# BLUELOGIC · Junction 2026 Construction Intelligence

Local-first construction-document system prototype. It detects document formats, uses Groq only to plan/select registered tools, and returns source-linked evidence where the selected local pipeline supports it.

## BLUELOGIC spatial workbench

The React/TypeScript interface in `frontend/blue_logic/` adds a source drawing viewer, paged native IFC scene, selectable model elements, source evidence overlays, and a question/trace panel. IFC triangles come from IfcOpenShell and retain their GlobalIds and provenance; large models load in pages. A raster/PDF 2.5D view is an explicit user-triggered CubiCasa inference and is labelled display-only because its scale and extrusion heights are unknown. It is not a metric BIM reconstruction.

From the project root, either use Vite for development and run FastAPI in another terminal:

```powershell
Set-Location frontend\blue_logic
npm ci
npm run dev
```

Open `http://127.0.0.1:5173`. Vite proxies `/api` to the FastAPI server at `http://127.0.0.1:8000`.

For the production-style FastAPI-served UI, build before starting the backend:

```powershell
Set-Location frontend\blue_logic
npm ci
npm run build
Set-Location ..\..
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

The previous vanilla STOA interface remains available at `/legacy`. IFC scene endpoints are `GET /api/documents/{id}/scene` (paged) and `POST /api/documents/{id}/scene/elements` (GlobalId geometry).

## What works today

- Browse or upload local PDF, PNG/JPEG, SVG, DXF, and IFC documents. DWG is recognized but requires a separately installed converter; conversion is not silently claimed.
- Render raster sources and PDF pages in a zoomable/pannable drawing viewer. DXF files can be rendered as vector SVG with the source model-to-view transform preserved.
- Dynamically route IFC count questions to IfcOpenShell typed-entity queries. Floor scope uses IFC spatial containment and returns matching GlobalIds.
- Search selectable PDF text and return exact page spans, PDF-point boxes, and clickable highlights. Optional local vision models process selected raster/PDF pages when their dependencies and weights are installed.
- Run optional local PaddleOCR or EasyOCR on raster text questions and on the selected PDF page when selectable text is absent. OCR results include source-aligned text boxes; OCR is not used to claim object counts.
- Route raster questions to Grounding DINO Tiny, SAM 2.1, and CubiCasa5K when their local weights are installed. These models return source-aligned detections/masks; counts remain partial predictions, not verified truth.
- Route explicit wall-line and classical-CV questions through an optional OpenCV analysis layer using adaptive thresholding, morphology, Canny edges, probabilistic Hough lines, and connected components. Its output is geometric evidence, not semantic object counting.
- Search native SVG text and locate untransformed text anchors.
- Query explicitly named DXF door blocks/layers, highlight source geometry, and calculate closed room-outline areas using declared DXF units. Unsupported scope and incomplete outlines are surfaced rather than hidden.
- Use optional Gemini free-tier semantic review for local Grounding DINO detections after separate per-request consent. Gemini cannot answer questions, count objects, provide measurements, or alter detector boxes.
- Keep Groq planner-only: it receives the question and registered tool descriptions, not the drawing, OCR results, evidence, tool output, or answer.
- Abstain explicitly when local OCR weights, object detection/segmentation, DWG conversion, semantic CAD mappings, or IFC-to-2D projection are unavailable.
- Generate group-aware train/validation/test data splits. Runtime endpoints never load `questions.jsonl` or the evaluator-only gold directory.
- Evaluate prediction JSONL separately with exact-count, 2%-measurement, normalized-text, evidence-coverage, and group/source/type metrics.

This remains a prototype, not a fully validated production system. Local Grounding DINO/SAM/CubiCasa and PaddleOCR inference have been smoke-tested in this workspace, but a manually annotated evaluation set and calibrated accuracy metrics are still missing. General PDF schedule/table extraction, DWG conversion, broad DXF reconstruction, IFC geometry projection, and trained STOA models remain unavailable. Groq planner and Gemini review were smoke-tested; Gemini is optional and consent-gated.

## Requirements and run

Python 3.13 is verified. From the project root in PowerShell:

```powershell
python -m pip install -r requirements.txt
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). The API and document processing are local by default. Uploads are stored under the gitignored `runtime/uploads/` folder and limited to 25 MiB.

The 0.68 GB `junction-dataset-preview/` collection is not included in this repository. It contains third-party drawings with mixed per-file licences and answer data. To run dataset-backed demos and tests, place an authorized copy at the project root and follow its per-source attribution/licence terms. Dataset splits and evaluation outputs are generated locally under the ignored `artifacts/` directory.

The base requirements include the IFC and DXF libraries. OCR is a large optional PyTorch dependency; install it only when needed:

```powershell
python -m pip install -r requirements-ocr.txt
```

The local vision stack is also optional and can require substantial disk space and CPU/GPU resources:

```powershell
python -m pip install -r requirements-vision.txt
python scripts\download_vision_models.py --models grounding-dino-tiny sam2.1-hiera-small
python scripts\download_cubicasa_model.py
python -m pip install -r requirements-vision-ocr.txt
```

Model downloads are not automatic unless explicitly run. Grounding DINO and SAM 2.1 use their public Hugging Face checkpoints; the CubiCasa source/checkpoint is CC BY-NC 4.0 and restricted to non-commercial use. Set `STOA_CUBICASA_SOURCE_DIR` and `STOA_CUBICASA_CHECKPOINT` to the paths printed by its downloader. This machine is CPU-only; first inference can be slow.

By default, OCR will not download model files automatically. To explicitly permit EasyOCR's first-use English model download, set `STOA_OCR_DOWNLOAD_MODELS=true` in the backend process before starting it. Alternatively, place `craft_mlt_25k.pth` and `english_g2.pth` in EasyOCR's model directory (`%USERPROFILE%\.EasyOCR\model`) or set `STOA_OCR_MODEL_DIR` to another local directory. The API reports OCR as unavailable until its package, PyTorch, and both weights are present (or downloads are explicitly enabled). OCR processes English text only in this implementation.

For PaddleOCR, run `python scripts\download_ocr_models.py` once to explicitly cache the English detection and recognition weights. Inference uses CPU mode with oneDNN disabled for compatibility with the PaddlePaddle Windows CPU build. To permit PaddleOCR's first-use downloads from the app instead, set `STOA_OCR_DOWNLOAD_MODELS=true`; otherwise missing weights are reported as unavailable.

## Leakage-safe dataset pipeline

```powershell
python scripts\create_splits.py --seed 2026
python -m unittest discover -s tests -v
```

Input-only validation/test files are under `artifacts/data_splits/`. Their references are held separately under the gitignored `artifacts/evaluation/gold/`. The solver must only receive the `*_inputs.jsonl` file and source documents; use gold only from a separate evaluator after inference.

Evaluate predictions without connecting the evaluator to the runtime:

```powershell
python scripts\evaluate.py --predictions predictions.jsonl --gold artifacts\evaluation\gold\validation_gold.jsonl
```

To produce predictions from answer-free held-out inputs, use the same runtime path as the API:

```powershell
python scripts\run_runtime_eval.py --source ifc_bench --limit 20 --output artifacts\evaluation\predictions.jsonl
```

See [docs/DATA_AUDIT.md](docs/DATA_AUDIT.md), [docs/DATA_SPLITS.md](docs/DATA_SPLITS.md), and [docs/DEMO_GUIDE.md](docs/DEMO_GUIDE.md) for audited facts and example flows.

## Groq planner and Gemini vision review

Groq is used only for question interpretation and tool routing. The official Groq Python SDK reads `GROQ_API_KEY`; `GROQ_MODEL` selects the planner model. For local setup, copy `.env.example` to the ignored `.env` file and fill in secrets locally. Never commit `.env` or paste a key into chat/source:

```powershell
Copy-Item .env.example .env
# Edit .env locally and set GROQ_API_KEY without sharing it.
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Set `GROQ_MODEL` to a tool-calling model enabled for your account. The UI requires explicit per-tab consent before **Analyze** sends the question and tool descriptions to Groq. Groq never receives images, extracted evidence, or answers; local tools determine results.

For Gemini semantic review, set `GEMINI_API_KEY` and `GEMINI_MODEL=gemini-3.5-flash-lite` in the backend environment or `.env`. Only this free-tier model is allowed; unsupported/paid models fail closed, with no paid fallback. The route appears only when Grounding DINO is locally available and requires a separate per-request consent. Google's free-tier service may use submitted content to improve products and may involve human review; do not send confidential/personal drawings. Google's terms prohibit free-tier Gemini API clients being made available to users in the EEA, UK, or Switzerland. Project quotas vary and must be checked in AI Studio.

`/api/llm/status` reports key presence and non-secret model names only. Any credential previously exposed in chat must be revoked. Do not paste replacement keys into chat, screenshots, or version control.

## Attribution and data handling

When an authorized dataset copy is present at `junction-dataset-preview/`, the UI exposes its source notice and local licence file. Do not redistribute source drawings without checking their licence; some sources are non-commercial or share-alike, and some IFC files are no-derivatives. Original dataset files are read-only to this application.
