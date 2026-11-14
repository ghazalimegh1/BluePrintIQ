# STOA Junction 2026 — Master Prompt for VS Code Coding Agents

> **Use this as the primary, self-contained instruction for the lead coding agent.**  
> The agent should read this entire document before changing code. It should then inspect the actual workspace and coordinate implementation. This brief is deliberately dataset-aware but the product architecture must remain general and question-driven.

---

## 0. Your role and mission

You are the **technical lead, architect, and integration engineer** for our Junction 2026 STOA challenge project.

Build the first working demo of a **general-purpose multimodal construction-document intelligence system**. An engineer should be able to provide construction drawings and models in different formats, ask a natural-language question, and receive a correct answer with traceable evidence showing where the answer came from.

The system must not be hardcoded for one source, file format, object category, or question type. It must use the question and the capabilities of the available documents to choose an appropriate execution plan dynamically.

The core product loop is:

**Question + documents → understand the request → discover available evidence/capabilities → plan tool calls → execute tools → validate results → answer with source evidence.**

Do not build merely a chatbot that sends an entire drawing to a VLM. Build a modular system that combines existing AI models with deterministic document, computer-vision, geometric, and BIM tools.

Your immediate target is a **credible, end-to-end peer-submission demo**, not a complete commercial product or a system that supports every file type perfectly.

---

## 1. Mandatory first action: inspect the actual workspace

Before writing or modifying code:

1. Inspect the repository tree and identify the project root.
2. Read `README.md` completely.
3. Inspect `questions.jsonl` and validate every JSONL record.
4. Inspect the actual `data/` tree, if present. Do not assume every path in `questions.jsonl` is available locally; report missing paths.
5. Read relevant per-source `LICENSE.md` files before processing or sharing source material.
6. Inspect the existing code, environment, Python version, installed packages, frontend framework, and existing API contracts.
7. Reuse working code and dependencies where sensible. Do not replace the project structure without a reason.
8. Create `docs/DATA_AUDIT.md` before large-scale implementation.

Do not process the complete dataset initially. Select a small, representative set of actual files for the first working workflow, then expand after the pipeline works.

### 1.1 Dataset facts established from the provided files

The supplied `README.md` describes a larger collection of approximately:

- 14,000 construction drawings/models.
- Seven principal formats: PDF, DWG, DXF, IFC, SVG, PNG, and JPEG scans.
- Around 30 languages.
- Around 120,000 quantity-takeoff questions for roughly 40% of the drawings in the full challenge collection.

The README documents this layout:

```text
 data/<source>/<file>      drawings and models
 data/<source>/LICENSE.md  licence and credit for the source folder
 questions.jsonl           one JSON object per question
```

The question schema is:

```json
{
  "path": "data/source/file.ext",
  "question": "Natural-language question",
  "answer": "Reference answer",
  "unit": "count | m2 | m | m3 | ...",
  "type": "count | area | length | volume | text | other"
}
```

Important facts from the actual supplied `questions.jsonl` in this workspace:

- **7,990 question rows**.
- **320 distinct `path` values**.
- Type counts:
  - `count`: 6,076
  - `area`: 1,599
  - `text`: 265
  - `volume`: 34
  - `length`: 16
- Source counts in those question rows:
  - `cubicasa5k`: 4,270
  - `swiss_dwellings`: 2,358
  - `ifc_models`: 1,049
  - `ifc_bench`: 249
  - `opening_design`: 64

These counts describe the **provided question file**, not the entire challenge collection. Never confuse the 7,990 supplied records with the README's approximately 120,000 questions across the larger dataset.

The question file contains repeated/parallel questions in different languages. Multiple questions can refer to the same drawing. The README explicitly states:

- Files with the same name and different extensions can be the same drawing in another format.
- Under `ifc_models`, floor-plan PDFs named `<model>_<level>.pdf` were rendered from `<model>.ifc`.

The README also states the benchmark scoring rules:

- Counts must be **exact**.
- Areas, lengths, and volumes must be within **2%** of the reference value.
- Text answers are free-form.

The sources named in the README include `cubicasa5k`, `swiss_dwellings`, `opening_design`, `ifc_models`, `ifc_bench`, `habs`, `finna`, `europeana`, and `wikimedia`. The actual supplied question rows currently cover five of these source folders; still inspect the real `data/` tree because it may contain more files than those represented in `questions.jsonl`.

### 1.2 Dataset licensing and responsible handling

Every source folder has its own licence/credit file. Respect the licence for every file used or shown:

- Preserve attribution when displaying or sharing drawings.
- NonCommercial (NC) files are for non-commercial use only.
- ShareAlike (SA) adaptations must use the same licence.
- NoDerivatives (ND) files must remain unchanged.
- Questions inherit the licence of their source drawing.

Do not redistribute the dataset or upload source drawings to third-party services unless the challenge terms, source licence, and data-handling rules allow it. Prefer local processing or approved services. Never commit credentials or API keys.

---

## 2. Critical requirement: create leakage-safe train / validation / test splits

This is mandatory. We need reproducible splits to develop, train where suitable, tune, and evaluate the system. Do **not** randomly split question rows.

### 2.1 Why row-level splitting is wrong

The same drawing can have several questions, translations, or alternate file representations. If questions about the same drawing appear in both training and test, the system may effectively see the test drawing during development. That produces an inflated and misleading score.

The split unit must be the **logical drawing / model / building / project family**, not an individual question row and not blindly the literal path string.

### 2.2 Build a canonical group resolver

Implement a deterministic grouping function that assigns each question row and each related file a `group_id` representing the logical source drawing/model or, where appropriate, the building/project.

Use the following evidence, from strongest to weakest:

1. **Explicit relationships in the README and source structure.** For example, an IFC model and its rendered floor-plan PDF(s) must belong to the same group.
2. **Same logical basename across extensions.** Same-name PDF/DWG/DXF/SVG/PNG/JPEG files in the same source/drawing family must be grouped.
3. **Building/project identity.** If several floors, sheets, or views belong to one building/project, keep the full family together where the identity is available. Examples:
   - `swiss_dwellings`: derive a building-level key from site/building identifiers, not an individual floor identifier, when multiple floors for one building are present.
   - `opening_design`: drawings in the same project folder/set should normally stay together to prevent project leakage.
   - `ifc_models`: the IFC model and all floor-plan renderings with the model's level suffixes must stay together.
   - `ifc_bench`: all records associated with one IFC model stay together.
   - `cubicasa5k`: all question variants for the same underlying floor-plan image stay together.
4. **Content hashes.** Use SHA-256 to identify exact duplicate files when accessible.
5. **Near-duplicate checks.** Where feasible, use perceptual hashes or page/image similarity to flag likely duplicate renderings. Do not automatically merge uncertain files without recording the reason; flag them for review.

Do not overfit the resolver to the examples above. Make it extensible and record the grouping method and confidence/reason for every assignment. If identity is ambiguous, prefer conservative grouping to prevent leakage.

### 2.3 Split policy

Create a reproducible initial split with these target proportions:

- **70% train**
- **15% validation**
- **15% test**

These are target proportions, not a reason to violate group boundaries. Split whole `group_id` families. Use a fixed seed and a group-aware assignment method. Try to balance source and question type across splits where possible, but group integrity takes priority over exact stratification.

Important edge cases:

- Rare types such as `length` and `volume` may occur in very few independent drawing/model families. Do not split one family across sets just to force each set to contain a rare type. Instead, report which categories cannot be represented in each partition and use transparent cross-validation or a separate diagnostic evaluation if necessary.
- Preserve all translations/rewrites of the same question and all questions for one drawing family in the same partition.
- Group alternate file formats and rendered/model pairs before splitting.
- If several drawings belong to the same building/project, keep the project together when feasible.

### 2.4 Required split artifacts

Create:

```text
artifacts/data_splits/
  train.jsonl                 # contains training questions and reference answers
  validation_inputs.jsonl     # questions/metadata only; NO reference answers
  test_inputs.jsonl           # questions/metadata only; NO reference answers
  split_manifest.json
  leakage_audit.json
artifacts/evaluation/gold/
  validation_gold.jsonl       # evaluator-only reference answers
  test_gold.jsonl             # evaluator-only reference answers
```

Each input row must preserve the question and non-answer metadata and add non-destructive metadata such as:

```json
{
  "path": "data/cubicasa5k/example.png",
  "question": "How many windows are shown?",
  "unit": "count",
  "type": "count",
  "group_id": "canonical-logical-family-id",
  "split": "test",
  "source": "cubicasa5k"
}
```

Keep reference answers out of `validation_inputs.jsonl` and `test_inputs.jsonl`. Store them in the separate evaluator-only gold files. The training file may contain answers for supervised training. The evaluator should join predictions with gold references only after inference has completed. Add the gold directory to `.gitignore` if appropriate, and never expose test gold to the model, agent prompts, runtime API, retrieval index, or frontend.

`split_manifest.json` must include:

- Split seed and target proportions.
- Split algorithm/version.
- Total rows, groups, and unique paths per partition.
- Counts by source and question type per partition.
- Group resolver rules and reason for each group assignment (or a sidecar mapping).
- Missing source-file paths.
- File hashes where available.
- Any manual overrides and the reason for each.

`leakage_audit.json` must verify and report:

- No `group_id` occurs in more than one split.
- No exact path occurs in more than one split.
- No alternate-format family is divided across splits.
- No known IFC model / rendered-plan family is divided across splits.
- No translations or paraphrases attached to one source drawing are divided across splits.
- Exact duplicate hashes do not cross splits.
- Potential near-duplicates are listed for review.

Add automated tests that fail if the audit detects a hard leakage violation.

### 2.5 Correct use of train, validation, and test

- `train`: use for supervised experiments, fine-tuning where there are suitable labels, examples, or annotations, and development of learned components.
- `validation`: use for model selection, threshold selection, prompt/workflow iteration, and hyperparameter tuning. The solver receives only `validation_inputs.jsonl`; a separate evaluator joins predictions to `validation_gold.jsonl`.
- `test`: hold out until the system and configuration are frozen. The solver receives only `test_inputs.jsonl`; a separate evaluator joins predictions to `test_gold.jsonl` after inference. Do not use test results repeatedly to tune prompts, models, routing rules, thresholds, or heuristics.

Never put reference `answer` fields into the runtime retrieval index or provide them to the question-answering system at inference time. Gold references must be isolated from runtime services and agent prompts. The evaluation harness may load gold answers in a separate evaluator process, but the runtime solver must only receive the question and allowed source documents. Do not use validation/test answers as context for generation or tool selection.

**Important annotation limitation:** `questions.jsonl` provides question-answer pairs and types/units; it does not, by itself, provide bounding boxes, masks, symbol locations, or segmentation labels. Do not claim that these QA rows are sufficient to train an object detector or segmentation model. Inspect source files for additional annotations. If no localization labels exist, use pretrained models, manual annotation of a small subset, weak supervision with explicit caveats, or focus on tool routing and deterministic extraction.

### 2.6 Baseline evaluation and metrics

Before fine-tuning, build at least one transparent baseline and an evaluation harness.

Implement the README's scoring logic:

- Count: exact numeric match after safe normalization.
- Area / length / volume: absolute relative error no greater than 2%, with unit normalization/conversion handled correctly.
- Text: free-form comparison. Report normalized exact match and a separately labelled semantic/human review measure; do not silently substitute an LLM judge for the official metric.

Also report:

- Accuracy by question type and source.
- Group-level performance, not only aggregate row-level performance.
- Evidence coverage: percentage of answers with a usable source reference.
- Evidence correctness: whether cited page/region/entity actually supports the answer (audit a sample manually if full automation is not possible).
- Abstention/unknown rate and accuracy on answered questions.
- Latency and model/tool cost where measurable.

Keep a clear distinction between benchmark correctness and evidence quality. A correct answer without verifiable evidence is not a complete product answer.

---

## 3. Product architecture: a general, question-driven system

The architecture combines three complementary foundations:

1. **Capability-based multimodal indexing**: process documents once and expose what can be extracted from each file.
2. **A shared knowledge/evidence representation**: connect documents, pages, entities, annotations, geometry, BIM objects, and relationships while preserving native sources.
3. **Agentic orchestration**: interpret each question and dynamically plan which tools to use, in what order, and when evidence is sufficient.

Do not force every drawing into one lossy universal format. Preserve source-native representations and provide common interfaces over them.

### 3.1 Phase A — Ingestion and document understanding

For each file:

1. Detect format and validate readability.
2. Register document metadata, source, licence, file hash, and identity/group relationships.
3. Use the appropriate adapter(s):
   - PDF: extract text, vector paths where possible, page dimensions, and rendered pages.
   - DWG/DXF: extract layers, entities, blocks, text, coordinates, dimensions, and geometric primitives where supported.
   - IFC: extract spatial structure, elements, relationships, properties, quantities, units, and geometry.
   - SVG: parse vector elements, text, groups, and coordinates.
   - PNG/JPEG: retain original image, create multi-scale views, run OCR/visual analysis as needed.
4. Produce a capability report for the document.
5. Preserve coordinate transforms between native coordinates, rendered page pixels, crops, and evidence overlays.

Do not rasterize vector documents as the only representation. Do not assume every PDF is vector or every image is a clean scan.

### 3.2 Phase B — Shared representation and evidence store

Use a practical relational representation for the first demo; a dedicated graph database is optional, not a prerequisite. PostgreSQL (or SQLite for a very small local MVP) can store structured records initially.

Represent at least:

- Document and file identity.
- Page/sheet/view.
- Visual region/crop.
- Text span/annotation.
- Table/schedule and cells.
- Geometric primitive/shape and coordinate system.
- Building element / semantic entity.
- BIM entity and IFC GlobalId when present.
- Relationships between entities.
- Evidence provenance and extraction method.

Each extracted fact must carry provenance, for example:

```json
{
  "value": 200,
  "unit": "mm",
  "entity_id": "W12",
  "source": {
    "document_id": "doc-123",
    "path": "data/example/plan.pdf",
    "page": 4,
    "region": [120, 340, 280, 410],
    "coordinate_system": "page_pixels",
    "source_type": "dimension_annotation",
    "extracted_text": "200 mm",
    "extraction_tool": "ocr_or_pdf_text",
    "confidence": 0.96
  }
}
```

The confidence value above is an illustrative example, not a prescribed score. Never fabricate a confidence value. Record the actual method and whether a confidence estimate is available.

Potential relationships include `belongs_to`, `located_in`, `bounds`, `adjacent_to`, `connected_to`, `supports`, `refers_to`, `represented_by`, and `derived_from`. Only assert relationships with evidence; store provenance and confidence.

### 3.3 Phase C — Question understanding and planner

The question interpreter should transform natural language into a validated structured request. It should identify:

- Requested quantity or information.
- Target entities and synonyms.
- Scope: building, floor, room, sheet, document, zone, or time/version if relevant.
- Operation: find, count, measure, calculate, compare, classify, summarize, or retrieve text/property.
- Required output unit and constraints.
- Whether multiple documents or multiple steps may be needed.
- Ambiguities that materially affect the answer.

Use an LLM for semantic interpretation and planning, but validate its output with Pydantic/JSON Schema. The LLM must not invent file capabilities or claim that a tool has run when it has not.

### 3.4 Phase D — Capability registry and dynamic routing

Do not use a brittle hardcoded rule such as `count → YOLO`, `area → geometry`, or `text → OCR`. Those rules fail when the same task can be solved from a BIM model, CAD file, vector PDF, or scan.

Every tool must register:

- Name and version.
- Description and supported operation(s).
- Supported input formats and document capabilities.
- Typed input/output schema.
- Preconditions and required identifiers.
- Whether it is deterministic, model-based, or external.
- Expected evidence/provenance output.
- Known limitations and optional cost/latency estimate.

The planner must consider both:

1. **What does the question require?**
2. **Which available source representation and tools can answer it most reliably?**

It may choose one tool, a sequence of tools, parallel calls, a verification call, or abstention. It should prefer the most precise available source (for example IFC/CAD geometry for a measurement) but must validate that the relevant data exists and is semantically appropriate.

The LLM may propose a plan, but only registered tools can execute. Do not execute arbitrary generated Python, shell commands, SQL, or code from the LLM. Use safe typed tool calls and parameter validation.

### 3.5 Phase E — Tool execution

Provide standardized tools where available. Initial useful tools include:

- `list_document_capabilities(document_id)`
- `search_text(query, document_scope)`
- `find_entity(name_or_description, scope)`
- `render_page(document_id, page, scale)`
- `crop_region(document_id, page, region)`
- `run_ocr(region_or_page)`
- `detect_objects(region_or_page, classes)`
- `segment_regions(region_or_page, task)`
- `extract_table(region_or_page)`
- `get_vector_geometry(document_id, entity_or_region)`
- `query_ifc(model_id, structured_query)`
- `find_relations(entity_ids, relation_types)`
- `calculate_area(geometry, assumptions)`
- `calculate_length(geometry, assumptions)`
- `calculate_volume(geometry_or_quantities, assumptions)`
- `render_evidence(evidence_refs, overlays)`

Use the tools that are actually implemented. Do not create fake stubs that return fabricated outputs. If a tool is not yet implemented, report that capability as unavailable so the planner can choose a valid fallback or abstain.

Deterministic operations (unit conversion, arithmetic, polygon area, aggregation, tolerance checks) should be done in ordinary code, not by asking an LLM to calculate.

### 3.6 Phase F — Result validation and evidence aggregation

Combine tool outputs into a typed result. Verify:

- The selected entity matches the user's target.
- The floor/room/document scope is correct.
- Units are known and consistently converted.
- Duplicates are not counted twice.
- Openings/exclusions are handled according to the question's wording.
- Geometry is valid and uses the correct coordinate system/scale.
- Evidence points to the actual source page, region, entity, or table cell.
- Conflicting sources are detected and reported rather than silently averaged.

When the evidence is insufficient or sources conflict, the system must say so, request clarification if appropriate, or return a qualified/abstaining answer. Never invent measurements, object locations, citations, or confidence values.

### 3.7 Phase G — Final answer and visualization

The final UI should display:

- Direct natural-language answer.
- Unit and calculation breakdown where relevant.
- Source document name and page/sheet.
- Highlighted original region(s), with an overlay generated from real coordinates.
- Supporting text, dimensions, table cells, IFC GlobalIds, or geometric entities.
- Brief explanation of the method and assumptions.
- Uncertainty/conflicts when relevant.

The evidence viewer must show the original drawing, not a generated illustration pretending to be the source.

---

## 4. Shared interfaces and data contracts

Before parallel implementation, define common Pydantic models (or equivalent typed schemas). Keep them in one shared module and version them. All agents must use these contracts.

At minimum define:

### 4.1 `DocumentRecord`

Fields should include:

- `document_id`
- `path` / storage URI
- `source`
- `format`
- `sha256` where available
- `canonical_group_id`
- `license` / credit metadata
- `page_count` or model metadata where applicable
- `capabilities[]`
- `ingestion_status`

### 4.2 `Capability`

Fields should include:

- `capability_type` (text, raster, vector, CAD, IFC, table, geometry, etc.)
- `available`
- `details`
- `limitations`
- `coordinate_system` where relevant

### 4.3 `QuestionSpec`

Fields should include:

- Original question.
- Requested operation.
- Entity/object concepts and aliases.
- Scope and constraints.
- Output unit/type.
- Ambiguities.

### 4.4 `ToolSpec` and `PlanStep`

Include typed names/arguments, dependencies, expected result type, timeout/budget, and required capability. The plan must be machine-validated before execution.

### 4.5 `EvidenceRef`

Include:

- Document ID/path.
- Page/sheet/view.
- Region or native geometry reference.
- Coordinate system and transform if applicable.
- Entity ID / IFC GlobalId / table cell / text span.
- Extracted content or computed fact.
- Extraction method and tool version.
- Confidence or quality metadata only when genuinely available.

### 4.6 `ToolResult` and `FinalAnswer`

Every result should include `status`, typed `value`, `unit`, `evidence[]`, warnings, assumptions, and error details if unsuccessful. A final answer must not be marked verified unless the validation layer has checked its evidence.

---

## 5. Example execution path

Question:

> What is the total area of the exterior walls on the second floor?

Expected high-level behavior:

1. Parse the question into operation `aggregate_area`, target `exterior_wall`, scope `floor_2`.
2. Resolve the referenced floor and available documents.
3. Inspect capabilities: IFC model? CAD geometry? vector PDF? scanned PDF?
4. Generate a plan based on the strongest available source.
5. If IFC is available and contains appropriate geometry/quantities, query wall elements and their floor relationships. Validate whether they are exterior walls.
6. Otherwise, retrieve CAD/vector geometry and reconstruct or identify wall boundaries. If only raster scans exist, use visual interpretation and scale/dimension evidence; report lower reliability where appropriate.
7. Determine gross vs net area. If the question does not specify and the difference materially changes the result, surface the assumption or ask for clarification.
8. Compute individual areas with deterministic code and aggregate.
9. Check duplicates, openings, units, scope, and evidence.
10. Return total area with each contributing wall linked to its source evidence and highlighted region.

This example illustrates the system; do not hardcode this exact path as the only workflow.

---

## 6. First demo scope: make one full loop work

Do not attempt to implement every format and every construction task before the peer submission.

The first demo must demonstrate the **architecture's dynamic behavior**, not merely one successful hardcoded question.

Build a narrow but real vertical slice:

1. Ingest at least one actual drawing/model from the workspace.
2. Extract and expose its capabilities.
3. Accept a natural-language question.
4. Produce a structured question specification.
5. Select a tool dynamically based on both the question and available source capabilities.
6. Execute real tool calls.
7. Validate the result.
8. Return an answer with real evidence and a working source viewer/highlight.

Ideally, demonstrate two questions requiring different routes, for example:

- One question answered using structured IFC or CAD/vector data.
- Another question answered using OCR/visual document analysis.

If the local data does not include a suitable example or the relevant dependency is unavailable, choose the closest real example and document the limitation. Do not fake the second route.

Prioritize one complete, trustworthy end-to-end flow over many disconnected placeholder features.

---

## 7. Suggested repository organization

Adapt this to the existing project rather than blindly imposing it:

```text
project/
├── README.md
├── questions.jsonl
├── data/
├── docs/
│   ├── DATA_AUDIT.md
│   ├── ARCHITECTURE.md
│   ├── DATA_SPLITS.md
│   └── DEMO_GUIDE.md
├── artifacts/
│   ├── data_splits/
│   ├── evaluation/
│   └── sample_outputs/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── schemas/
│   │   ├── ingestion/
│   │   ├── representations/
│   │   ├── tools/
│   │   ├── routing/
│   │   ├── execution/
│   │   ├── verification/
│   │   └── evidence/
│   └── tests/
├── frontend/
├── scripts/
│   ├── audit_dataset.py
│   ├── create_splits.py
│   ├── audit_leakage.py
│   └── evaluate.py
└── .env.example
```

Do not commit `.env`, API keys, tokens, private model credentials, or huge generated artifacts. Add appropriate `.gitignore` entries.

---

## 8. Suggested technologies (choose pragmatically)

Use what is already installed and what can be made reliable in the remaining hackathon time.

- Backend: Python + FastAPI.
- Schemas: Pydantic.
- PDF: PyMuPDF; pdfplumber where useful.
- Raster/image processing: OpenCV, Pillow.
- OCR: installed/available OCR engine such as PaddleOCR or Tesseract, selected after local environment audit.
- CAD: ezdxf for DXF; for DWG, determine whether a supported converter/library is available. Do not claim native DWG support if it is only converted or unsupported.
- Geometry: Shapely and explicit unit/coordinate handling.
- BIM: IfcOpenShell where installation and file compatibility permit.
- Tables: pdfplumber or a suitable table model depending on the document.
- Vision: existing pretrained model or approved vision API; record the actual model and version.
- LLM orchestration: custom typed planner first; LangGraph or a framework only if it accelerates implementation without hiding execution behavior.
- Storage/search: begin with SQLite/PostgreSQL and simple indexes. Add vector search only when it materially helps.
- Frontend: reuse the existing stack; otherwise a minimal React/Next.js or Streamlit demo is acceptable.

Do not add dependencies just because they are popular. Check install time, hardware availability, licences, and whether a real sample can be processed.

---

## 9. Agent team and ownership

You are the **lead/integration agent**. If the coding environment supports parallel agents, delegate after shared schemas and contracts are approved. Agents must inspect this master brief and the workspace before coding.

### Lead agent (you)

Own:

- Workspace and dataset audit.
- Shared architecture and contracts.
- Leakage-safe split design and evaluation harness.
- Integration and end-to-end tests.
- Technical decisions and final demo quality.
- Preventing conflicting edits to shared files.

### Agent A — Ingestion and document adapters

Own:

- Format detection and document registry.
- PDF/image/DXF/IFC adapters that are actually feasible.
- Source metadata, capabilities, coordinates, and ingestion tests.
- Preserve original files and licence metadata.

Deliverable: a real document can be ingested and its capabilities queried.

### Agent B — Specialized extraction tools

Own:

- OCR/text search, visual detection/segmentation, table extraction, CAD/vector geometry, IFC queries, deterministic calculations.
- Standard tool contracts and real evidence outputs.
- Unit tests on representative files.

Deliverable: a set of callable, tested tools that never fabricate outputs.

### Agent C — Question planner and execution engine

Own:

- Question interpretation.
- Tool registry and capability discovery.
- LLM-generated structured plans with schema validation.
- Sequential/parallel tool execution, retries, budgets and error handling.
- Result aggregation and verification.

Deliverable: at least two different question/capability combinations route to different real workflows.

### Agent D — Frontend and evidence viewer

Own:

- Upload/select document.
- Ask question and show execution status/plan.
- Display answer, unit, assumptions, warnings and evidence.
- Render original page and highlight source regions accurately.

Deliverable: a user can inspect the real source for the returned answer.

### Coordination rules

- The lead creates and owns shared schemas and API contracts before parallel implementation.
- Each agent owns separate modules/folders where possible.
- Do not let agents independently redefine schemas or duplicate the tool registry.
- Use separate branches/worktrees if available; otherwise assign non-overlapping files.
- Require each agent to report: files changed, commands/tests run, real capabilities completed, limitations, and integration requirements.
- Integrate incrementally. Do not wait until every agent claims to be finished.
- If an agent's model/API quota is exhausted, another agent/model may continue from the repository and this master brief. Keep progress in code, tests, and `docs/STATUS.md`, not only in chat history.
- Maintain `docs/STATUS.md`, `docs/DECISIONS.md`, and `docs/NEXT_AGENT_HANDOFF.md`. Update them after each major phase and before handing work to another model/agent. Record completed work, exact files changed, commands run, test results, known bugs, current branch/commit, pending decisions, and the next three concrete actions. Never rely on the previous model's chat memory as the only source of project context.

---

## 10. Evaluation harness requirements

Create a reproducible offline evaluator that accepts:

- A prediction file containing question ID, predicted value, unit, status, and evidence references.
- A protected reference file from one split.
- A split manifest.

The solver must never receive gold answers at inference time. Keep evaluator access separate from runtime services.

For each run, save:

- Git commit/hash or code version.
- Model/provider/version and relevant settings.
- Prompt/config version.
- Dataset split and seed.
- Prediction output.
- Aggregate and per-category metrics.
- Errors and abstentions.

Use the README scoring criteria exactly where possible: exact counts; <=2% relative error for areas, lengths, and volumes; free-form text answers. Make unit conversion explicit. Report unsupported categories honestly when the test set lacks independent groups for a category.

---

## 11. Quality, safety, and engineering requirements

- Never modify or delete original dataset files.
- Never expose reference answers to the runtime solver.
- Never report a placeholder, mock, or unimplemented tool as a working capability.
- Never fabricate evidence, source locations, measurements, confidence, or citations.
- Use safe, typed tool calls; do not execute arbitrary LLM-generated code or commands.
- Validate paths against the workspace root to prevent path traversal.
- Set file size, page count, image dimension, time, and model-call limits for the demo.
- Handle malformed, missing, unsupported, or corrupt files gracefully.
- Preserve units and coordinate systems explicitly.
- Log plans, tool inputs/outputs (excluding secrets and sensitive content), validation decisions, and errors.
- Respect per-source licences and attribution.
- Keep secrets in environment variables and provide `.env.example` with placeholder names only.
- Add unit tests for core logic and at least one end-to-end integration test using an actual local file.
- Pin or record key dependency/model versions.

---

## 12. Definition of done for peer submission

The first demo is ready only when all applicable points below are satisfied:

### Data and evaluation

- [ ] `README.md`, `questions.jsonl`, actual data tree and source licences audited.
- [ ] Dataset statistics reproduced by a script.
- [ ] Canonical group resolver implemented and documented.
- [ ] Train/validation/test splits created by logical drawing/building/project groups, not rows.
- [ ] Leakage audit passes; any unresolved near-duplicates are documented.
- [ ] Gold answers are isolated from runtime answering.
- [ ] Evaluator implements exact count and 2% measurement scoring.

### System

- [ ] Real document ingestion works.
- [ ] Document capability report is available.
- [ ] Question is parsed into a structured spec.
- [ ] Planner chooses from a real tool registry.
- [ ] At least two distinct workflows execute real tools (if suitable files are available).
- [ ] Tool results include provenance/evidence.
- [ ] Deterministic calculations and unit conversions are tested.
- [ ] Uncertainty, missing evidence and tool errors are handled honestly.

### User demo

- [ ] User can select/upload a real drawing or model.
- [ ] User can ask a natural-language question.
- [ ] UI shows the answer and unit.
- [ ] UI shows the source document/page/entity.
- [ ] Evidence highlight maps to the correct original source region.
- [ ] Demo can be run using documented commands from a clean environment.

### Documentation

- [ ] `docs/DATA_AUDIT.md`
- [ ] `docs/DATA_SPLITS.md`
- [ ] `docs/ARCHITECTURE.md`
- [ ] `docs/DEMO_GUIDE.md`
- [ ] `docs/STATUS.md` with completed, incomplete and known limitations.
- [ ] `docs/DECISIONS.md` and `docs/NEXT_AGENT_HANDOFF.md` maintained for agent/model handoffs.

Do not mark a checkbox complete based on an intention or stub. Run it and verify it.

---

## 13. Immediate execution order

Proceed in this order and keep the user informed through concise progress reports:

1. Audit repository, data files, questions, environment, and licences.
2. Create `docs/DATA_AUDIT.md` with reproducible statistics and missing-file report.
3. Implement group identity resolution, split creation, leakage audit, and evaluator tests. Do this before model experiments.
4. Define shared schemas, tool contracts, and repository structure.
5. Choose one or two representative real files and document why they were chosen.
6. Build the smallest real ingestion-to-evidence vertical slice.
7. Add the LLM planner and capability-based routing.
8. Add a second distinct workflow to demonstrate dynamic routing.
9. Build the simplest usable evidence viewer.
10. Run evaluation on validation data. Freeze the design before touching test results.
11. Run the final held-out test once the demo configuration is stable; report the metrics honestly.
12. Produce a concise demo script and a list of known limitations.

If time is short, reduce the breadth of supported tools, not the quality of the end-to-end evidence path. Do not spend the entire hackathon building infrastructure without a working demonstration.

---

## 14. Final instruction

Start by inspecting the workspace and writing the data audit. Do not ask the user to repeat information already present in the repository or this brief. Make reasonable, reversible engineering decisions and document them.

Your goal is to deliver a **working, honest, evidence-grounded, question-driven construction-document intelligence demo** whose routing can adapt to different questions and different available document representations.

The central differentiator is not any single OCR, CV, BIM, or LLM model. It is the reliable orchestration of those capabilities, combined with leakage-safe evaluation and traceable evidence.
