# STOA Junction 2026 — Complete Self-Contained Prompt for Every VS Code Coding Agent

> **This document is the complete project brief and execution prompt.** It contains the challenge context, dataset facts, leakage-safe evaluation requirements, architecture, interfaces, UI/demo requirements, agent responsibilities, testing rules, and handoff protocol. An agent must not depend on a previous chat or another Markdown specification to understand the project.
>
> **Use this same document for every coding LLM/agent.** Before pasting it into an agent, set the `AGENT ROLE` block below to the role assigned to that agent. The project lead and all specialist agents should work from the same definitions and contracts.

---

## AGENT ROLE — SET THIS BEFORE STARTING

Set exactly one role for the current coding agent:

```text
AGENT_ROLE = LEAD
# Or one of: INGESTION (Agent A), SPECIALIZED_TOOLS (Agent B), ROUTER (Agent C), FRONTEND (Agent D)

ASSIGNED_TASK = Follow the responsibilities for the selected role in Section 10.

WORK_MODE = Inspect the current workspace, preserve existing work, implement the assigned task, run tests, and update the continuity documents.
```

If the user gives you a more specific task, that task narrows your role; it does not override the shared architecture, data-safety, evidence, or evaluation requirements in this prompt.

### How every agent must begin

1. Read this entire prompt before coding.
2. Inspect the actual repository, existing code, current Git status, installed dependencies, and existing tests. Do not assume the repository is empty.
3. Read `README.md`, inspect `questions.jsonl`, and inspect the actual data tree and source-specific licence files. The prompt gives known dataset facts, but the current workspace audit is authoritative for what files are present locally.
4. Read `docs/STATUS.md`, `docs/DECISIONS.md`, and `docs/NEXT_AGENT_HANDOFF.md` if they exist. These are project continuity records, not substitutes for this prompt.
5. Confirm your assigned role and identify the exact modules/files you own. Do not duplicate another agent's work or make uncoordinated changes to shared contracts.
6. Implement real, testable functionality. Do not stop after proposing a plan.
7. Update the continuity documents before handing over.

### When switching models or token providers

Another LLM may take over at any time. Therefore, never keep essential decisions only in chat. Record them in code, tests, and the continuity documents. A replacement agent must be able to resume from the repository state and these files without access to prior conversation history.

---

## 0. Challenge context, mission, and product goal

You are contributing to the Junction 2026 challenge from **Stoa**. The challenge is to build a program that accurately answers natural-language questions about real construction drawings and Building Information Models (BIM). A strong answer must be correct and verifiable: the engineer should be able to see where the information came from in the original drawing/model and validate it quickly.

Construction documents are heterogeneous and technically dense. They may contain text, symbols, vector geometry, dimensions, tables/schedules, spatial relationships, and structured BIM objects. A general-purpose LLM or VLM alone may confuse annotations, misread small text, estimate measurements inaccurately, or miss relationships between elements.

### Product mission

Build a **general-purpose, question-driven multimodal construction-document intelligence system**. The system must accept different document representations, interpret a natural-language question, discover the capabilities of the available documents, dynamically plan and execute the most reliable tools, validate the result, and return an answer with traceable evidence.

The system must not be hardcoded for a single dataset source, file format, object category, building type, language, or question type. Use the question and the capabilities of the available source documents to decide how to solve each request.

The core product loop is:

**Documents + question → understand the request → discover document capabilities → plan tool calls → execute specialized tools → validate/aggregate evidence → answer with verifiable source references.**

### Mandatory peer-submission outcome

Deliver a **running, visually polished first demo**, not merely an architecture proposal, a command-line script, or a text-only chatbot. A user must be able to select/upload a real drawing or model, ask a question, see the system's execution route, receive an answer, and click evidence to inspect the corresponding region in the original drawing.

The central innovation is the reliable orchestration of document AI, computer vision, geometry, BIM, retrieval, and language models—not the use of one particular foundation model.

---

## Quick assignment lines for the five agents

Use the complete prompt unchanged for every agent, but set the role at the top differently for each one:

| Agent instance | Set `AGENT_ROLE` to | Primary ownership |
|---|---|---|
| Main/coordinator LLM | `LEAD` | Dataset splits, shared schemas, integration, evaluator, end-to-end demo |
| Specialist 1 | `INGESTION` | File adapters, parsing, rendering, metadata, capability discovery |
| Specialist 2 | `SPECIALIZED_TOOLS` | OCR, CV, CAD, IFC, geometry, evidence-producing tools |
| Specialist 3 | `ROUTER` | Question parsing, dynamic planning, tool registry/execution, verification flow |
| Specialist 4 | `FRONTEND` | Drawing viewer, overlays, evidence interactions, answer/execution UI |

If only one coding agent is available, set `AGENT_ROLE = LEAD`; it should implement the vertical slice itself and may create clear module boundaries for future agents.

**Important:** Do not give the same role to multiple agents working concurrently unless the user explicitly asks them to collaborate on that same module. Keep shared contracts owned by LEAD.

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

**Important annotation limitation:** `questions.jsonl` provides question-answer pairs and types/units; it does not, by itself, provide bounding boxes, masks, symbol locations, or segmentation labels. The QA answers may support supervised QA/prompt/router experiments on the training split, but they are not CV localization labels. Do not train or report a detector/segmenter as supervised on these QA rows unless you find separate verified annotations. Inspect source files for additional annotations. If no localization labels exist, use pretrained models, manual annotation of a small subset, weak supervision with explicit caveats, or focus on tool routing and deterministic extraction.

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

The final UI is a first-class product deliverable, not a debug page. It should display:

- Direct natural-language answer and unit.
- Calculation breakdown where relevant.
- Source document name and page/sheet/view.
- The original drawing/model view with overlays generated from actual extraction results.
- Supporting text, dimensions, table cells, IFC GlobalIds, geometric entities, detected objects, and segmentation regions.
- Brief explanation of the method, assumptions, and limitations.
- Uncertainty/conflicts when relevant.

The evidence viewer must show the original drawing, not a generated illustration pretending to be the source. The user must be able to toggle overlays and inspect the unmodified source. Never label a detection box as a segmentation mask or show illustrative/mock regions as model predictions.

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

### 4.5.1 `EvidenceOverlay` (required for the drawing viewer)

Define a typed overlay contract so the backend and frontend agree on exactly what can be drawn over the source. Include at least:

- `overlay_id`, `document_id`, `page_or_view_id`.
- `overlay_type`: `instance_mask`, `semantic_mask`, `polygon`, `polyline`, `bounding_box`, `point`, `dimension`, `text_region`, or `ifc_selection`.
- `geometry`: mask reference or polygon/polyline/box/point coordinates.
- `coordinate_system`: explicit native/page/image coordinate system.
- `transform`: mapping to the displayed page/image coordinates when required.
- `label`, `entity_id`, and optional `class_name`.
- `source_tool`, `model_name/version`, and `is_model_output`.
- `evidence_refs[]` linking the overlay to the claim/result it supports.
- Optional confidence/quality only if produced by the actual tool and meaningful.

Support masks, vector outlines, and bounding boxes as different overlay types. The UI must render them differently and label them honestly. Large masks should be stored as image assets or compact geometry references, not huge JSON arrays.

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

### 6.1 Mandatory demo UI: drawing canvas, segmentation, and evidence

The peer-submission demo must be a visually understandable application. A text-only chatbot or API response is not sufficient. The UI must make the core value obvious: the engineer asks a question, the system reasons over a real drawing, and the exact supporting evidence is visible on that drawing.

#### Recommended screen layout

Build a clean desktop-first interface with three cooperating areas (responsive on smaller screens):

1. **Document panel (left):** uploaded/selected files, format, page count where available, ingestion status, detected capabilities, and document/page selector.
2. **Drawing canvas (center):** render the actual selected page or view at useful resolution. Support zoom, pan, fit-to-screen, page navigation, and original-versus-overlay viewing.
3. **Question and answer panel (right):** natural-language question input, answer, unit, calculation/assumptions, warnings, evidence cards, and execution trace.

The layout can differ if the existing frontend framework suggests a better design, but all required functions below must remain discoverable.

#### Drawing visualization and segmentation overlays

The central canvas must show the real source drawing or a faithful rendering of it. Where a real extraction tool produces results, display them as aligned overlays:

- Instance segmentation masks for individual detected objects, when the selected model genuinely outputs masks.
- Semantic segmentation masks for classes/regions, when genuinely available.
- Polygon/polyline overlays for extracted vector/CAD geometry or reconstructed room/wall boundaries.
- Bounding boxes for object detectors that output boxes only. Do not call these segmentation.
- OCR text boxes or annotation regions.
- Dimension lines/measurement geometry where extracted.
- IFC-selected elements or their projected/highlighted representation when a valid view/coordinate mapping exists.

Provide a compact legend and layer controls so users can toggle overlay categories (e.g. rooms, walls, doors/windows, detected objects, OCR, dimensions, evidence highlights). Use visibly different styling for masks, outlines, boxes, text regions, and the currently selected evidence. Include an opacity control if practical. Users must be able to turn all overlays off to inspect the untouched original.

If segmentation is not implemented for a given file, do not fabricate colored regions. Show the actual available output (for example OCR boxes, vector lines, or detector boxes), label it correctly, and state which analysis is unavailable. A static pre-painted sample can be used only if clearly marked as a static example, never as live model output.

#### Evidence interaction (essential)

- Every evidence card must identify the source document and page/sheet/view.
- Evidence must include a meaningful reference: highlighted region, entity, table cell, text span, dimension, or IFC GlobalId.
- Clicking an evidence card must navigate to the correct document/page, zoom to the referenced region, and highlight it on the canvas.
- Selecting an overlay/object on the canvas should open its details and associated evidence in the side panel.
- For calculated answers, show the contributing elements and calculation breakdown; selecting a contributor should highlight that element.
- Provide a clear way to return to the full-page view and deselect evidence.
- Preserve the source coordinate system and transformations. The highlight must line up with the actual source at different zoom levels and page sizes.
- If a tool can provide only a page-level citation and no precise region, show the page citation honestly without inventing a highlight.

#### Question, answer, and reasoning panel

Show:

- Question input and submit action.
- Answer with normalized unit and status (e.g. supported, partially supported, uncertain, unable to answer).
- Short explanation of what was retrieved/calculated; avoid exposing hidden chain-of-thought. Show concise execution steps and factual tool outcomes instead.
- Assumptions, unit conversions, exclusions, and warnings where they materially affect the answer.
- Evidence cards with source/page, evidence type, extracted value/text, and a “Show on drawing” interaction.
- A visible abstention or clarification state when evidence is insufficient.

Do not display an uncalibrated numeric confidence as if it were a probability. If confidence is not meaningful or available, show evidence status/quality notes instead.

#### Execution trace for demonstrating dynamic routing

Include an expandable, user-friendly execution trace that makes the system's routing observable without exposing internal chain-of-thought. Show steps such as:

- Parsed request (operation, entity, scope, requested unit).
- Selected document capabilities.
- Planned tool names and their status (queued/running/succeeded/failed/skipped).
- Short tool summaries and returned evidence counts.
- Validation decisions, unit conversions, and any source conflicts.

Do not show secrets, raw credentials, private prompts, hidden model reasoning, or excessive low-level logs. The purpose is to demonstrate which tools ran and what evidence they returned.

#### Minimum visual demo workflow

The demo must support this sequence:

1. Open the app and choose or upload a real drawing from the workspace.
2. Show the document in the drawing canvas.
3. Display any actual extracted segmentation/detection/vector/OCR overlays available for that sample, with layer toggles and a legend.
4. Ask a natural-language question about the selected document.
5. Show the router's concise execution trace.
6. Display the answer and its evidence cards.
7. Click an evidence card and see the corresponding region highlighted and zoomed in the original drawing.
8. Toggle overlays off and compare against the unmodified source.

Prepare at least one polished demo scenario with a real local sample and a known reference answer, but keep reference-answer access inside the evaluator only. The live solver must answer from the drawing, not read the gold answer. If the chosen sample has a reference answer in `questions.jsonl`, make sure the runtime path cannot access that field.

#### Frontend implementation notes

- Reuse an existing frontend if present; otherwise use the simplest reliable stack available (React/Next.js is appropriate, but not mandatory).
- PDF.js or an equivalent viewer can render PDF pages. For image pages, use an image canvas. For vector/CAD/IFC, render only supported geometry and identify the representation accurately.
- Keep the drawing image/source and overlay layer separate (e.g. stacked canvas/SVG layers) so overlays can be toggled without altering the source.
- Use a single canonical viewer coordinate space and explicit transforms from PDF points, image pixels, CAD units, or projected IFC geometry.
- Avoid loading the full 10 GB dataset into the browser. The demo should select a small file and load/render only the needed page, view, and evidence assets.
- Make loading, processing, no-evidence, unsupported-format, and tool-failure states visually clear.
- Add a short `docs/DEMO_GUIDE.md` with exact commands and the demo question(s), sample file(s), expected live behavior, and limitations.

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

For runtime LLM/VLM calls, use a provider adapter and configuration selected through environment variables where feasible. The application should not depend on the coding agent or coding-model provider used to develop it. Never hardcode model credentials or vendor-specific response assumptions into core tool schemas.

---

## 9. Shared team rules and role ownership

The project may be developed by several VS Code agents and several different LLM providers. All agents must use the same architecture, schemas, evaluation rules, and evidence contract defined in this prompt.

### 9.1 Role selection

The `AGENT_ROLE` value at the top of this prompt determines the current agent's responsibility. Do not silently assume all roles. If the role is missing or ambiguous, inspect the continuity documents and ask the user for the one missing assignment before making overlapping changes. If the user explicitly asks you to act as lead, use the LEAD role.

### 9.2 LEAD — architecture, data, integration, demo ownership

Own:

- Workspace and dataset audit.
- Reproducible group-aware train/validation/test splitting and leakage audit.
- Evaluation harness and protected gold-answer flow.
- Shared Pydantic/JSON schemas, tool registry interface, and API contracts.
- Architecture decisions and coordination among agents.
- Integration, end-to-end tests, demo readiness, and final quality.
- Preventing conflicting edits to shared files.
- Continuity documentation and handoffs.

Deliverable: an integrated running application, reproducible data/evaluation pipeline, and an honest report of capabilities and limitations.

### 9.3 INGESTION — Agent A: document processing and adapters

Own:

- Format detection and document registry.
- PDF and image processing.
- DXF/CAD and IFC adapters where feasible in the current environment.
- SVG parsing where feasible.
- OCR/text/table extraction adapters or integration points.
- File hashes, source metadata, licence metadata, capability reports, and coordinate systems.
- Rendering pages/views and creating evidence-ready page assets.

Deliverable: a real document can be ingested; the system can query its available capabilities; extracted records retain source provenance and coordinate information.

### 9.4 SPECIALIZED_TOOLS — Agent B: CV, OCR, geometry, CAD, BIM tools

Own:

- Registered tool implementations for object detection, segmentation where genuinely supported, OCR, annotation search, table extraction, CAD/vector geometry, IFC queries, spatial relationships, and deterministic quantity calculations.
- Standard tool inputs/outputs compatible with shared schemas.
- Evidence references and overlay data produced by each tool.
- Unit tests on actual representative documents.

Deliverable: callable, tested tools that return typed results, honest status/errors, and source evidence. Do not return fabricated outputs or claim support for unavailable formats/models.

### 9.5 ROUTER — Agent C: question interpretation, planning, and execution

Own:

- Natural-language question interpretation into a structured `QuestionSpec`.
- Capability discovery from documents and tool registry.
- Dynamic tool selection based on question requirements AND source capabilities.
- Typed multi-step execution plans with dependencies, sequential/parallel calls, timeouts, and budgets.
- Tool execution, result aggregation, verification orchestration, and graceful abstention.
- Provider-agnostic LLM adapter/configuration where practical.

Deliverable: natural-language questions can produce validated plans and execute at least two genuinely different tool workflows depending on available document representations.

### 9.6 FRONTEND — Agent D: visual product, drawing viewer, and evidence UX

Own:

- A polished desktop-first application with document panel, central drawing canvas, and question/answer/evidence panel.
- File selection/upload, document status, page navigation, zoom, pan, and fit-to-screen.
- Rendering the actual source drawing and overlays from the shared `EvidenceOverlay` schema.
- Correctly distinguishing segmentation masks, vector polygons/polylines, bounding boxes, OCR regions, dimension overlays, and IFC selections.
- Overlay legend, visibility toggles, opacity controls where practical, and clean original-versus-overlay inspection.
- Clickable evidence cards that navigate to and highlight/zoom the exact supported page/region/entity.
- Execution trace visualization showing tool steps/statuses/evidence counts and validation summaries without exposing hidden chain-of-thought.
- Clear loading, unsupported, uncertain, no-evidence, and error states.

Deliverable: a user can inspect the actual drawing, ask a question, see real analysis overlays where available, inspect the tools used, and click evidence to verify the answer on the source.

### 9.7 Integration and collaboration rules

- LEAD creates and owns shared schemas/API contracts before parallel implementation.
- Specialist agents must not redefine shared schemas independently. Propose changes to LEAD and update all consumers together.
- Each agent works in assigned modules/folders or a separate branch/worktree where available. Avoid simultaneous edits to the same files.
- Before coding, check the current status and files changed by other agents.
- Integrate continuously; do not wait until every agent says it is finished.
- Every handoff must state: files changed, features actually implemented, commands/tests run and results, known limitations/bugs, schema/API changes, and next required integration step.
- If an agent/model runs out of tokens or is replaced, the next agent reads the continuity files and resumes; it must not rebuild functioning modules without justification.

### 9.8 Continuity documents — mandatory for every role

Maintain these files:

- `docs/STATUS.md`: current working features, incomplete features, bugs, how to run, last tests and result.
- `docs/DECISIONS.md`: dated architectural decisions, alternatives considered, rationale, schema/API changes, and migration notes.
- `docs/NEXT_AGENT_HANDOFF.md`: exact current state, changed files, commands, tests, known issues, required environment variables (names only, never values), and the next three concrete tasks.

The LEAD ensures these files are coherent. Every specialist agent updates the relevant sections before handoff. Never store secrets or API tokens in these documents.

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

### User demo and visual UI

- [ ] User can select/upload a real drawing or model.
- [ ] User can ask a natural-language question.
- [ ] UI has a usable document panel, central drawing canvas, and answer/evidence panel (or an equally clear layout).
- [ ] UI renders the original drawing at readable resolution with zoom, pan, and page navigation.
- [ ] UI displays actual analysis overlays available for the selected sample (segmentation masks where genuinely produced; otherwise correctly labelled boxes, vector outlines, OCR regions, or dimensions).
- [ ] Overlay legend and layer toggles work; user can inspect the original without overlays.
- [ ] UI shows the answer and unit, assumptions, warnings, and calculation breakdown where relevant.
- [ ] UI shows source document/page/entity and clickable evidence cards.
- [ ] Clicking evidence navigates/zooms to the correct region and highlights it accurately in the original source.
- [ ] Selecting an overlay/object exposes its associated evidence/details where implemented.
- [ ] UI exposes a concise execution trace showing selected tools, execution statuses, and evidence/validation summaries (not hidden chain-of-thought).
- [ ] Unsupported, uncertain, no-evidence, loading, and error states are handled honestly.
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
9. Build the visual demo UI: original drawing canvas, honest segmentation/detection/vector/OCR overlays, layer toggles, answer panel, clickable evidence highlights, and concise execution trace.
10. Run evaluation on validation data. Freeze the design before touching test results.
11. Run the final held-out test once the demo configuration is stable; report the metrics honestly.
12. Produce a concise demo script, screenshots, and a list of known limitations.

If time is short, reduce the breadth of supported tools, not the quality of the end-to-end evidence path. Do not spend the entire hackathon building infrastructure without a working demonstration.

---

## 14. Final instruction — execute, don't just describe

Your assigned role is specified at the top of this prompt. Carry out that role while respecting every shared project requirement in this document.

Before making changes, inspect the current workspace, Git status, existing implementation, tests, and continuity documents. Do not ask the user to repeat details already present in the repository or this prompt. Make reasonable, reversible engineering decisions and record important choices.

**Do not stop after proposing an architecture or writing a plan. Implement real functionality, run it, test it against actual local files, fix failures where feasible, and report what works versus what remains incomplete.**

The overall project goal is a **working, honest, evidence-grounded, question-driven construction-document intelligence demo** whose routing adapts to different questions and different document representations. The user-facing demonstration must include the real drawing viewer and clickable evidence described in this prompt. The data pipeline must include reproducible leakage-safe train/validation/test splits and a protected evaluator. The system must never fabricate analysis results, source locations, model outputs, or confidence values.

When you finish a task, provide a concise handoff with:

1. What was implemented (only verified capabilities).
2. Files created or modified.
3. Exact commands to run the relevant component/demo.
4. Tests executed and their results.
5. Known limitations, failures, and unsupported cases.
6. Any schema/API changes requiring integration.
7. The next three concrete actions.

Update `docs/STATUS.md`, `docs/DECISIONS.md`, and `docs/NEXT_AGENT_HANDOFF.md` before handing off.
