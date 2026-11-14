from __future__ import annotations

from pathlib import Path
from typing import Any

from .llm_interpreter import (
    InterpreterError,
    configured_provider,
    interpret_with_provider,
)
from .schemas import EvidenceOverlay, EvidenceRef, FinalAnswer, LLMProviderConfig, PlanStep, QuestionSpec
from .ocr import ocr_is_available, paddle_ocr_is_available
from .gemini_vision import GeminiVisionError, MAX_REVIEW_CANDIDATES, review_detection_semantics
from .tools import (
    IFC_ENTITY_TYPES,
    interpret_question,
    query_dxf_named_blocks,
    calculate_dxf_room_area,
    query_ifc_count,
    search_pdf_ocr,
    search_pdf_text,
    search_raster_ocr,
    search_svg_text,
    tool_registry,
)
from .vision_models import (
    VisionInferenceError,
    capability_status,
    detect_objects,
    load_source_image,
    segment_detections,
    segment_floorplan_cubicasa,
)


def available_tools() -> list[dict[str, Any]]:
    try:
        import ifcopenshell  # noqa: F401
        ifc_available = True
    except ImportError:
        ifc_available = False
    try:
        import ezdxf  # noqa: F401
        dxf_available = True
    except ImportError:
        dxf_available = False
    try:
        import pymupdf  # noqa: F401
        pdf_available = True
    except ImportError:
        pdf_available = False
    vision = capability_status()
    local_ocr_available = ocr_is_available()
    registry = []
    for spec in tool_registry():
        installed = {
            "ifc_entity_count": ifc_available,
            "dxf_named_block_count": dxf_available,
            "dxf_room_area": dxf_available,
            "pdf_text_search": pdf_available,
            "grounding_dino_detection": vision["grounding_dino"],
            "sam2_instance_segmentation": vision["sam2"],
            "cubicasa_floorplan_segmentation": vision["cubicasa"],
            "paddle_ocr_text_search": vision["paddle_ocr"],
            "gemini_vl_semantic_review": (
                vision["gemini_vl"] and vision["grounding_dino"]
            ),
            "local_ocr_text_search": local_ocr_available,
            "svg_text_search": True,
        }[spec.name]
        registry.append({
            **spec.model_dump(),
            "available": installed,
            "requires_user_configuration": spec.name in {
                "gemini_vl_semantic_review", "local_ocr_text_search"
            },
        })
    return registry


def _abstain(
    question_spec: QuestionSpec,
    message: str,
    trace: list[PlanStep],
    *,
    status: str = "unable",
) -> FinalAnswer:
    return FinalAnswer(
        status=status, answer=message, question_spec=question_spec, trace=trace,
        validation="No answer was marked supported because no applicable evidence-producing tool ran.",
    )


def _raster_vision_answer(
    document_id: str,
    relative_path: str,
    file_path: Path,
    document_format: str,
    question: str,
    spec: QuestionSpec,
    selected_tools: list[str],
    trace: list[PlanStep],
    *,
    page_number: int,
    gemini_vl_consent: bool,
) -> FinalAnswer:
    try:
        source = load_source_image(file_path, document_format, page_number)
        regions: list[dict[str, Any]] = []
        detections = []
        if "cubicasa_floorplan_segmentation" in selected_tools:
            regions = segment_floorplan_cubicasa(source)
            trace.append(PlanStep(
                tool_name="cubicasa_floorplan_segmentation",
                status="succeeded",
                summary=f"Segmented {len(regions)} source-aligned CubiCasa floor-plan regions.",
                evidence_count=len(regions),
            ))
            requested = set(spec.entity_concepts)
            if "space" in requested:
                requested.add("room")
            if "sanitary fixture" in requested:
                requested.update({"toilet", "sink"})
            if requested:
                regions = [
                    region for region in regions
                    if region["label"].casefold() in requested
                ]
        elif "grounding_dino_detection" in selected_tools:
            if not spec.entity_concepts:
                return _abstain(
                    spec,
                    "Object detection requires a recognized object class; no class was inferred.",
                    trace,
                )
            detections = detect_objects(source, spec.entity_concepts)
            trace.append(PlanStep(
                tool_name="grounding_dino_detection",
                status="succeeded",
                summary=(
                    f"Detected {len(detections)} candidate objects with Grounding DINO Tiny "
                    "using overlapping high-resolution tiles."
                ),
                evidence_count=len(detections),
            ))
            if "sam2_instance_segmentation" in selected_tools and detections:
                masks = segment_detections(source, detections)
                regions = [
                    {
                        "label": detection.label,
                        "score": confidence,
                        "bbox": [
                            min(point[0] for point in polygons[0]),
                            min(point[1] for point in polygons[0]),
                            max(point[0] for point in polygons[0]),
                            max(point[1] for point in polygons[0]),
                        ],
                        "polygons": polygons,
                        "detection": detection,
                    }
                    for detection, polygons, confidence in masks
                ]
                trace.append(PlanStep(
                    tool_name="sam2_instance_segmentation",
                    status="succeeded",
                    summary=f"Generated {len(regions)} SAM 2.1 masks from detector boxes.",
                    evidence_count=len(regions),
                ))
        else:
            return _abstain(
                spec,
                "No compatible local vision model is installed with cached weights.",
                trace,
            )
    except VisionInferenceError as exc:
        tool_name = (
            "cubicasa_floorplan_segmentation"
            if "cubicasa_floorplan_segmentation" in selected_tools
            else "grounding_dino_detection"
        )
        return FinalAnswer(
            status="error",
            answer="The selected specialist vision model could not process this drawing.",
            question_spec=spec,
            trace=trace + [PlanStep(tool_name=tool_name, status="failed", summary=str(exc))],
            validation="Vision inference failed; no answer was returned.",
        )

    evidence: list[EvidenceRef] = []
    overlays: list[EvidenceOverlay] = []
    model_name = (
        "CubiCasa5K"
        if "cubicasa_floorplan_segmentation" in selected_tools
        else "Grounding DINO Tiny"
    )
    source_tool = (
        "cubicasa_floorplan_segmentation"
        if model_name == "CubiCasa5K"
        else "grounding_dino_detection"
    )
    if "grounding_dino_detection" in selected_tools:
        for index, detection in enumerate(detections):
            evidence_id = f"{document_id}-dino-p{page_number}-{index}"
            evidence.append(EvidenceRef(
                document_id=document_id,
                path=relative_path,
                page=page_number if document_format == "pdf" else None,
                entity_type=spec.entity_concepts[0] if spec.entity_concepts else detection.label,
                extracted_content=f"{detection.label} (confidence {detection.score:.3f})",
                bbox=list(detection.bbox),
                coordinate_system=source.coordinate_system,
                extraction_method="Grounding DINO Tiny tiled object detection",
                source_tool_version="0.1.0",
            ))
            overlays.append(EvidenceOverlay(
                overlay_id=evidence_id,
                document_id=document_id,
                page_or_view_id=str(page_number) if document_format == "pdf" else None,
                overlay_type="bounding_box",
                geometry={
                    "bbox": list(detection.bbox),
                    "native_width": source.native_width,
                    "native_height": source.native_height,
                    "confidence": detection.score,
                },
                coordinate_system=source.coordinate_system,
                label=f"{detection.label} · {detection.score:.2f}",
                class_name=detection.label,
                source_tool=source_tool,
                model_name=model_name,
                is_model_output=True,
                evidence_ids=[evidence_id],
            ))
    for index, region in enumerate(regions):
        detection = region.get("detection")
        evidence_id = f"{document_id}-mask-p{page_number}-{index}"
        bbox = region["bbox"]
        evidence.append(EvidenceRef(
            document_id=document_id,
            path=relative_path,
            page=page_number if document_format == "pdf" else None,
            entity_type=spec.entity_concepts[0] if spec.entity_concepts else region["label"],
            extracted_content=f"{region['label']} (confidence {region['score']:.3f})",
            bbox=list(bbox),
            geometry={"polygons": region.get("polygons", [region.get("points", [])])},
            coordinate_system=source.coordinate_system,
            extraction_method=(
                "SAM 2.1 Hiera Small promptable mask"
                if detection is not None
                else "CubiCasa5K pretrained floor-plan segmentation"
            ),
            source_tool_version="0.1.0",
        ))
        overlay_type = (
            "instance_mask"
            if detection is not None or region["label"] in {"window", "door"}
            else "semantic_mask"
        )
        overlays.append(EvidenceOverlay(
            overlay_id=evidence_id,
            document_id=document_id,
            page_or_view_id=str(page_number) if document_format == "pdf" else None,
            overlay_type=overlay_type,
            geometry={
                "polygons": region.get("polygons", [region.get("points", [])]),
                "bbox": list(bbox),
                "native_width": source.native_width,
                "native_height": source.native_height,
                "confidence": region["score"],
                "opacity": 0.24,
            },
            coordinate_system=source.coordinate_system,
            label=f"{region['label']} · {region['score']:.2f}",
            class_name=region["label"],
            source_tool=(
                "sam2_instance_segmentation"
                if detection is not None
                else "cubicasa_floorplan_segmentation"
            ),
            model_name="SAM 2.1 Hiera Small" if detection is not None else "CubiCasa5K",
            is_model_output=True,
            evidence_ids=[evidence_id],
        ))

    if "gemini_vl_semantic_review" in selected_tools:
        if not gemini_vl_consent:
            return _abstain(
                spec,
                "Gemini visual review was selected without explicit image-sharing consent.",
                trace + [PlanStep(
                    tool_name="gemini_vl_semantic_review",
                    status="skipped",
                    summary="No drawing image was sent; per-request Gemini consent is required.",
                )],
            )
        if not any(overlay.overlay_type == "bounding_box" for overlay in overlays):
            trace.append(PlanStep(
                tool_name="gemini_vl_semantic_review",
                status="skipped",
                summary="No detector candidates were produced; no image was sent to Gemini.",
            ))
            review_notes = []
        else:
            try:
                detector_overlays = [
                    overlay
                    for overlay in overlays
                    if overlay.overlay_type == "bounding_box"
                ][:MAX_REVIEW_CANDIDATES]
                candidates = []
                for overlay in detector_overlays:
                    bbox = overlay.geometry["bbox"] if overlay.geometry else None
                    if not bbox:
                        continue
                    candidates.append({
                        "candidate_id": overlay.overlay_id,
                        "label": overlay.class_name or "object",
                        "score": overlay.geometry.get("confidence"),
                        "bbox_normalized": [
                            bbox[0] / source.native_width,
                            bbox[1] / source.native_height,
                            bbox[2] / source.native_width,
                            bbox[3] / source.native_height,
                        ],
                    })
                review = review_detection_semantics(
                    source.image,
                    question,
                    candidates,
                )
                review_notes = [
                    (
                        f"{item['candidate_id']}: label mismatch"
                        + (f" — {item['note']}" if item["note"].strip() else "")
                        if not item["matches_label"]
                        else f"{item['candidate_id']}: {item['note']}"
                    )
                    for item in review["matches"]
                    if item["note"].strip() or not item["matches_label"]
                ]
                trace.append(PlanStep(
                    tool_name="gemini_vl_semantic_review",
                    status="succeeded",
                    summary=(
                        f"{review['model']} reviewed {len(review['matches'])} detector candidate labels; "
                        "it did not create an answer or alter counts."
                    ),
                    evidence_count=len(review["matches"]),
                ))
            except GeminiVisionError as exc:
                review_notes = []
                trace.append(PlanStep(
                    tool_name="gemini_vl_semantic_review",
                    status="failed",
                    summary=str(exc),
                ))
    else:
        review_notes = []

    if not evidence:
        trace.append(PlanStep(
            tool_name="evidence_validator",
            status="skipped",
            summary="The selected model produced no regions above its configured confidence threshold.",
        ))
        return _abstain(
            spec,
            "No objects were detected above the model threshold; this does not establish that none are present.",
            trace,
        )

    count = len(evidence)
    if "sam2_instance_segmentation" in selected_tools and detections:
        count = len(detections)
    if "cubicasa_floorplan_segmentation" in selected_tools:
        count = len(regions)
    target = spec.entity_concepts[0] if spec.entity_concepts else "objects"
    answer_text = f"{count} {target}{'' if count == 1 else 's'} detected by {model_name}"
    if spec.operation == "count":
        answer_text += " (model prediction, not independently verified)"
    warnings = [
        "Model detections/segmentations are not ground truth or calibrated measurements.",
        "Counts are limited to retained regions above the configured model threshold.",
    ]
    if document_format == "pdf":
        warnings.append(f"Only selected PDF page {page_number} was processed.")
    if review_notes:
        warnings.extend(f"Gemini semantic review: {note}" for note in review_notes)
    validation = (
        "Source coordinates were mapped from the rendered page or image to native drawing coordinates. "
        "Model regions were not independently validated."
    )
    trace.append(PlanStep(
        tool_name="evidence_validator",
        status="skipped",
        summary=validation,
        evidence_count=len(evidence),
    ))
    return FinalAnswer(
        status="partial",
        answer=answer_text,
        value=count,
        unit="count" if spec.operation == "count" else None,
        evidence=evidence,
        overlays=overlays,
        warnings=warnings,
        assumptions=[
            f"Selected specialist: {model_name}.",
            "No calibrated physical scale was applied.",
        ],
        question_spec=spec,
        trace=trace,
        validation=validation,
    )


def answer_question(
    document_id: str,
    relative_path: str,
    file_path: Path,
    document_format: str,
    question: str,
    llm_config: LLMProviderConfig | None = None,
    page_number: int | None = None,
    gemini_vl_consent: bool = False,
) -> FinalAnswer:
    if document_format in {"png", "jpg", "jpeg"}:
        local_spec = interpret_question(question)
        try:
            provider = configured_provider(llm_config)
        except InterpreterError as exc:
            return _abstain(
                local_spec,
                "The configured Groq planner is invalid; no vision tool was run.",
                [PlanStep(tool_name="groq_question_planner", status="failed", summary=str(exc))],
                status="error",
            )
        raster_tools = [
            item
            for item in available_tools()
            if document_format in item["input_formats"] and item["available"]
        ]
        if not gemini_vl_consent:
            raster_tools = [
                item for item in raster_tools
                if item["name"] != "gemini_vl_semantic_review"
            ]
        allowed_names = [item["name"] for item in raster_tools]
        try:
            if provider is not None and allowed_names:
                spec, interpreter = interpret_with_provider(
                    question, llm_config, allowed_tools=allowed_names
                )
            else:
                spec, interpreter = local_spec, "deterministic"
        except InterpreterError as exc:
            return FinalAnswer(
                status="error",
                answer="Groq could not create a valid tool plan for this raster question.",
                question_spec=local_spec,
                trace=[PlanStep(
                    tool_name="groq_question_planner",
                    status="failed",
                    summary=str(exc),
                )],
                validation="Execution stopped because the structured plan was invalid.",
            )
        trace = [
            PlanStep(
                tool_name="question_interpreter",
                status="succeeded",
                summary=(
                    f"{interpreter} planned operation={spec.operation}; "
                    f"entities={spec.entity_concepts or ['unspecified']}; "
                    f"tools={spec.recommended_tools or ['local capability router']}."
                ),
            ),
            PlanStep(
                tool_name="capability_router",
                status="succeeded",
                summary="Selected only locally available specialist models; Groq received text planning context only.",
            ),
        ]
        if spec.operation == "find_text":
            ocr_tools = {"paddle_ocr_text_search", "local_ocr_text_search"}
            if spec.recommended_tools and not ocr_tools.intersection(spec.recommended_tools):
                return _abstain(
                    spec,
                    "The planner did not select an available OCR tool for this text question.",
                    trace,
                )
            result = search_raster_ocr(document_id, relative_path, file_path, spec)
            tool_name = (
                "paddle_ocr_text_search"
                if paddle_ocr_is_available()
                else "local_ocr_text_search"
            )
            trace.append(PlanStep(
                tool_name=tool_name,
                status="failed" if result.status == "error" else "succeeded" if result.evidence else "skipped",
                summary=(
                    f"Extracted {len(result.evidence)} source-aligned OCR text regions."
                    if result.evidence
                    else result.error or "; ".join(result.warnings) or "No OCR text was found."
                ),
                evidence_count=len(result.evidence),
            ))
            if result.status == "error":
                return FinalAnswer(
                    status="error",
                    answer="Local OCR could not process this drawing.",
                    evidence=result.evidence,
                    overlays=result.overlays,
                    warnings=result.warnings,
                    question_spec=spec,
                    trace=trace,
                    validation=result.error or "OCR engine failure.",
                )
            if not result.evidence:
                return _abstain(spec, "No readable text could be retrieved from the drawing.", trace)
            return FinalAnswer(
                status="partial",
                answer=f"Locally recognized text: {result.value}",
                value=result.value,
                evidence=result.evidence,
                overlays=result.overlays,
                warnings=result.warnings,
                question_spec=spec,
                trace=trace + [PlanStep(
                    tool_name="evidence_validator",
                    status="skipped",
                    summary="OCR text is mapped to source pixels but may contain recognition errors.",
                    evidence_count=len(result.evidence),
                )],
                validation="Local OCR text was mapped to source regions; recognition was not independently corrected.",
            )

        selected_tools = list(spec.recommended_tools)
        if not selected_tools:
            names = set(allowed_names)
            if (
                spec.operation in {"count", "describe"}
                and "cubicasa_floorplan_segmentation" in names
                and any(concept in {"window", "door", "room", "space"} for concept in spec.entity_concepts)
            ):
                selected_tools.append("cubicasa_floorplan_segmentation")
            elif spec.operation in {"count", "describe"} and "grounding_dino_detection" in names:
                selected_tools.append("grounding_dino_detection")
            if (
                "grounding_dino_detection" in selected_tools
                and "sam2_instance_segmentation" in names
                and any(term in question.casefold() for term in ("segment", "mask", "highlight"))
            ):
                selected_tools.append("sam2_instance_segmentation")
            if (
                gemini_vl_consent
                and "gemini_vl_semantic_review" in names
                and "grounding_dino_detection" in selected_tools
                and spec.operation == "describe"
            ):
                selected_tools.append("gemini_vl_semantic_review")
        if not selected_tools or not any(
            name in selected_tools
            for name in (
                "grounding_dino_detection",
                "cubicasa_floorplan_segmentation",
            )
        ):
            return _abstain(
                spec,
                "No compatible local detection or floor-plan segmentation weights are available; no visual answer was claimed.",
                trace + [PlanStep(
                    tool_name="vision_capability_check",
                    status="skipped",
                    summary="Install the optional vision dependencies and cache the selected pretrained weights.",
                )],
            )
        return _raster_vision_answer(
            document_id,
            relative_path,
            file_path,
            document_format,
            question,
            spec,
            selected_tools,
            trace,
            page_number=1,
            gemini_vl_consent=gemini_vl_consent,
        )

    try:
        allowed_tools = [
            item["name"]
            for item in available_tools()
            if document_format in item["input_formats"]
            and item["available"]
            and (
                gemini_vl_consent
                or item["name"] != "gemini_vl_semantic_review"
            )
        ]
        spec, interpreter = interpret_with_provider(
            question,
            llm_config,
            allowed_tools=allowed_tools,
        )
    except InterpreterError as exc:
        spec = interpret_question(question)
        return FinalAnswer(
            status="error",
            answer="The configured question interpreter failed; no document tool was run.",
            question_spec=spec,
            trace=[
                PlanStep(
                    tool_name="question_interpreter",
                    status="failed",
                    summary=str(exc),
                )
            ],
            validation="Interpreter failure; execution stopped before selecting a tool.",
        )
    trace = [
        PlanStep(
            tool_name="question_interpreter",
            status="succeeded",
            summary=(
                f"{interpreter} planned operation={spec.operation}; "
                f"entities={spec.entity_concepts or ['unspecified']}; "
                f"tools={spec.recommended_tools or ['local capability router']}; "
                f"scope={spec.scope or 'document'}"
            ),
        ),
        PlanStep(
            tool_name="capability_router",
            status="succeeded",
            summary=f"Selected route from the actual {document_format.upper()} document format and registered tool capabilities.",
        ),
    ]

    if document_format == "pdf" and spec.operation in {"count", "describe"}:
        selected_tools = list(spec.recommended_tools)
        if not selected_tools:
            names = {
                item["name"]
                for item in available_tools()
                if item["available"] and document_format in item["input_formats"]
            }
            if not gemini_vl_consent:
                names.discard("gemini_vl_semantic_review")
            if (
                "cubicasa_floorplan_segmentation" in names
                and any(concept in {"window", "door", "room", "space"} for concept in spec.entity_concepts)
            ):
                selected_tools.append("cubicasa_floorplan_segmentation")
            elif "grounding_dino_detection" in names:
                selected_tools.append("grounding_dino_detection")
            if (
                "grounding_dino_detection" in selected_tools
                and "sam2_instance_segmentation" in names
                and any(term in question.casefold() for term in ("segment", "mask", "highlight"))
            ):
                selected_tools.append("sam2_instance_segmentation")
            if (
                gemini_vl_consent
                and "gemini_vl_semantic_review" in names
                and "grounding_dino_detection" in selected_tools
                and spec.operation == "describe"
            ):
                selected_tools.append("gemini_vl_semantic_review")
        if any(
            name in selected_tools
            for name in (
                "grounding_dino_detection",
                "cubicasa_floorplan_segmentation",
            )
        ):
            return _raster_vision_answer(
                document_id,
                relative_path,
                file_path,
                document_format,
                question,
                spec,
                selected_tools,
                trace,
                page_number=page_number or 1,
                gemini_vl_consent=gemini_vl_consent,
            )

    if (
        document_format == "ifc"
        and spec.operation == "count"
        and (
            not spec.recommended_tools
            or "ifc_entity_count" in spec.recommended_tools
        )
    ):
        if len(spec.entity_concepts) != 1:
            return _abstain(spec, "I could not identify one unambiguous IFC entity to count.", trace)
        if spec.entity_concepts[0] not in IFC_ENTITY_TYPES:
            return _abstain(spec, f"No registered IFC entity mapping is available for {spec.entity_concepts[0]}.", trace)
        trace.append(PlanStep(
            tool_name="ifc_entity_count",
            status="running",
            summary=f"Querying typed IFC elements{f' on {spec.scope}' if spec.scope else ''}.",
        ))
        result = query_ifc_count(document_id, relative_path, file_path, spec)
        trace[-1] = PlanStep(
            tool_name="ifc_entity_count",
            status="succeeded" if result.status == "supported" else "failed",
            summary=(
                f"Counted {len(result.evidence)} IFC element records."
                if result.status == "supported"
                else result.error or "; ".join(result.warnings) or "The IFC query did not complete."
            ),
            evidence_count=len(result.evidence),
        )
    elif (
        document_format == "dxf"
        and spec.operation in {"measure", "calculate"}
        and "area" in spec.original_question.casefold()
        and any(concept in {"room", "space"} for concept in spec.entity_concepts)
        and (
            not spec.recommended_tools
            or "dxf_room_area" in spec.recommended_tools
        )
    ):
        trace.append(PlanStep(
            tool_name="dxf_room_area",
            status="running",
            summary="Finding closed polylines on the explicitly named ROOM_OUTLINE layer and calculating native polygon areas.",
        ))
        result = calculate_dxf_room_area(document_id, relative_path, file_path, spec)
        trace[-1] = PlanStep(
            tool_name="dxf_room_area",
            status="succeeded" if result.evidence else "skipped" if result.status == "abstain" else "failed",
            summary=(
                f"Calculated areas for {len(result.evidence)} closed room outlines."
                if result.evidence
                else result.error or "; ".join(result.warnings) or "No valid closed room outlines."
            ),
            evidence_count=len(result.evidence),
        )
    elif (
        document_format == "dxf"
        and spec.operation == "count"
        and (
            not spec.recommended_tools
            or "dxf_named_block_count" in spec.recommended_tools
        )
    ):
        trace.append(PlanStep(
            tool_name="dxf_named_block_count",
            status="running",
            summary="Inspecting modelspace INSERT names for explicit semantic labels.",
        ))
        result = query_dxf_named_blocks(document_id, relative_path, file_path, spec)
        trace[-1] = PlanStep(
            tool_name="dxf_named_block_count",
            status="succeeded" if result.status == "supported" else "skipped" if result.status == "abstain" else "failed",
            summary=f"Returned {len(result.evidence)} labelled block references."
            if result.status == "supported"
            else result.error or "; ".join(result.warnings) or "No usable block result.",
            evidence_count=len(result.evidence),
        )
    elif (
        document_format == "pdf"
        and (
            not spec.recommended_tools
            or any(
                name in spec.recommended_tools
                for name in ("pdf_text_search", "local_ocr_text_search")
            )
        )
    ):
        trace.append(PlanStep(
            tool_name="pdf_text_search",
            status="running",
            summary="Searching selectable page text and retaining page-coordinate evidence spans.",
        ))
        result = search_pdf_text(
            document_id,
            relative_path,
            file_path,
            spec,
            page_number=page_number,
        )
        trace[-1] = PlanStep(
            tool_name="pdf_text_search",
            status="succeeded" if result.evidence else "skipped" if result.status == "abstain" else "failed",
            summary=f"Retrieved {len(result.evidence)} selectable text spans."
            if result.evidence
            else result.error or "; ".join(result.warnings) or "No text result.",
            evidence_count=len(result.evidence),
        )
        if (
            result.status == "abstain"
            and page_number is not None
            and "scanned pages require ocr" in " ".join(result.warnings).casefold()
        ):
            trace.append(PlanStep(
                tool_name="local_ocr_text_search",
                status="running",
                summary=f"Running local English OCR on the selected PDF page {page_number}.",
            ))
            result = search_pdf_ocr(
                document_id,
                relative_path,
                file_path,
                spec,
                page_number,
            )
            trace[-1] = PlanStep(
                tool_name="local_ocr_text_search",
                status="failed" if result.status == "error" else "succeeded" if result.evidence else "skipped",
                summary=(
                    f"Extracted {len(result.evidence)} source-aligned OCR text regions from page {page_number}."
                    if result.evidence
                    else result.error or "; ".join(result.warnings) or "No OCR text was found."
                ),
                evidence_count=len(result.evidence),
            )
    elif (
        document_format == "svg"
        and spec.operation in {"find_text", "describe"}
        and (
            not spec.recommended_tools
            or "svg_text_search" in spec.recommended_tools
        )
    ):
        trace.append(PlanStep(
            tool_name="svg_text_search",
            status="running",
            summary="Searching native SVG text elements and retaining source view coordinates.",
        ))
        result = search_svg_text(document_id, relative_path, file_path, spec)
        trace[-1] = PlanStep(
            tool_name="svg_text_search",
            status="succeeded" if result.evidence else "skipped" if result.status == "abstain" else "failed",
            summary=f"Retrieved {len(result.evidence)} native SVG text elements."
            if result.evidence
            else result.error or "; ".join(result.warnings) or "No SVG text result.",
            evidence_count=len(result.evidence),
        )
    else:
        reason = {
            "png": "Raster object detection and OCR are unavailable; no visual count is claimed.",
            "jpg": "Raster object detection and OCR are unavailable; no visual count is claimed.",
            "jpeg": "Raster object detection and OCR are unavailable; no visual count is claimed.",
            "svg": "The SVG route supports native text search only; unlabelled vector geometry is not interpreted.",
            "ifc": "The registered IFC tool currently supports typed counts only.",
            "dxf": "The registered DXF tool currently supports named block counts only.",
        }.get(document_format, f"No registered answer tool supports {document_format.upper()}.")
        trace.append(PlanStep(
            tool_name="capability_abstention",
            status="skipped",
            summary=reason,
        ))
        return _abstain(spec, reason, trace)

    if result.status == "error":
        return FinalAnswer(
            status="error",
            answer="The selected document tool failed; no answer was produced.",
            evidence=result.evidence,
            overlays=result.overlays,
            warnings=result.warnings,
            assumptions=result.assumptions,
            question_spec=spec,
            trace=trace,
            validation=result.error or "Tool error.",
        )
    if result.status == "abstain" or not result.evidence:
        return FinalAnswer(
            status="unable",
            answer="I could not produce a supported answer from the available document evidence.",
            evidence=result.evidence,
            overlays=result.overlays,
            warnings=result.warnings,
            assumptions=result.assumptions,
            question_spec=spec,
            trace=trace,
            validation="Insufficient or ambiguous evidence; abstained.",
        )

    if result.unit in {"m2", "ft2"} and isinstance(result.value, (int, float)):
        meter_total = sum(
            float(ref.geometry["area_m2"])
            for ref in result.evidence
            if ref.geometry and isinstance(ref.geometry.get("area_m2"), (int, float))
        )
        expected = meter_total * (10.7639104167 if result.unit == "ft2" else 1)
        evidence_valid = abs(expected - float(result.value)) <= max(1e-8, abs(expected) * 1e-9)
        validation = (
            "Area sum matches the per-outline source geometries."
            if evidence_valid
            else "Area sum does not match the returned per-outline evidence."
        )
        if result.warnings:
            validation += " Some source geometries were excluded; see warnings."
        final_status = "supported" if evidence_valid and not result.warnings else "partial"
        if not evidence_valid:
            final_status = "uncertain"
        answer_text = (
            f"{float(result.value):.6g} {result.unit} total from {len(result.evidence)} closed room outlines"
            if evidence_valid
            else "The calculated area could not be verified against its source outlines."
        )
    elif result.status == "supported" and isinstance(result.value, int):
        evidence_valid = result.value == len(result.evidence)
        if evidence_valid:
            validation = "Count equals the number of returned, typed IFC/DXF entity records."
            final_status = "supported"
            if (
                document_format == "dxf"
                and result.evidence[0].entity_type.endswith(":DOOR")
                and result.evidence[0].extraction_method
                == "ezdxf entity query on an explicitly named semantic layer"
            ):
                answer_text = f"{result.value} door geometries on the explicitly named DOOR layer"
                validation = "Count equals the returned LWPOLYLINE records on the explicitly named DOOR layer."
            else:
                answer_text = f"{result.value} {spec.entity_concepts[0]}{'s' if result.value != 1 else ''}"
        else:
            validation = "Count did not match returned entity evidence; result downgraded."
            final_status = "uncertain"
            answer_text = "The extracted count could not be verified against its evidence."
        if result.warnings:
            final_status = "partial"
            validation += " Warnings remain; review the scope limitations."
    else:
        validation = "Verbatim text evidence is available, but no validated quantity parser supports this answer."
        final_status = "partial"
        answer_text = (
            f"Relevant extracted text: {result.value}"
            if result.value
            else "Relevant text was retrieved, but it does not resolve the question."
        )

    answer_assumptions = list(result.assumptions)
    warnings = list(result.warnings)
    trace.append(PlanStep(
        tool_name="evidence_validator",
        status="succeeded" if final_status == "supported" else "skipped",
        summary=validation,
        evidence_count=len(result.evidence),
    ))
    return FinalAnswer(
        status=final_status,
        answer=answer_text,
        value=result.value,
        unit=result.unit,
        calculation=result.calculation,
        evidence=result.evidence,
        overlays=result.overlays,
        warnings=warnings,
        assumptions=answer_assumptions,
        question_spec=spec,
        trace=trace,
        validation=validation,
    )
