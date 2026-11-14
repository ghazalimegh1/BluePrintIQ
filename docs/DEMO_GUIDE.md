# Demo guide

## Start

From `C:\Users\HP\Desktop\JunctionHack`:

```powershell
python -m pip install -r requirements.txt
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`. The app defaults to the local Esplanades IFC example when available. It also exposes the companion plan as a faithful preview; IFC entity evidence is not projected onto that page.

## Scenario 1 — BIM entity count

Select:

`junction-dataset-preview/data/ifc_models/bsc-esplanades_1807-ep-ar-v18.ifc`

Ask:

> How many doors are shown on the floor plan of '1.korrus'?

Expected live behavior:

- The question is parsed as a door count scoped to `1.korrus`.
- The router selects the IFC entity tool, not a vision model.
- IfcOpenShell filters `IfcDoor` entities by their spatial container.
- The result includes the returned entity GlobalIds and names. The UI explicitly states that a model-to-page projection is unavailable.
- The live runtime never reads the matching answer from `questions.jsonl`.

The sample is under `ifc_models`; consult `junction-dataset-preview/data/ifc_models/LICENSE.md` for its credit and terms.

## Scenario 2 — PDF text evidence

Select:

`junction-dataset-preview/data/opening_design/Sports_Complex/Sheets - Current Set/A-801 - Door and Finish Schedules & Wall Types.pdf`

Ask:

> Find the room schedule and show its text evidence.

Expected live behavior:

- The router selects PDF text retrieval.
- The answer is explicitly partial: retrieved text is not presented as a validated schedule calculation.
- Clicking a result card navigates to its page and highlights its actual text bounding box on the rendered source.
- The source and evidence overlays can be toggled independently.

Consult `junction-dataset-preview/data/opening_design/LICENSE.md` for attribution and per-file terms.

## Scenario 3 — DXF geometry and room areas

Select:

`junction-dataset-preview/data/swiss_dwellings/site52_bldg298_floor1183.dxf`

Ask:

> What is the total area of the rooms in square meters?

Expected behavior:

- The backend renders a vector preview from the DXF source and preserves the CAD-to-preview transform.
- The tool sums only closed, non-bulged polylines on the explicitly named `ROOM_OUTLINE` layer and converts from the document's declared `$INSUNITS`.
- The sample also has open room outlines. Those are excluded and listed in warnings, so the answer is explicitly partial rather than a claimed complete building total.
- The UI draws each contributing polygon; selecting an evidence card zooms to that source geometry.

Door counts may use named block references or `LWPOLYLINE` records on the explicit `DOOR` layer. Other DXF geometry is not treated as an object count.

## Optional local OCR

Install the OCR extra with `python -m pip install -r requirements-ocr.txt`. To permit EasyOCR to download its English model weights on first use, set `STOA_OCR_DOWNLOAD_MODELS=true` in the backend process before starting the app. Without this opt-in, put `craft_mlt_25k.pth` and `english_g2.pth` in `%USERPROFILE%\.EasyOCR\model` or set `STOA_OCR_MODEL_DIR` to their local directory. The tool registry and document capability cards report OCR unavailable until the engine and weights are ready.

On a PNG/JPEG, ask:

> Find readable text on this drawing.

For scanned PDFs, select the page in the viewer and ask the same. When native selectable text is absent or not relevant, the app OCRs only the selected page. Click an OCR evidence card to highlight its pixel/PDF-point box. Results are English-only and marked partial because OCR can misread construction lettering. OCR does not supply door/window detections or validated quantity totals.

## Optional Gemini semantic review

Copy `.env.example` to `.env`, set `GROQ_API_KEY`, `GROQ_MODEL`, and `GEMINI_API_KEY`, then restart the backend. Keep both keys in the ignored local `.env` or hosting secrets; never put them in the frontend or source control. `GEMINI_MODEL` is restricted to `gemini-3.5-flash-lite`, the documented stable free-tier image-input/structured-output model. Per-project quotas vary and are managed in Google AI Studio. The server will not fall back to another or paid model.

Gemini is optional and is only offered when the local Grounding DINO detector and its weights are available. In **LLM setup**, separately check the Gemini consent before asking a `describe` question. The drawing image, question, and up to 64 detector candidates are then sent to Google for semantic label review only. Gemini does not count objects, provide measurements, change boxes, or generate the answer. Free-tier prompts/images may be human-reviewed and used to improve Google products; do not send confidential or personal drawings. Google’s terms prohibit free-tier Gemini API clients being made available to users in the EEA, UK, or Switzerland.

Groq receives only the natural-language question and registered tool descriptions for planning/routing. Numeric answers and evidence come from local tools and remain unchanged by either LLM. No separate LLM answer-generation call is made.

## Optional local specialist models

Install `requirements-vision.txt` and download the intended public checkpoints with `python scripts\download_vision_models.py --models grounding-dino-tiny sam2.1-hiera-small`. Run `python scripts\download_cubicasa_model.py` for the official CubiCasa source/checkpoint, then set `STOA_CUBICASA_SOURCE_DIR` and `STOA_CUBICASA_CHECKPOINT` in the backend environment. CubiCasa is CC BY-NC 4.0 and non-commercial only. Install `requirements-vision-ocr.txt` and run `python scripts\download_ocr_models.py` to cache PaddleOCR weights explicitly. PaddleOCR CPU inference disables oneDNN for compatibility with the Windows CPU build. Grounding DINO and SAM 2.1 require substantial CPU/GPU resources; this CPU-only machine has limited RAM, so first inference may be slow. The UI/API report unavailable capabilities when dependencies or weights are missing rather than simulating inference.

The previously exposed Groq credential must be revoked and replaced. Do not put replacement credentials in chat or source code.

## Upload and limitations

The left panel accepts PDF, PNG/JPEG, SVG, DWG, DXF, and IFC files up to 25 MiB. Uploads stay under `runtime/uploads/`. DWG conversion needs a local ODA File Converter, which is not installed. OCR, object detection, and segmentation are optional and require their local dependencies and weights. IFC entity evidence cannot be projected onto a companion drawing yet. PDF table extraction is not validated.

## Checks

```powershell
python -m unittest discover -s tests -v
python scripts\create_splits.py --seed 2026
```

Never pass `artifacts/evaluation/gold/*.jsonl` to the server or frontend.
