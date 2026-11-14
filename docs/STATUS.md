# Project status

Updated: 2026-11-14

## Delivered

- Read the project specification and dataset documentation. Preserved original dataset files.
- Parsed all 7,990 question rows: valid JSON, 320 unique referenced paths, and no missing question-linked files.
- Added deterministic group-aware train/validation/test splits and leakage/near-duplicate audits. The latest recorded split has 317 groups: train 5,610 rows, validation 1,185, test 1,195. One perceptual-hash near-duplicate pair remains flagged for manual review.
- Kept validation/test runtime inputs answer-free and gold references separate under `artifacts/evaluation/gold/`; the answering API does not import the evaluator or gold data.
- Built a local-first FastAPI app with document catalog/upload, PDF/image/SVG/DXF preview, page navigation, zoom/pan, evidence overlays, and execution traces. The catalog now returns lightweight metadata first and inspects capabilities only when a document is selected.
- Implemented local evidence tools for IFC typed counts, PDF selectable-text search, SVG text anchors, DXF named blocks/door-layer geometry, room-outline area calculations, and optional EasyOCR/PaddleOCR.
- Added Grounding DINO Tiny, SAM 2.1, and CubiCasa inference adapters, source-coordinate mapping, high-resolution image tiling, model overlays, and PaddleOCR. Grounding DINO/SAM and the official CubiCasa checkpoint are cached locally; PaddleOCR 3.7.0 and PaddlePaddle 3.3.1 are installed with the English models cached outside the repository. No model weights are checked into source control.
- Groq uses the official Python SDK with `GROQ_API_KEY`/`GROQ_MODEL` and structured, allowlisted question planning only. It receives no drawing, OCR, tool result, or evidence and does not generate answer text.
- Added a modular Google GenAI adapter using `GEMINI_API_KEY` and `GEMINI_MODEL`. It allowlists only `gemini-3.5-flash-lite`, sends an annotated reduced image plus detector candidates only after separate per-request consent, and returns validated structured semantic label reviews. It cannot answer/count/measure or change detector evidence. No paid model or other-provider fallback exists.
- Added Gemini UI disclosure of free-tier content use, confidentiality warning, and EEA/UK/Switzerland restriction. `.env.example` now contains blank credential placeholders only.
- Current backend status reports Groq and Gemini configured, and the local capability endpoint reports Grounding DINO, SAM 2, PaddleOCR, and CubiCasa available. CubiCasa source/checkpoint paths are configured in the ignored local `.env`; credentials remain there and are never printed. `/`, `/api/health`, `/api/llm/status`, and `/api/tools` respond successfully.
- Real raster checks passed on `colorful-11397.png`: Grounding DINO returned a local candidate; CubiCasa produced 73 segmented regions with source-coordinate mapping; PaddleOCR returned 13 text regions within source-image coordinates. The API/UI route for a door-count question returned 12 CubiCasa door predictions with 12 evidence references and overlays, honestly marked partial and unverified. These outputs are model predictions, not ground truth.
- Official Google docs list `gemini-3.5-flash-lite` as stable, image-input capable, and structured-output capable; its standard free tier lists zero input/output token charges. Project-specific free quotas vary. Google’s terms prohibit free-tier Gemini API clients being made available to users in the EEA, UK, or Switzerland and permit human review/product improvement of unpaid-service inputs.

## Validation completed

- `python -m unittest discover -s tests -v`: 42 tests passed, including deferred catalog inspection, IFC companion preview metadata, PaddleOCR download gating/CPU configuration, Gemini structured response validation, and Groq planner routing.
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
4. Continue improving PDF schedule extraction, IFC geometry/projection, and DWG conversion (only with a licensed local converter). Keep reference answers isolated from runtime.

## Run

From the project root:

```powershell
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```
