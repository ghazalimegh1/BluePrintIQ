# Architecture

## Runtime flow

1. `backend/app/ingestion.py` detects formats, builds the local catalog, and reports format-specific capabilities. It never loads question answers.
2. `backend/app/llm_interpreter.py` uses the official Groq SDK with `GROQ_API_KEY` and `GROQ_MODEL` only after per-tab user consent. Groq receives the question and tool descriptions to create a validated plan; it never receives drawings, OCR results, retrieved evidence, or answers.
3. `backend/app/routing.py` checks the selected document format, available tools, and plan, then runs the matching local tool.
4. `backend/app/tools.py` executes IFC typed-entity counts, explicit DXF block/layer queries, DXF room-outline area calculations, PDF/SVG text retrieval, and optional EasyOCR/PaddleOCR extraction.
5. `backend/app/vision_models.py` provides optional local Grounding DINO Tiny detection, SAM 2.1 masks, CubiCasa floor-plan segmentation, and PaddleOCR. Local model weights are opt-in and must be cached before use.
6. `backend/app/gemini_vision.py` provides optional hosted semantic review using the allowlisted free-tier Gemini model. After separate per-request consent, it sends a reduced/annotated drawing image, the question, and up to 64 local Grounding DINO candidates. Gemini may flag label ambiguity; it cannot create counts, measurements, boxes, or answers.
7. `EvidenceRef` records source path, page/entity, coordinate system, extracted content, geometry, and extraction method. Model overlays preserve original drawing coordinates. IFC elements remain model-coordinate references because no projection to the companion page is established.
8. The local evidence validators determine answer status and numeric values. There is no LLM answer-generation call; Groq and Gemini outputs never replace tool values or evidence.
9. `backend/app/main.py` exposes the app and JSON API. Runtime endpoints are not connected to `questions.jsonl`, split gold, or predictions.
10. `frontend/` renders source, companion, and vector views separately from evidence overlays, and shows capability, route, validation, evidence, provider configuration, and limitation details.

## Provider and consent contracts

- Groq is planner-only. Provider credentials are read from the backend environment or ignored `.env`, never accepted by a request model or returned to the browser.
- Gemini uses `GEMINI_API_KEY` and `GEMINI_MODEL`; only `gemini-3.5-flash-lite` is allowed by this free-tier integration. Unknown/paid model names fail closed. There is no paid-model or other-provider fallback.
- The Gemini review tool is available only when Gemini is configured, Grounding DINO is locally available, and the request has explicit image-sharing consent.
- Free-tier Gemini inputs may be human-reviewed and used to improve Google products. Do not send sensitive, confidential, or personal information. Google’s terms restrict free-tier API clients available to users in the EEA, UK, or Switzerland; use of this adapter is for eligible hackathon/demo scenarios only.
- Google’s free-tier quotas vary by project and can change. Check the active project limits in AI Studio; the application reports quota/rate-limit failures without switching models.

## Data/evaluation flow

`scripts/create_splits.py` resolves whole drawing/building/project groups, hashes referenced files, assigns groups deterministically, audits leakage, and writes answer-free validation/test inputs plus separate gold. `scripts/evaluate.py` is an offline evaluator; it is not imported by the API or router.

## Supported evidence and limits

- IFC: entity class, GlobalId, name, optional `IfcBuildingStorey` containment. No model geometry or screen-space highlight.
- PDF: selectable text spans and PDF-point boxes. Local vision/OCR operates on the chosen page only; selectable text search is not a validated schedule parser.
- OCR: optional English EasyOCR or PaddleOCR uses local weights and returns source-coordinate text regions. OCR is not an object detector or schedule parser.
- DXF: vector SVG rendering, explicit named block counts, door geometry on the explicitly named `DOOR` layer, and closed `ROOM_OUTLINE` polygon areas. Open room outlines are excluded and reported. Other primitives are not silently equated to semantic objects.
- PNG/JPEG: local tiled object detection and segmentation when dependencies and weights are installed; optional local OCR; Gemini semantic review only when local detections exist and per-request consent is given. Model counts remain partial and are not calibrated ground truth.
- SVG: parsed vector metadata, native text retrieval, and text-anchor evidence when no ancestor transforms make the anchor ambiguous.
- DWG: format recognition only; an ODA converter is not installed/configured.

## Safety and failure behavior

Document IDs resolve through the local catalog; upload extensions and byte size are restricted; server paths are rooted under the dataset or upload directory. Original source documents are not modified. Provider calls require explicit selection/consent, use backend-only environment credentials, and never return keys. Model-selected tools are checked against the registered, format-compatible allowlist. Missing libraries, unreadable files, absent evidence, provider errors, and unsupported operations are surfaced as errors or abstentions rather than success-shaped defaults.
