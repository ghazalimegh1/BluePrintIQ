# Next-agent handoff

Read `STOA_COMPLETE_PROMPT_FOR_ALL_VSCODE_AGENTS.md` before expanding scope.

## Workspace and run

- Workspace: `C:\Users\HP\Desktop\JunctionHack`
- Dataset path when separately provisioned: `junction-dataset-preview/`. The 0.68 GB dataset is intentionally excluded from Git because it contains answer data and mixed per-file third-party licences; obtain an authorized copy before running dataset-backed tests.
- The remote repository was empty when push preparation began; only source, documentation, tests, and scripts should be committed. `.env`, `runtime/`, and generated `artifacts/` remain ignored.
- Current implementation and limitations: `docs/STATUS.md`
- Architecture/security decisions: `docs/DECISIONS.md` and `docs/ARCHITECTURE.md`
- Run from the project root: `python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000`

## Current provider/vision state

- Groq uses the official SDK for question interpretation and tool routing only. It never receives a drawing, OCR output, tool result, evidence, or answer, and it does not generate answer wording.
- Gemini uses `google-genai`, `GEMINI_API_KEY`, and `GEMINI_MODEL`. The free-tier allowlist contains only `gemini-3.5-flash-lite`; there is no paid or alternate-provider fallback.
- Gemini only reviews labels on local Grounding DINO detections. The frontend requires separate per-request image-sharing consent and discloses free-tier content use and geography restrictions.
- The latest `/api/llm/status` check reports Groq and Gemini configured. The local capability endpoint reports Grounding DINO, SAM 2, PaddleOCR, and CubiCasa available. `/`, `/api/health`, `/api/llm/status`, and `/api/tools` respond successfully; the app is running at `http://127.0.0.1:8000`.
- A credential was exposed in chat and another was placed in `.env.example`; the Gemini value was moved to the ignored local `.env`, and both example key placeholders are now blank. Treat exposed keys as compromised and rotate them; never put credentials in source or chat.
- The document catalog now returns lightweight metadata first; capability inspection is deferred until a user selects a document. This reduced the real catalog load from a 90-second timeout to about 2.1 seconds for 916 records.
- End-to-end local IFC demo passed: the default Esplanades IFC opened with its PDF companion preview, and `/api/ask` returned 211 doors with 211 evidence references. The browser showed the selected IFC and companion plan.
- Google’s model docs list `gemini-3.5-flash-lite` as stable with image input and structured outputs and free standard input/output tokens. Per-project quotas vary. Unpaid-service content may be reviewed/used to improve Google products; do not send confidential/personal drawings. Free-tier API clients cannot be made available to users in the EEA, UK, or Switzerland.
- Live synthetic smoke tests passed for Groq question planning and Gemini structured image review (`gemini-3.5-flash-lite`). The Gemini test used a generated image, not a project drawing. An initial Groq planner request returned HTTP 400, followed by a successful request; monitor if repeated.

## Verified implementation and checks

- Group-aware split/evaluation tooling is in `scripts/create_splits.py` and `scripts/evaluate.py`. The recorded split has 317 groups: train 5,610 rows, validation 1,185, test 1,195. One perceptual-hash near-duplicate pair remains flagged.
- Runtime inputs for validation/test contain no answers; gold remains under `artifacts/evaluation/gold/` and must never be connected to the app.
- FastAPI backend and frontend are in `backend/app/` and `frontend/`.
- Local routes cover IFC typed counts, PDF text evidence, SVG native text, DXF named blocks/door-layer geometry, room-outline area calculations, and optional OCR.
- Optional local adapters exist for Grounding DINO Tiny, SAM 2.1 Hiera Small, CubiCasa, and PaddleOCR. On this Python 3.13 CPU-only machine, all four local raster capabilities are now installed/cached and report available. Actual raster checks passed: CubiCasa returned 73 regions; PaddleOCR returned 13 source-aligned text regions; the UI/API returned 12 CubiCasa door predictions with 12 overlays, marked partial/unverified. Grounding DINO inference previously returned a real candidate; SAM succeeded in the earlier full raster API test.
- `google-genai==3.3.0` is installed. Focused SDK tests check the image request, structured response validation, free-model rejection, consent default, and credential-safe quota error.
- `python -m unittest discover -s tests -v`: 42 tests pass.
- `python -m compileall -q backend scripts tests`, `node --check frontend\\app.js`, and `python -m pip check`: pass after OCR dependency installation.
- Pylance syntax checks are clean. The VS Code-selected interpreter still points to Microsoft Store Python, while terminal validation used `C:\\Users\\HP\\Python313\\python.exe`; editor import diagnostics may therefore show false missing-package warnings until its interpreter selection is corrected.

## Next actions

1. Revoke/replace credentials previously exposed in chat or `.env.example`; keep replacements only in ignored `.env` or hosting secrets. Do not print or paste secrets.
2. Check the Google AI Studio project's active free-tier quota. Do not send project drawings to an external provider without per-request consent.
3. Before hosting, ensure the free-tier Gemini API client is not available to users in the EEA, UK, or Switzerland; otherwise do not enable this free-tier path.
4. The laptop has low free RAM and local inference is slow; do not keep DINO, SAM, PaddleOCR, and CubiCasa loaded concurrently. Current model predictions are not validated ground truth. Build a manually annotated subset split by drawing identity and evaluate precision/recall before making accuracy claims.
5. Continue PDF schedule extraction, IFC geometry/projection, and licensed DWG conversion without leaking reference answers into runtime.

Do not modify original dataset files. Preserve source attribution and licence constraints.
