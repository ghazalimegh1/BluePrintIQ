from __future__ import annotations

import io
import re
import string
import xml.etree.ElementTree as ET
from collections import Counter
from difflib import get_close_matches
from pathlib import Path
from typing import Any

from .ingestion import read_pdf_text, read_svg_viewbox, render_dxf_preview, render_pdf_page
from .ocr import (
    OCRError,
    OCRLine,
    OCRUnavailable,
    extract_ocr_lines,
    extract_paddle_ocr_lines,
    paddle_ocr_is_available,
)
from .schemas import EvidenceOverlay, EvidenceRef, QuestionSpec, ToolResult, ToolSpec


TOOL_VERSION = "0.1.0"
DXF_ROOM_AREA_LAYER = "ROOM_OUTLINE"
DXF_DOOR_LAYER = "DOOR"
IFC_ENTITY_TYPES = {
    "door": ("IfcDoor",),
    "window": ("IfcWindow",),
    "wall": ("IfcWall",),
    "room": ("IfcSpace",),
    "space": ("IfcSpace",),
    "column": ("IfcColumn",),
    "beam": ("IfcBeam",),
    "stair": ("IfcStair",),
    "slab": ("IfcSlab",),
    "roof": ("IfcRoof",),
    "furniture": ("IfcFurnishingElement",),
    "sanitary fixture": ("IfcSanitaryTerminal",),
    "storey": ("IfcBuildingStorey",),
}
ENTITY_TERMS = {
    "door": ("door", "doors", "doorway", "doorways", "ovi", "ovet", "ovea", "ovia", "ovien"),
    "window": ("window", "windows", "ikkuna", "ikkunat", "ikkunaa", "ikkunoita", "ikkunoiden"),
    "wall": ("wall", "walls", "seinä", "seinät"),
    "room": ("room", "rooms", "huone", "huoneet", "huonetta"),
    "space": ("space", "spaces", "tila", "tilat", "huonetila"),
    "column": ("column", "columns", "pilari", "pilarit"),
    "beam": ("beam", "beams", "palkki", "palkit"),
    "stair": ("stair", "stairs", "staircase", "staircases", "porras", "portaat"),
    "slab": ("slab", "slabs", "floor slab", "floor slabs"),
    "roof": ("roof", "roofs"),
    "furniture": ("furniture",),
    "sanitary fixture": ("sanitary fixture", "sanitary fixtures", "toilet", "toilets", "sink", "sinks"),
    # Benchmark room-program and fixture classes.  These remain distinct so a
    # detector/property adapter can preserve the requested class instead of
    # reducing every sanitary object to one generic label.
    "toilet": ("toilet", "toilets", "toilet bowl", "toilet bowls", "wc", "wcs", "wc seat", "wc seats"),
    "sink": ("sink", "sinks", "wash basin", "wash basins", "washbasin", "washbasins"),
    "shower": ("shower", "showers"),
    "bathtub": ("bathtub", "bathtubs", "bath tub", "bath tubs"),
    "bedroom": ("bedroom", "bedrooms"),
    "kitchen": ("kitchen", "kitchens"),
    "bathroom": ("bathroom", "bathrooms", "bath room", "bath rooms"),
    "separate wc": ("separate wc", "separate wcs", "separate toilet", "guest wc"),
    "sauna": ("sauna", "saunas"),
    "balcony": ("balcony", "balconies"),
    "storey": ("storey", "storeys", "story", "stories", "kerros", "kerrosta", "kerrokset", "kerroksia"),
}
CORRECTION_TERMS = tuple(sorted({term for terms in ENTITY_TERMS.values() for term in terms if " " not in term}, key=len))
COMMON_CORRECTIONS = {
    "windom": "window",
    "windoms": "windows",
    "widnow": "window",
    "widnows": "windows",
    "doorr": "door",
    "doorrs": "doors",
}
STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "could", "do", "does",
    "for", "from", "how", "in", "is", "it", "many", "me", "of", "on", "or", "please",
    "show", "shown", "the", "there", "this", "to", "what", "which", "with", "would",
    "text", "texts", "label", "labels", "annotation", "annotations", "drawing",
    "plan", "sheet", "readable", "visible", "written", "note", "notes",
}


def interpret_question(question: str) -> QuestionSpec:
    corrected_question = question.casefold()
    corrections: list[str] = []
    for match in re.finditer(r"\b[a-zA-Z]{4,}\b", corrected_question):
        token = match.group(0)
        replacement = COMMON_CORRECTIONS.get(token)
        if replacement is None and token not in CORRECTION_TERMS:
            match_candidates = get_close_matches(token, CORRECTION_TERMS, n=1, cutoff=0.88)
            replacement = match_candidates[0] if match_candidates else None
        if replacement and replacement != token:
            corrected_question = re.sub(rf"\b{re.escape(token)}\b", replacement, corrected_question)
            corrections.append(f"{token} → {replacement}")
    lowered = corrected_question
    targets: list[str] = []
    for concept, terms in ENTITY_TERMS.items():
        if any(re.search(rf"\b{re.escape(term)}\b", lowered) for term in terms):
            targets.append(concept)
    specific_fixtures = {"toilet", "sink", "shower", "bathtub"}
    if specific_fixtures.intersection(targets):
        targets = [concept for concept in targets if concept != "sanitary fixture"]
    specific_room_program = {
        "bedroom", "kitchen", "bathroom", "separate wc", "sauna", "balcony"
    }
    if specific_room_program.intersection(targets):
        targets = [concept for concept in targets if concept != "room"]
    # A floor/level count is a storey query, while "windows on Level 1"
    # remains a window query with a spatial scope.
    if (
        "floor slab" not in lowered
        and re.search(r"\b(?:how many|number of)\s+(?:floors?|storeys?|stories?|levels?)\b", lowered)
        and "storey" not in targets
    ):
        targets.append("storey")
    if (
        "how many" in lowered
        or "kuinka monta" in lowered
        or "montako" in lowered
        or re.search(r"\b(count|number of|lukumäärä|määrä)\b", lowered)
    ):
        operation = "count"
    elif any(term in lowered for term in ("area", "length", "volume", "perimeter", "height", "width")):
        operation = "measure"
    elif any(term in lowered for term in ("find", "search", "show me", "quote", "where is", "which text", "etsi", "näytä")):
        operation = "find_text"
    elif any(term in lowered for term in ("segment", "segmentation", "mask", "detect", "highlight")):
        operation = "describe"
    elif targets:
        operation = "describe"
    else:
        operation = "find_text"

    # Match the dataset's evaluation taxonomy.  A measurement operation is
    # split by requested physical dimension; property, schedule, summary, and
    # comparison questions are intentionally classified as text because that
    # is how the supplied benchmark labels them.
    composite_summary = (
        re.search(r"\bwhat\s+are\b", lowered)
        and (
            re.search(r"\b(number of|area|distribution|breakdown|percentage|percent|heights?)\b", lowered)
            or lowered.count(" and ") >= 1
        )
    )
    if composite_summary or (
        re.search(r"\b(?:height|heights)\b", lowered)
        and re.search(r"\b(?:each|every|level|storey|floor)\b", lowered)
    ):
        # IFC summaries and property schedules are labelled text in the
        # benchmark, even if one requested field is numeric.
        question_type = "text"
    elif operation == "count":
        question_type = "count"
    elif re.search(r"\b(volume|volumes|cubic|m3|m\^3|m³)\b", lowered):
        question_type = "volume"
    elif re.search(r"\b(length|lengths|long|perimeter|span|distance|m\b|metre|meter|feet|foot|ft)\b", lowered):
        question_type = "length"
    elif re.search(r"\b(area|areas|floor area|footprint|square meters?|square metres?|m2|m\^2|m²)\b", lowered):
        question_type = "area"
    elif operation == "find_text" or targets:
        question_type = "text"
    else:
        question_type = "other"

    if composite_summary:
        intent = "aggregate"
    elif operation == "count":
        intent = "count"
    elif any(term in lowered for term in ("largest", "smallest", "widest", "narrowest", "greatest", "least", "most", "highest", "lowest")):
        intent = "compare"
    elif any(term in lowered for term in ("total", "distribution", "breakdown", "percentage", "percent", "each type", "by function", "by level")):
        intent = "aggregate"
    elif any(term in lowered for term in ("what are", "which", "what is", "name", "type", "function", "property", "material", "rating")):
        intent = "retrieve"
    elif operation == "measure":
        intent = "measure"
    elif any(term in lowered for term in ("summary", "summarize", "describe")):
        intent = "summarize"
    else:
        intent = "describe"

    scope = None
    quoted = re.search(r"""['"“](.+?)['"”]""", question)
    if quoted:
        scope = quoted.group(1).strip()
    else:
        floor = re.search(
            r"\b(?:on|at|for|of)\s+(?:the\s+)?((?:\d+(?:st|nd|rd|th)?\s+)?(?:floor|level|storey|story)(?:\s+\d+)?)\b",
            question,
            flags=re.IGNORECASE,
        )
        if floor:
            scope = floor.group(1)

    unit = None
    if re.search(r"\b(?:square|sq\.?)\s*(?:meters?|metres?|m)\b", lowered):
        unit = "m2"
    elif re.search(r"\b(?:square|sq\.?)\s*(?:feet|foot|ft)\b", lowered):
        unit = "ft2"
    else:
        unit_match = re.search(r"\b(m2|m\^2|ft2|ft\^2|m3|m\^3|mm|cm|m|ft|in)\b|m²|m³", lowered)
        if unit_match:
            unit = unit_match.group(0)
    ambiguities: list[str] = []
    if len(targets) > 1:
        ambiguities.append(f"Multiple entity concepts detected: {', '.join(targets)}")
    if operation == "measure" and not unit:
        ambiguities.append("The requested measurement unit is not explicit")
    return QuestionSpec(
        original_question=question,
        corrections=corrections,
        operation=operation,
        question_type=question_type,
        intent=intent,
        entity_concepts=targets,
        scope=scope,
        output_unit=unit,
        ambiguities=ambiguities,
    )


def tool_registry() -> list[ToolSpec]:
    return [
        ToolSpec(
            name="svg_text_search",
            version=TOOL_VERSION,
            description="Search native SVG text and locate untransformed text anchors in viewBox coordinates.",
            operations=["find_text", "describe"],
            input_formats=["svg"],
            deterministic=True,
            limitations=[
                "Text anchors under SVG transforms are cited without an overlay",
                "Vector primitives are not treated as semantic objects",
            ],
        ),
        ToolSpec(
            name="grounding_dino_detection",
            version=TOOL_VERSION,
            description="Detect open-vocabulary construction-plan objects with tiled Grounding DINO Tiny inference.",
            operations=["count", "describe"],
            input_formats=["pdf", "png", "jpg", "jpeg"],
            deterministic=False,
            limitations=[
                "Requires cached Grounding DINO Tiny weights and the optional CPU vision dependencies",
                "Detection counts are model predictions and are returned as partial, not verified quantities",
                "High-resolution tiled inference can miss or duplicate small/overlapping symbols",
            ],
        ),
        ToolSpec(
            name="sam2_instance_segmentation",
            version=TOOL_VERSION,
            description="Generate source-aligned instance masks for Grounding DINO detections using SAM 2.1 Hiera Small.",
            operations=["count", "describe"],
            input_formats=["pdf", "png", "jpg", "jpeg"],
            deterministic=False,
            limitations=[
                "Requires cached SAM 2.1 Hiera Small weights and prompts from an object detector",
                "Masks inherit errors and omissions from their detector prompts",
            ],
        ),
        ToolSpec(
            name="cubicasa_floorplan_segmentation",
            version=TOOL_VERSION,
            description="Segment rooms and floor-plan icons using the official pretrained CubiCasa5K model.",
            operations=["count", "describe"],
            input_formats=["pdf", "png", "jpg", "jpeg"],
            deterministic=False,
            limitations=[
                "Requires the official CubiCasa source checkout and checkpoint, which is CC BY-NC 4.0",
                "The model was trained for floor plans and may not generalize to other drawing types",
                "Predicted regions are not manually verified or calibrated measurements",
            ],
        ),
        ToolSpec(
            name="paddle_ocr_text_search",
            version=TOOL_VERSION,
            description="Extract English text and source-aligned regions from raster drawings with PaddleOCR.",
            operations=["find_text"],
            input_formats=["pdf", "png", "jpg", "jpeg"],
            deterministic=False,
            limitations=[
                "Requires PaddlePaddle and PaddleOCR; first use may download OCR weights",
                "OCR can misread construction lettering and does not identify semantic objects",
                "Only the selected PDF page is processed",
            ],
        ),
        ToolSpec(
            name="gemini_vl_semantic_review",
            version=TOOL_VERSION,
            description="Use Gemini 3.5 Flash-Lite to review Grounding DINO candidate labels and ambiguity without answering or counting.",
            operations=["describe"],
            input_formats=["pdf", "png", "jpg", "jpeg"],
            deterministic=False,
            limitations=[
                "Requires GEMINI_API_KEY, the allowlisted free-tier GEMINI_MODEL, local Grounding DINO candidates, and per-request image-sharing consent",
                "Free-tier image and prompt content may be reviewed and used to improve Google's products; never submit sensitive or confidential drawings",
                "Free-tier Gemini cannot be used for API clients available to users in the EEA, UK, or Switzerland",
                "Semantic review is not ground truth and cannot answer counts or provide measurements",
            ],
        ),
        ToolSpec(
            name="ifc_entity_count",
            version=TOOL_VERSION,
            description="Count typed IFC elements, optionally constrained by spatial containment.",
            operations=["count"],
            input_formats=["ifc"],
            deterministic=True,
            limitations=["Requires IfcOpenShell; no 2D projection is generated for IFC selections"],
        ),
        ToolSpec(
            name="dxf_named_block_count",
            version=TOOL_VERSION,
            description="Count DXF INSERT instances only when block names explicitly identify the requested class.",
            operations=["count"],
            input_formats=["dxf"],
            deterministic=True,
            limitations=["Does not infer semantics from anonymous geometry or layer appearance"],
        ),
        ToolSpec(
            name="dxf_room_area",
            version=TOOL_VERSION,
            description="Calculate and project closed room-outline polygon areas from explicitly named DXF layers.",
            operations=["measure", "calculate"],
            input_formats=["dxf"],
            deterministic=True,
            limitations=[
                "Requires closed polylines on ROOM_OUTLINE and declared DXF insertion units",
                "Does not infer gross/net wall area or associate names with rooms",
            ],
        ),
        ToolSpec(
            name="pdf_text_search",
            version=TOOL_VERSION,
            description="Search selectable PDF text and return its page and exact text bounding box.",
            operations=["find_text", "describe", "measure", "count"],
            input_formats=["pdf"],
            deterministic=True,
            limitations=["Retrieval is not a validated schedule/quantity parser; scanned pages need OCR"],
        ),
        ToolSpec(
            name="local_ocr_text_search",
            version=TOOL_VERSION,
            description="Extract searchable English text and source-aligned text regions from raster drawings and selected PDF pages.",
            operations=["find_text", "describe"],
            input_formats=["pdf", "png", "jpg", "jpeg"],
            deterministic=True,
            limitations=[
                "Requires EasyOCR and its local English detection/recognition weights",
                "OCR can misread construction lettering and does not identify semantic objects",
                "Only the selected PDF page is processed",
            ],
        ),
        ToolSpec(
            name="classical_cv_analysis",
            version=TOOL_VERSION,
            description="Extract explainable line and connected-component candidates with OpenCV preprocessing and Hough analysis.",
            operations=["describe"],
            input_formats=["pdf", "png", "jpg", "jpeg"],
            deterministic=True,
            limitations=[
                "Produces geometric candidates only; it does not label doors, rooms, fixtures, or other objects",
                "Results depend on scan quality, thresholding, and drawing scale",
                "Requires OpenCV and NumPy",
            ],
        ),
    ]


def query_ifc_count(
    document_id: str, relative_path: str, path: Path, spec: QuestionSpec
) -> ToolResult:
    if len(spec.entity_concepts) != 1:
        return ToolResult(
            status="abstain",
            warnings=["An IFC count requires one unambiguous entity concept."],
        )
    concept = spec.entity_concepts[0]
    target_types = IFC_ENTITY_TYPES.get(concept)
    if not target_types:
        return ToolResult(status="abstain", warnings=[f"No registered IFC mapping for {concept}."])
    try:
        import ifcopenshell
        from ifcopenshell.util.element import get_container
    except ImportError:
        return ToolResult(status="error", error="IfcOpenShell is not installed.")
    try:
        model = ifcopenshell.open(str(path))
        elements = []
        for type_name in target_types:
            elements.extend(model.by_type(type_name))
    except (RuntimeError, OSError, ValueError) as exc:
        return ToolResult(status="error", error=f"IFC model could not be queried: {exc}")

    query_warnings: list[str] = []
    if concept == "storey":
        excluded = []
        floor_elements = []
        non_floor_terms = ("foundation", "vundament", "roof", "katus", "attic", "podium")
        for element in elements:
            name = str(getattr(element, "Name", "") or "").casefold()
            if any(term in name for term in non_floor_terms):
                excluded.append(str(getattr(element, "Name", "") or element.is_a()))
            else:
                floor_elements.append(element)
        elements = floor_elements
        if excluded:
            query_warnings.append(
                "Excluded non-occupiable IFC storeys from the floor count: "
                + ", ".join(excluded)
                + "."
            )

    matched = []
    unscoped = 0
    requested_scope = spec.scope.casefold() if spec.scope else None
    for element in elements:
        if requested_scope:
            container = get_container(element)
            container_name = str(getattr(container, "Name", "") or "") if container else ""
            if not container_name:
                unscoped += 1
                continue
            if requested_scope not in container_name.casefold():
                continue
        matched.append(element)

    evidence: list[EvidenceRef] = []
    overlays: list[EvidenceOverlay] = []
    for element in matched:
        global_id = getattr(element, "GlobalId", None)
        express_id = element.id()
        entity_key = str(global_id or f"#{express_id}")
        label = str(getattr(element, "Name", "") or element.is_a())
        evidence.append(EvidenceRef(
            document_id=document_id,
            path=relative_path,
            entity_id=entity_key,
            entity_type=element.is_a(),
            extracted_content=label,
            coordinate_system="ifc_model_coordinates",
            extraction_method="IfcOpenShell typed entity query and spatial containment",
            source_tool_version=TOOL_VERSION,
        ))
        overlays.append(EvidenceOverlay(
            overlay_id=f"ifc-{express_id}",
            document_id=document_id,
            page_or_view_id=None,
            overlay_type="ifc_selection",
            geometry=None,
            coordinate_system="ifc_model_coordinates",
            label=label,
            entity_id=entity_key,
            class_name=element.is_a(),
            source_tool="ifc_entity_count",
            is_model_output=False,
            evidence_ids=[entity_key],
        ))
    warnings = list(query_warnings)
    storey_counts: Counter[str] = Counter()
    if not requested_scope:
        for element in matched:
            container = get_container(element)
            storey_name = str(getattr(container, "Name", "") or "Unassigned") if container else "Unassigned"
            storey_counts[storey_name] += 1
        if len(storey_counts) > 1:
            breakdown = ", ".join(f"{name}: {count}" for name, count in sorted(storey_counts.items()))
            warnings.append(
                f"This unscoped count spans {len(storey_counts)} storeys; the companion drawing may show only one level."
            )
        else:
            breakdown = ""
    else:
        breakdown = ""
    if requested_scope and unscoped:
        warnings.append(f"{unscoped} matching IFC elements had no storey containment and were excluded.")
    assumptions = [
        f"Counted IFC entity types {', '.join(target_types)}.",
        f"Spatial scope: {spec.scope}." if spec.scope else "No floor/storey scope was applied.",
    ]
    calculation = []
    if breakdown:
        calculation.append(f"Storey breakdown: {breakdown}.")
    return ToolResult(
        status="supported",
        value=len(matched),
        unit="count",
        calculation=calculation,
        evidence=evidence,
        overlays=overlays,
        warnings=warnings,
        assumptions=assumptions,
    )


def query_dxf_named_blocks(
    document_id: str, relative_path: str, path: Path, spec: QuestionSpec
) -> ToolResult:
    if len(spec.entity_concepts) != 1:
        return ToolResult(status="abstain", warnings=["A DXF count requires one entity concept."])
    concept = spec.entity_concepts[0]
    aliases = ENTITY_TERMS.get(concept, ())
    if spec.scope:
        return ToolResult(
            status="abstain",
            warnings=["Scoped DXF counts are not implemented; no unscoped entities were counted."],
        )
    try:
        import ezdxf
    except ImportError:
        return ToolResult(status="error", error="ezdxf is not installed.")
    try:
        drawing = ezdxf.readfile(path)
        modelspace = drawing.modelspace()
    except (OSError, ValueError, ezdxf.DXFStructureError) as exc:
        return ToolResult(status="error", error=f"DXF could not be queried: {exc}")

    matches = []
    for entity in modelspace.query("INSERT"):
        block_name = str(entity.dxf.name)
        normalized = block_name.casefold().replace("_", " ").replace("-", " ")
        if any(re.search(rf"\b{re.escape(alias)}\b", normalized) for alias in aliases):
            matches.append(entity)
    if not matches:
        if concept == "door":
            return query_dxf_layer_count(
                document_id, relative_path, path, spec, DXF_DOOR_LAYER, "LWPOLYLINE"
            )
        return ToolResult(
            status="abstain",
            warnings=[
                f"No DXF block names explicitly identify {concept}; anonymous or unlabelled geometry was not counted."
            ],
        )

    evidence = []
    overlays = []
    warnings = []
    try:
        preview = render_dxf_preview(path)
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        preview = None
        warnings.append(
            f"DXF entities were counted in native coordinates, but a drawing overlay could not be generated: {exc}"
        )
    for entity in matches:
        point = entity.dxf.insert
        model_point = [float(point.x), float(point.y)]
        evidence_id = str(entity.dxf.handle)
        geometry: dict[str, Any] = {"point": model_point}
        if preview:
            svg_point = preview.transform_point(point.x, point.y)
            geometry["rendered_point"] = [svg_point[0], svg_point[1]]
            overlays.append(EvidenceOverlay(
                overlay_id=f"dxf-{evidence_id}",
                document_id=document_id,
                page_or_view_id="1",
                overlay_type="point",
                geometry={"point": [svg_point[0], svg_point[1]]},
                coordinate_system="dxf_rendered_svg_viewbox",
                label=f"{entity.dxf.name} at ({point.x:g}, {point.y:g})",
                entity_id=evidence_id,
                class_name=str(entity.dxf.name),
                source_tool="dxf_named_block_count",
                is_model_output=False,
                evidence_ids=[evidence_id],
            ))
        evidence.append(EvidenceRef(
            document_id=document_id,
            path=relative_path,
            page=1,
            entity_id=evidence_id,
            entity_type=f"INSERT:{entity.dxf.name}",
            extracted_content=f"Block {entity.dxf.name} at ({point.x:g}, {point.y:g})",
            geometry=geometry,
            coordinate_system="dxf_modelspace",
            extraction_method="ezdxf named block reference query",
            source_tool_version=TOOL_VERSION,
        ))
    return ToolResult(
        status="supported",
        value=len(matches),
        unit="count",
        evidence=evidence,
        overlays=overlays,
        warnings=warnings,
        assumptions=[f"Counted modelspace INSERT entities with block names matching {concept}."],
    )


def _polyline_vertices(entity) -> list[list[float]]:
    return [[float(point[0]), float(point[1])] for point in entity.get_points("xy")]


def _closed_polyline_area(vertices: list[list[float]]) -> float:
    if len(vertices) < 3:
        raise ValueError("A closed area requires at least three vertices.")
    return abs(sum(
        vertices[index][0] * vertices[(index + 1) % len(vertices)][1]
        - vertices[(index + 1) % len(vertices)][0] * vertices[index][1]
        for index in range(len(vertices))
    )) / 2


def _dxf_area_unit_scale(document) -> float | None:
    insertion_units = document.header.get("$INSUNITS", 0)
    return {
        1: 0.0254,
        2: 0.3048,
        4: 0.001,
        5: 0.01,
        6: 1.0,
        7: 1000.0,
        10: 0.9144,
    }.get(insertion_units)


def query_dxf_layer_count(
    document_id: str,
    relative_path: str,
    path: Path,
    spec: QuestionSpec,
    layer_name: str,
    entity_type: str,
) -> ToolResult:
    try:
        import ezdxf
        document = ezdxf.readfile(path)
    except ImportError:
        return ToolResult(status="error", error="ezdxf is not installed.")
    except (OSError, ValueError, ezdxf.DXFStructureError) as exc:
        return ToolResult(status="error", error=f"DXF could not be queried: {exc}")

    entities = [
        entity for entity in document.modelspace()
        if entity.dxftype() == entity_type and entity.dxf.layer.casefold() == layer_name.casefold()
    ]
    if not entities:
        return ToolResult(
            status="abstain",
            warnings=[f"No {entity_type} records were found on the explicit {layer_name} layer."],
        )
    try:
        preview = render_dxf_preview(path)
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        return ToolResult(status="error", error=f"DXF evidence projection failed: {exc}")

    evidence = []
    overlays = []
    for entity in entities:
        native_points = _polyline_vertices(entity)
        if not native_points:
            continue
        rendered_points = [preview.transform_point(x, y) for x, y in native_points]
        closed = bool(entity.closed)
        handle = str(entity.dxf.handle)
        evidence.append(EvidenceRef(
            document_id=document_id,
            path=relative_path,
            page=1,
            entity_id=handle,
            entity_type=f"{entity_type}:{layer_name}",
            extracted_content=f"{layer_name} {entity_type} on layer {layer_name}",
            geometry={
                "points": native_points,
                "rendered_points": [list(point) for point in rendered_points],
                "closed": closed,
            },
            coordinate_system="dxf_modelspace",
            extraction_method="ezdxf entity query on an explicitly named semantic layer",
            source_tool_version=TOOL_VERSION,
        ))
        overlays.append(EvidenceOverlay(
            overlay_id=f"dxf-{handle}",
            document_id=document_id,
            page_or_view_id="1",
            overlay_type="polygon" if closed else "polyline",
            geometry={"points": [list(point) for point in rendered_points], "closed": closed},
            coordinate_system="dxf_rendered_svg_viewbox",
            label=f"{layer_name} {entity_type}",
            entity_id=handle,
            class_name=layer_name,
            source_tool="dxf_named_layer_geometry",
            is_model_output=False,
            evidence_ids=[handle],
        ))
    if not evidence:
        return ToolResult(status="abstain", warnings=["No usable layer geometries were returned."])
    return ToolResult(
        status="supported",
        value=len(evidence),
        unit="count",
        evidence=evidence,
        overlays=overlays,
        assumptions=[
            f"Counted {entity_type} records on the explicitly named {layer_name} layer.",
            "Counts are CAD records; a multi-part object represented by several records may count more than once.",
        ],
    )


def calculate_dxf_room_area(
    document_id: str, relative_path: str, path: Path, spec: QuestionSpec
) -> ToolResult:
    if spec.scope:
        return ToolResult(
            status="abstain",
            warnings=["Scoped room areas are not implemented; no building-wide area was substituted."],
        )
    try:
        import ezdxf
        document = ezdxf.readfile(path)
    except ImportError:
        return ToolResult(status="error", error="ezdxf is not installed.")
    except (OSError, ValueError, ezdxf.DXFStructureError) as exc:
        return ToolResult(status="error", error=f"DXF geometry could not be queried: {exc}")

    unit_scale = _dxf_area_unit_scale(document)
    if unit_scale is None:
        return ToolResult(
            status="abstain",
            warnings=["DXF insertion units are unspecified or unsupported; area cannot be converted reliably."],
        )
    outlines = [
        entity for entity in document.modelspace()
        if entity.dxftype() == "LWPOLYLINE"
        and entity.dxf.layer.casefold() == DXF_ROOM_AREA_LAYER.casefold()
    ]
    closed_outlines = [entity for entity in outlines if entity.closed]
    if not closed_outlines:
        return ToolResult(
            status="abstain",
            warnings=[f"No closed room outlines were found on the {DXF_ROOM_AREA_LAYER} layer."],
        )
    try:
        preview = render_dxf_preview(path)
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        return ToolResult(status="error", error=f"DXF room area projection failed: {exc}")

    evidence = []
    overlays = []
    areas_m2 = []
    for entity in closed_outlines:
        vertices = _polyline_vertices(entity)
        bulges = [point[4] for point in entity.get_points("xyseb")]
        if any(abs(float(bulge)) > 1e-10 for bulge in bulges):
            continue
        area = _closed_polyline_area(vertices) * unit_scale ** 2
        if area <= 0:
            continue
        handle = str(entity.dxf.handle)
        rendered_points = [preview.transform_point(x, y) for x, y in vertices]
        areas_m2.append(area)
        evidence.append(EvidenceRef(
            document_id=document_id,
            path=relative_path,
            page=1,
            entity_id=handle,
            entity_type="LWPOLYLINE:ROOM_OUTLINE",
            extracted_content=f"Room outline area {area:.6g} m^2",
            geometry={
                "points": vertices,
                "rendered_points": [list(point) for point in rendered_points],
                "closed": True,
                "area_m2": area,
            },
            coordinate_system="dxf_modelspace",
            extraction_method="Shoelace area over a closed ROOM_OUTLINE polyline; DXF units converted to metres",
            source_tool_version=TOOL_VERSION,
        ))
        overlays.append(EvidenceOverlay(
            overlay_id=f"dxf-room-{handle}",
            document_id=document_id,
            page_or_view_id="1",
            overlay_type="polygon",
            geometry={"points": [list(point) for point in rendered_points], "closed": True},
            coordinate_system="dxf_rendered_svg_viewbox",
            label=f"Room area {area:.2f} m^2",
            entity_id=handle,
            class_name="ROOM_OUTLINE",
            source_tool="dxf_room_area",
            is_model_output=False,
            evidence_ids=[handle],
        ))
    if not areas_m2:
        return ToolResult(
            status="abstain",
            warnings=["Closed room outlines contain unsupported curves or no valid polygon area."],
        )

    total_m2 = sum(areas_m2)
    requested_unit = (spec.output_unit or "m2").casefold().replace("^", "").replace("²", "2")
    unit_factors = {"m2": 1.0, "ft2": 10.7639104167}
    if requested_unit not in unit_factors:
        return ToolResult(
            status="abstain",
            warnings=[f"Area output unit {spec.output_unit!r} is not supported."],
        )
    total = total_m2 * unit_factors[requested_unit]
    warnings = []
    skipped = len(outlines) - len(evidence)
    if skipped:
        warnings.append(
            f"{skipped} ROOM_OUTLINE records were open or used unsupported curve segments and were excluded."
        )
    calculation = [
        f"Calculated {len(evidence)} closed room polygon areas with the shoelace formula.",
        f"Converted DXF insertion units using $INSUNITS={document.header.get('$INSUNITS')}.",
        f"Summed {total_m2:.6g} m^2.",
    ]
    if requested_unit == "ft2":
        calculation.append(f"Converted {total_m2:.6g} m^2 to {total:.6g} ft^2.")
    return ToolResult(
        status="partial" if warnings else "supported",
        value=total,
        unit="ft2" if requested_unit == "ft2" else "m2",
        calculation=calculation,
        evidence=evidence,
        overlays=overlays,
        warnings=warnings,
        assumptions=[
            "Summed closed outlines on the ROOM_OUTLINE layer; open or curved records are excluded.",
            "Area is plan outline area and does not account for wall thickness, openings, or room-name association.",
        ],
    )


def _query_terms(question: str) -> set[str]:
    tokens = re.findall(r"[a-z0-9]+", question.casefold())
    terms = {token for token in tokens if token not in STOP_WORDS and len(token) > 1}
    for token in tuple(terms):
        if token.endswith("ies") and len(token) > 4:
            terms.add(f"{token[:-3]}y")
        elif token.endswith("s") and not token.endswith("ss") and len(token) > 3:
            terms.add(token[:-1])
    return terms


def _search_ocr_lines(
    document_id: str,
    relative_path: str,
    lines: list[OCRLine],
    page_number: int,
    coordinate_system: str,
    scale_x: float,
    scale_y: float,
    question: str,
) -> ToolResult:
    if not lines:
        return ToolResult(
            status="abstain",
            warnings=["OCR did not detect readable text in the source region."],
        )
    terms = _query_terms(question)
    ranked: list[tuple[int, OCRLine]] = []
    for line in lines:
        tokens = set(re.findall(r"[a-z0-9]+", line.text.casefold()))
        overlap = len(terms & tokens)
        if not terms or overlap:
            ranked.append((overlap, line))
    ranked.sort(key=lambda item: (-item[0], item[1].bbox[1], item[1].bbox[0]))
    if not ranked:
        return ToolResult(
            status="abstain",
            warnings=["OCR detected text, but no recognized text matched the requested terms."],
        )

    evidence: list[EvidenceRef] = []
    overlays: list[EvidenceOverlay] = []
    for index, (_, line) in enumerate(ranked[:30]):
        bbox = [
            line.bbox[0] * scale_x,
            line.bbox[1] * scale_y,
            line.bbox[2] * scale_x,
            line.bbox[3] * scale_y,
        ]
        evidence_id = f"{document_id}-ocr-p{page_number}-{index}"
        evidence.append(EvidenceRef(
            document_id=document_id,
            path=relative_path,
            page=page_number,
            entity_type="ocr_text",
            extracted_content=line.text,
            bbox=bbox,
            geometry={"confidence": line.confidence},
            coordinate_system=coordinate_system,
            extraction_method="EasyOCR local configured-language text detection",
            source_tool_version=TOOL_VERSION,
        ))
        overlays.append(EvidenceOverlay(
            overlay_id=evidence_id,
            document_id=document_id,
            page_or_view_id=str(page_number),
            overlay_type="text_region",
            geometry={"bbox": bbox},
            coordinate_system=coordinate_system,
            label=f"{line.text[:100]} ({line.confidence:.0%})",
            class_name="ocr_text",
            source_tool="local_ocr_text_search",
            is_model_output=False,
            evidence_ids=[evidence_id],
        ))
    return ToolResult(
        status="partial",
        value="\n".join(item.extracted_content or "" for item in evidence),
        evidence=evidence,
        overlays=overlays,
        warnings=["OCR text may contain recognition errors; inspect the highlighted source regions."],
    )


def search_raster_ocr(
    document_id: str,
    relative_path: str,
    path: Path,
    spec: QuestionSpec,
) -> ToolResult:
    try:
        from PIL import Image, ImageOps
        with Image.open(path) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
            image.load()
        lines = (
            extract_paddle_ocr_lines(image)
            if paddle_ocr_is_available()
            else extract_ocr_lines(image)
        )
    except OCRUnavailable as exc:
        return ToolResult(status="abstain", warnings=[str(exc)])
    except (OCRError, OSError, ValueError) as exc:
        return ToolResult(status="error", error=f"Raster OCR failed: {exc}")
    return _search_ocr_lines(
        document_id,
        relative_path,
        lines,
        1,
        "image_pixels",
        1.0,
        1.0,
        spec.original_question,
    )


def analyze_classical_cv(
    document_id: str,
    relative_path: str,
    path: Path,
    document_format: str,
    page_number: int = 1,
) -> ToolResult:
    """Return explainable line/component evidence without semantic counting."""
    try:
        from .classical_cv import ClassicalCVUnavailable, analyze_plan_image
        from .vision_models import load_source_image

        source = load_source_image(path, document_format, page_number)
        analysis = analyze_plan_image(source.image)
    except ClassicalCVUnavailable as exc:
        return ToolResult(status="abstain", warnings=[str(exc)])
    except (OSError, RuntimeError, ValueError) as exc:
        return ToolResult(status="error", error=f"Classical drawing analysis failed: {exc}")

    evidence: list[EvidenceRef] = []
    overlays: list[EvidenceOverlay] = []
    for index, line in enumerate(analysis["lines"]):
        evidence_id = f"{document_id}-classical-line-p{page_number}-{index}"
        evidence.append(EvidenceRef(
            document_id=document_id,
            path=relative_path,
            page=page_number if document_format == "pdf" else None,
            entity_type="detected_line",
            extracted_content=(
                f"Line {line['length_pixels']:.1f}px at {line['angle_degrees']:.1f} degrees"
            ),
            geometry={"points": line["points"]},
            coordinate_system=source.coordinate_system,
            extraction_method="Canny edges with probabilistic Hough transform",
            source_tool_version=TOOL_VERSION,
        ))
        overlays.append(EvidenceOverlay(
            overlay_id=evidence_id,
            document_id=document_id,
            page_or_view_id=str(page_number) if document_format == "pdf" else None,
            overlay_type="polyline",
            geometry={"points": line["points"]},
            coordinate_system=source.coordinate_system,
            label=f"line {line['angle_degrees']:.1f} deg",
            class_name="detected_line",
            source_tool="classical_cv_analysis",
            model_name="OpenCV HoughLinesP",
            is_model_output=False,
            evidence_ids=[evidence_id],
        ))
    for index, component in enumerate(analysis["components"]):
        evidence_id = f"{document_id}-classical-component-p{page_number}-{index}"
        evidence.append(EvidenceRef(
            document_id=document_id,
            path=relative_path,
            page=page_number if document_format == "pdf" else None,
            entity_type="connected_component",
            extracted_content=f"Connected component {component['area_pixels']} pixels",
            bbox=component["bbox"],
            geometry={"centroid": component["centroid"]},
            coordinate_system=source.coordinate_system,
            extraction_method="Adaptive threshold, morphology, and connected components",
            source_tool_version=TOOL_VERSION,
        ))
        overlays.append(EvidenceOverlay(
            overlay_id=evidence_id,
            document_id=document_id,
            page_or_view_id=str(page_number) if document_format == "pdf" else None,
            overlay_type="bounding_box",
            geometry={"bbox": component["bbox"], "area_pixels": component["area_pixels"]},
            coordinate_system=source.coordinate_system,
            label=f"component {component['area_pixels']} px",
            class_name="connected_component",
            source_tool="classical_cv_analysis",
            model_name="OpenCV connected components",
            is_model_output=False,
            evidence_ids=[evidence_id],
        ))
    if not evidence:
        return ToolResult(
            status="abstain",
            warnings=["No sufficiently large line or connected-component candidates were found."],
        )
    return ToolResult(
        status="partial",
        value={
            "line_count": len(analysis["lines"]),
            "component_count": len(analysis["components"]),
            "edge_density": analysis["edge_density"],
        },
        unit=None,
        evidence=evidence,
        overlays=overlays,
        warnings=[
            "Classical CV candidates are geometric evidence only; they are not architectural object labels or verified quantities.",
            f"Detected {len(analysis['lines'])} long-line candidates and {len(analysis['components'])} connected components.",
        ],
        assumptions=["Coordinates are source-image pixels or rendered PDF coordinates."],
    )


def search_pdf_ocr(
    document_id: str,
    relative_path: str,
    path: Path,
    spec: QuestionSpec,
    page_number: int,
) -> ToolResult:
    try:
        from PIL import Image
        png_bytes, page_width, page_height, _ = render_pdf_page(path, page_number)
        with Image.open(io.BytesIO(png_bytes)) as rendered_page:
            image = rendered_page.convert("RGB")
            image.load()
        lines = (
            extract_paddle_ocr_lines(image)
            if paddle_ocr_is_available()
            else extract_ocr_lines(image)
        )
    except OCRUnavailable as exc:
        return ToolResult(status="abstain", warnings=[str(exc)])
    except ImportError as exc:
        return ToolResult(status="error", error=f"PDF OCR dependencies are unavailable: {exc}")
    except (OCRError, IndexError, OSError, RuntimeError, ValueError) as exc:
        return ToolResult(status="error", error=f"PDF page OCR failed: {exc}")
    return _search_ocr_lines(
        document_id,
        relative_path,
        lines,
        page_number,
        "pdf_points",
        page_width / image.width,
        page_height / image.height,
        spec.original_question,
    )


def search_pdf_text(
    document_id: str,
    relative_path: str,
    path: Path,
    spec: QuestionSpec,
    page_number: int | None = None,
) -> ToolResult:
    terms = _query_terms(spec.original_question)
    if not terms:
        return ToolResult(
            status="abstain",
            warnings=["No searchable terms were found in the question. Scanned pages require OCR."],
        )
    try:
        pages = read_pdf_text(path)
    except (RuntimeError, OSError, ValueError) as exc:
        return ToolResult(status="error", error=f"PDF text could not be extracted: {exc}")
    if page_number is not None and (page_number < 1 or page_number > len(pages)):
        return ToolResult(
            status="error",
            error=f"Requested page {page_number} is outside the extracted PDF page range.",
        )

    candidates: list[tuple[float, dict[str, Any]]] = []
    for page in pages:
        if page_number is not None and page["page"] != page_number:
            continue
        for span in page["spans"]:
            text = span["text"]
            tokens = set(re.findall(r"[a-z0-9]+", text.casefold()))
            overlap = terms & tokens
            if not overlap:
                continue
            score = len(overlap) / max(1, len(terms))
            if any(term in text.casefold() for term in terms):
                score += 0.1
            candidates.append((score, {**span, "page": page["page"], "page_width": page["width"], "page_height": page["height"]}))
    candidates.sort(key=lambda item: (-item[0], item[1]["page"], item[1]["bbox"][1]))
    selected = []
    seen = set()
    for score, span in candidates:
        key = (span["page"], span["text"], tuple(round(value, 1) for value in span["bbox"]))
        if key in seen:
            continue
        seen.add(key)
        selected.append((score, span))
        if len(selected) == 6:
            break
    if not selected or selected[0][0] < 0.15:
        return ToolResult(
            status="abstain",
            warnings=["No sufficiently relevant selectable PDF text was found. Scanned pages require OCR."],
        )

    evidence = []
    overlays = []
    for index, (_, span) in enumerate(selected):
        evidence_id = f"{document_id}-p{span['page']}-t{index}"
        evidence.append(EvidenceRef(
            document_id=document_id,
            path=relative_path,
            page=span["page"],
            extracted_content=span["text"],
            bbox=span["bbox"],
            coordinate_system="pdf_points",
            extraction_method="PyMuPDF selectable-text span",
            source_tool_version=TOOL_VERSION,
        ))
        overlays.append(EvidenceOverlay(
            overlay_id=evidence_id,
            document_id=document_id,
            page_or_view_id=str(span["page"]),
            overlay_type="text_region",
            geometry={"bbox": span["bbox"], "page_width": span["page_width"], "page_height": span["page_height"]},
            coordinate_system="pdf_points",
            label=span["text"][:120],
            source_tool="pdf_text_search",
            is_model_output=False,
            evidence_ids=[evidence_id],
        ))
    return ToolResult(
        status="partial",
        value=evidence[0].extracted_content,
        evidence=evidence,
        overlays=overlays,
        warnings=[
            "Search results are verbatim text evidence, not a validated answer or quantity calculation."
        ],
    )


def search_svg_text(
    document_id: str, relative_path: str, path: Path, spec: QuestionSpec
) -> ToolResult:
    terms = _query_terms(spec.original_question)
    if not terms:
        return ToolResult(status="abstain", warnings=["No searchable terms were found in the question."])
    try:
        root = ET.parse(path).getroot()
        view_box = read_svg_viewbox(path)
    except (ET.ParseError, OSError, ValueError) as exc:
        return ToolResult(status="error", error=f"SVG text could not be extracted: {exc}")

    parent_by_child = {
        child: parent
        for parent in root.iter()
        for child in parent
    }

    candidates: list[tuple[float, ET.Element, str]] = []
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1].casefold() != "text":
            continue
        text = "".join(element.itertext()).strip()
        if not text:
            continue
        tokens = set(re.findall(r"[a-z0-9]+", text.casefold()))
        overlap = terms & tokens
        if not overlap:
            continue
        candidates.append((len(overlap) / max(1, len(terms)), element, text))

    candidates.sort(key=lambda item: (-item[0], item[2].casefold()))
    evidence: list[EvidenceRef] = []
    overlays: list[EvidenceOverlay] = []
    for index, (_, element, text) in enumerate(candidates[:6]):
        element_id = element.attrib.get("id")
        has_transform = False
        current: ET.Element | None = element
        while current is not None:
            if "transform" in current.attrib:
                has_transform = True
                break
            current = parent_by_child.get(current)
        point = None
        if view_box and not has_transform:
            try:
                x_text = element.attrib.get("x", "")
                y_text = element.attrib.get("y", "")
                if "%" not in x_text + y_text:
                    x = float(re.split(r"[\s,]+", x_text.strip())[0])
                    y = float(re.split(r"[\s,]+", y_text.strip())[0])
                    point = [x, y]
            except (ValueError, IndexError):
                point = None
        evidence_id = f"{document_id}-svg-text-{index}"
        evidence.append(EvidenceRef(
            document_id=document_id,
            path=relative_path,
            page=1,
            entity_id=element_id,
            entity_type="svg_text",
            extracted_content=text,
            geometry={"point": point} if point else None,
            coordinate_system="svg_viewbox" if view_box else None,
            extraction_method="ElementTree native SVG text element",
            source_tool_version=TOOL_VERSION,
        ))
        if point:
            overlays.append(EvidenceOverlay(
                overlay_id=evidence_id,
                document_id=document_id,
                page_or_view_id="1",
                overlay_type="point",
                geometry={"point": point},
                coordinate_system="svg_viewbox",
                label=text[:120],
                entity_id=element_id,
                source_tool="svg_text_search",
                is_model_output=False,
                evidence_ids=[evidence_id],
            ))
    if not evidence:
        return ToolResult(
            status="abstain",
            warnings=["No matching native SVG text was found; unlabeled vector geometry was not interpreted."],
        )
    return ToolResult(
        status="partial",
        value=evidence[0].extracted_content,
        evidence=evidence,
        overlays=overlays,
        warnings=[
            "Retrieved native SVG text; vector shapes were not interpreted as semantic objects."
        ],
    )
