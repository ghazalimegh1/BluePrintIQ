# Project status

Updated: 2026-11-14

## BLUELOGIC vertical slice

- Added a FastAPI IFC scene API with validated paging (maximum 400 items per page) and a bounded GlobalId-selection endpoint. IFC product geometry is tessellated by IfcOpenShell, rebased to a source origin, and returned with native GlobalIds, storey relationships, metre units, and provenance.
- Added an explicit CubiCasa raster/PDF scene adapter. It converts actual detected polygons into a display-only 2.5D view and marks metric height and area as unknown and extrusion height as illustrative.
- Added a separate React 19/TypeScript/Vite application using Three.js, React Three Fiber, and Drei. It provides document search/upload, original drawing previews, evidence overlays, a selectable IFC scene, selected-entity inspection, question execution traces, explicit provider consent, and loading/error states.
- FastAPI serves the production frontend from `frontend/dist` when it is built, while the existing STOA interface remains accessible at `/legacy`. Vite proxies `/api` to the backend for development.
- Build and run instructions are in `README.md` and `docs/DEMO_GUIDE.md`. The actual Esplanades IFC and paired plan remain local and unmodified.
- Live browser check against the local dataset: the React UI loaded the Esplanades IFC, showed its companion PDF, rendered a paged native 3D scene, and answered “How many doors are in this model?” with **211 doors**, 211 IFC evidence references, and a selected GlobalId. Groq and Gemini checkboxes were left off for this question.
- The React reconstruction action ran the actual cached CubiCasa checkpoint on `data/cubicasa5k/colorful-11397.png`, producing 65 detected regions in source-pixel coordinates. The frontend displayed the Three.js view and the warning that its extrusions are illustrative and non-metric.

## Delivered

- Read the project specification and dataset documentation. Preserved original dataset files.
- Parsed all 7,990 question rows: valid JSON, 320 unique referenced paths, and no missing question-linked files.
- Added deterministic group-aware train/validation/test splits and leakage/near-duplicate audits. The latest recorded split has 317 groups: train 5,610 rows, validation 1,185, test 1,195. One perceptual-hash near-duplicate pair remains flagged for manual review.
- Kept validation/test runtime inputs answer-free and gold references separate under `artifacts/evaluation/gold/`; the answering API does not import the evaluator or gold data.
- Built a local-first FastAPI app with document catalog/upload, PDF/image/SVG/DXF preview, page navigation, zoom/pan, evidence overlays, and execution traces. The catalog now returns lightweight metadata first and inspects capabilities only when a document is selected.
- Added a React/Three.js BLUELOGIC workbench and native IFC scene API without deleting the working legacy UI. Scene rendering/provenance and image-to-model limitations are disclosed in the UI.
- Implemented local evidence tools for IFC typed counts, PDF selectable-text search, SVG text anchors, DXF named blocks/door-layer geometry, room-outline area calculations, and optional EasyOCR/PaddleOCR.
- Added an optional explainable classical-CV route using adaptive thresholding, morphology, Canny edges, probabilistic Hough lines, and connected components. It returns source-aligned geometric evidence and never promotes candidates to semantic counts.
- Added Grounding DINO Tiny, SAM 2.1, and CubiCasa inference adapters, source-coordinate mapping, high-resolution image tiling, model overlays, and PaddleOCR. Grounding DINO/SAM and the official CubiCasa checkpoint are cached locally; PaddleOCR 3.7.0 and PaddlePaddle 3.3.1 are installed with the English models cached outside the repository. No model weights are checked into source control.
- Groq uses the official Python SDK with `GROQ_API_KEY`/`GROQ_MODEL` and structured, allowlisted question planning only. It receives no drawing, OCR, tool result, or evidence and does not generate answer text.
- Added a modular Google GenAI adapter using `GEMINI_API_KEY` and `GEMINI_MODEL`. It allowlists only `gemini-3.5-flash-lite`, sends an annotated reduced image plus detector candidates only after separate per-request consent, and returns validated structured semantic label reviews. It cannot answer/count/measure or change detector evidence. No paid model or other-provider fallback exists.
- Added Gemini UI disclosure of free-tier content use, confidentiality warning, and EEA/UK/Switzerland restriction. `.env.example` now contains blank credential placeholders only.
- Current backend status reports Groq and Gemini configured, and the local capability endpoint reports Grounding DINO, SAM 2, PaddleOCR, and CubiCasa available. CubiCasa source/checkpoint paths are configured in the ignored local `.env`; credentials remain there and are never printed. `/`, `/api/health`, `/api/llm/status`, and `/api/tools` respond successfully.
- Real raster checks passed on `colorful-11397.png`: Grounding DINO returned a local candidate; CubiCasa produced 73 segmented regions with source-coordinate mapping; PaddleOCR returned 13 text regions within source-image coordinates. The API/UI route for a door-count question returned 12 CubiCasa door predictions with 12 evidence references and overlays, honestly marked partial and unverified. These outputs are model predictions, not ground truth.
- Official Google docs list `gemini-3.5-flash-lite` as stable, image-input capable, and structured-output capable; its standard free tier lists zero input/output token charges. Project-specific free quotas vary. Google’s terms prohibit free-tier Gemini API clients being made available to users in the EEA, UK, or Switzerland and permit human review/product improvement of unpaid-service inputs.

## Validation completed

- `python -m unittest discover -s tests -v`: 46 tests passed, including the native IFC mesh, raster uncertainty, scene API pagination/selection validation, deferred catalog inspection, OCR, Gemini response validation, and Groq routing.
- `Set-Location frontend\\blue_logic; npm run build`: strict TypeScript check and Vite production build passed. Three.js is split from the UI; its largest minified vendor chunk is 689 kB (177 kB gzip).
- FastAPI served the built BLUELOGIC page and `/legacy` successfully; the 916-document catalog and both actual scene adapters were checked through the running app.
- `python -m compileall -q backend scripts tests`, `node --check frontend\\app.js`, and `python -m pip check`: pass.
- End-to-end local IFC demo passed: all 916 catalog records loaded in about 2.1 seconds; the default Esplanades IFC selected its PDF companion preview; `/api/ask` returned a supported answer of 211 doors with 211 evidence references and successful planner, IFC-count, and evidence-validation steps. The browser displayed the selected model and companion plan.
- Pylance syntax checks report no syntax errors in the new Gemini adapter, router, or tests. The editor-selected interpreter still points to Microsoft Store Python, while terminal validation used `C:\\Users\\HP\\Python313\\python.exe`; editor import diagnostics therefore report missing third-party modules despite their presence in the terminal interpreter.
- `google-genai==3.3.0` was installed and the Interactions API, `HttpOptions`, and API error signatures were inspected.
- Live Gemini smoke test passed using only a synthetic image and one candidate; the allowlisted `gemini-3.5-flash-lite` returned a valid structured review.
- Live Groq planner smoke test passed using a synthetic question and the registered `ifc_entity_count` tool. Authentication and model listing succeeded. One initial planner request returned HTTP 400; a subsequent request passed, so monitor for recurrence.
- `python -m pip check`, `python -m compileall -q backend scripts tests`, and `node --check frontend\\app.js` passed after installing the OCR stack. PaddleOCR CPU inference required `enable_mkldnn=False` on this Windows/Paddle build; the adapter now uses CPU-only, oneDNN-disabled inference and does not download missing weights unless explicitly opted in.
- The running app was verified at `http://127.0.0.1:8000`; `/api/health` returned `ok`, all four local raster tools reported available, and a real CubiCasa request rendered its 12 model masks in the frontend.

## Current limits and next steps

1. Revoke/replace credentials previously exposed in chat or `.env.example`; keep replacements only in ignored `.env` or hosting secrets. Restart the backend after rotating keys.
2. The current CPU-only laptop has limited RAM and slow local inference (about 61 seconds for the earlier DINO sample, 60 seconds for OCR, and 14 seconds for CubiCasa at a 512-pixel maximum side). Avoid concurrent specialist inference and keep results explicitly partial until a drawing-identity-split, manually annotated evaluation set has been created.
3. Before any hosted demo, confirm the audience and region: free-tier Gemini must not serve API-client users in the EEA, UK, or Switzerland. Do not submit confidential or personal drawings to the unpaid service.
4. IFC native geometry is available in the separate 3D viewport, but projection/alignment onto companion 2D drawings is not implemented. Raster 2.5D geometry is display-only, not a dimensioned BIM model. Continue improving PDF schedule extraction and DWG conversion (only with a licensed local converter). Keep reference answers isolated from runtime.
5. The frontend build currently produces a large Three.js bundle; verify its split chunks and optimize further if startup is slow on the demo machine.

## Evaluation follow-up

- Added `docs/EVALUATION.md` with the protected-gold scoring protocol, leakage-safe workflow, and raster annotation requirements.
- A real CubiCasa run on `junction-dataset-preview/data/cubicasa5k/colorful-34.png` returned 100 total regions and 2 retained `window` regions. The benchmark row for that image expects 17, so this remains an explicitly partial model prediction and is not presented as validated benchmark accuracy.
- Raster scene elements now carry stable source evidence IDs, measured source-pixel area, and detected symbol-to-room containment relationships when polygons support them. These relationships remain explicitly detected 2D relationships, not metric BIM topology.
- The validated interpreter for this workspace is `C:\Users\HP\Python313\python.exe`; the full test suite now passes 48 tests with that interpreter.
- Added `scripts/run_runtime_eval.py`, an answer-free held-out evaluation harness that calls the same runtime answer path as the API and writes evidence/status predictions without loading gold answers. This supports reproducible accuracy and evidence-coverage reporting for the judging criteria.

## Run

From the project root:

```powershell
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```
