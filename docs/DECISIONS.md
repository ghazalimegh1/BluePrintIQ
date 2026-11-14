# Architecture decisions

## 2026-11-13 — Local-first MVP in the existing workspace

- The dataset lives under `junction-dataset-preview/`; application code and generated artifacts live at the project root.
- Preserve source files. The first demo processes files locally and does not transmit drawings to external providers.
- Do not add a foundation-model dependency until a provider is configured; the initial planner must use validated, capability-aware tools and abstain when evidence is insufficient.
- Keep reference answers isolated from runtime endpoints, indexes, prompts, and frontend. Evaluation joins predictions with separate gold files only after inference.
- Use a group-aware split resolver rather than row-level random splitting. Known family rules include CubiCasa image path, Swiss building identifier, IFC model/render pair, IFC-Bench model path, and OpeningDesign project folder. Exact hashes can merge duplicate groups; uncertain visual near-duplicates are reported rather than auto-merged.
- Use honest tool availability: absent OCR/vision/CAD/BIM dependencies must be reported as unavailable, not represented by mock results.

## 2026-11-13 — Keep evidence and answer claims capability-bounded

- IFC entity counts are supported only by typed IFC records and returned entity references. Do not imply page highlighting where a model-to-page transform is unavailable.
- Selectable PDF text search can return verbatim spans and page-coordinate overlays, but it does not validate schedule values or quantities. Keep these responses marked partial until a tested parser exists.
- DXF entity counting is limited to explicit named block inserts. Do not infer semantic counts from primitive geometry or layer names.
- Browser verification confirmed the current PDF text overlays highlight their corresponding source regions. Raster OCR was unavailable at that time; it is now an optional local text-retrieval tool, while object detection, segmentation, and IFC geometry projection remain unavailable.
- Resolve uploaded files directly by their deterministic upload path and construct their records independently of the dataset catalog. Uploading must not force a full scan and parser pass over all dataset files.

## 2026-11-13 — Groq SDK, environment configuration and explicit consent

- Use the official Groq Python SDK. Read `GROQ_API_KEY` and `GROQ_MODEL` from host environment or an ignored local `.env`; never accept credentials in request schemas or return/log their value.
- A UI model selection plus per-tab consent is required before questions and tool descriptions are sent to Groq. Host secrets alone do not enable browser requests.
- Use a strict function call to create a structured plan. Validate model-selected tool names against the available format-specific allowlist before executing local code.
- Groq is planner-only. Do not send images, OCR, tool results, or evidence to Groq, and do not call it to generate answer wording. Local tools and validators own answer content.
- The Groq SDK handles bounded retries and timeout; translate rate-limit, timeout, transport, status, and invalid-response errors into credential-free diagnostics.

## 2026-11-14 — Gemini free-tier as an optional semantic reviewer

- Use the official `google-genai` Python SDK with `GEMINI_API_KEY` and `GEMINI_MODEL`. Allow only `gemini-3.5-flash-lite`, which Google's model page lists as stable with image input and structured outputs and whose standard free tier lists zero input/output token charges. Project-specific quotas vary and must be checked in AI Studio.
- Gemini is an independent vision subsystem, not a router or answer generator. It may review local Grounding DINO labels and flag ambiguity; it cannot create counts, measurements, boxes, or answer text. Never use a VLM estimate as a deterministic quantity.
- Require a separate per-request consent before sending a resized, annotated drawing image, the question, and detector candidates. Free-tier submitted content may be human-reviewed and used to improve Google's products; do not send sensitive, confidential, or personal drawings.
- Reject any unsupported/paid `GEMINI_MODEL`; do not silently fall back to a paid model or other provider. Report quota, timeout, transport, API, and response-schema failures explicitly.
- Google's Gemini API terms say only Paid Services may power API clients made available to users in the EEA, UK, or Switzerland. This free-tier adapter is limited to eligible hackathon/demo use and must not be enabled for an audience in those regions.
- The `.env.example` contains blank secret placeholders only. Any credential previously pasted into chat is compromised and must be revoked/replaced.
- Official references: [model capabilities](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite), [pricing](https://ai.google.dev/gemini-api/docs/pricing#gemini-3.5-flash-lite), [rate limits](https://ai.google.dev/gemini-api/docs/rate-limits), and [API terms](https://ai.google.dev/gemini-api/docs/terms).

## 2026-11-13 — Use native DXF transforms and label-level geometry conservatively

- Render DXF modelspace to SVG and reuse the renderer's model-to-view transform for supported CAD evidence overlays.
- Count only explicit named block references or source records on the explicitly named `DOOR` layer. Label layer-record counts as geometry records; do not generalize to other primitives.
- Calculate only closed, non-bulged `ROOM_OUTLINE` polygons using a declared `$INSUNITS` conversion. Exclude open/unsupported outlines, report them, and mark the aggregate partial.
- DWG remains format-detected but unavailable until a local converter is installed; do not claim that a DWG parser exists.

## 2026-11-13 — Optional local OCR with explicit model-download opt-in

- Use EasyOCR's English detector/recognizer for raster text retrieval and only the selected PDF page when native PDF text does not answer the query.
- Return recognizer text, confidence, and source-coordinate regions. Keep answers partial and do not infer object counts or schedule quantities from OCR boxes.
- Keep EasyOCR/PyTorch in `requirements-ocr.txt` rather than the lightweight base requirements.
- Do not download pretrained OCR weights automatically. Require `STOA_OCR_DOWNLOAD_MODELS=true` for first-use downloads, or accept weights already present in the configured local model directory.

## 2026-11-14 — Activate local CubiCasa and PaddleOCR models

- Download the official CubiCasa5K source and checkpoint into ignored `runtime/` storage with `scripts/download_cubicasa_model.py`; configure only `STOA_CUBICASA_SOURCE_DIR` and `STOA_CUBICASA_CHECKPOINT` in the ignored `.env`. The model/source is non-commercial (CC BY-NC 4.0); preserve the dataset's separate CC BY-NC-SA attribution.
- Install PaddleOCR/PaddlePaddle through `requirements-vision-ocr.txt`; cache English detector/recognizer weights explicitly with `scripts/download_ocr_models.py`. The application reports PaddleOCR unavailable until both weights exist, unless `STOA_OCR_DOWNLOAD_MODELS=true` explicitly permits first-use downloads.
- Run PaddleOCR on CPU with oneDNN disabled because the Windows CPU build raised an unsupported PIR/oneDNN runtime error with its default mode. Keep CPU threads bounded; model outputs are source-coordinate candidates, not verified text.
- Keep Grounding DINO, SAM, CubiCasa, and PaddleOCR independent from Groq. The planner selects only relevant capabilities; no model is loaded for every question, and counts from model predictions remain partial/unverified.
- Local smoke-test result on the bundled sample: CubiCasa produced 73 regions; PaddleOCR produced 13 text regions; the API/UI returned 12 door candidates with 12 evidence overlays. Do not treat these predictions as ground truth; create and evaluate a manually annotated, drawing-identity-split subset.

