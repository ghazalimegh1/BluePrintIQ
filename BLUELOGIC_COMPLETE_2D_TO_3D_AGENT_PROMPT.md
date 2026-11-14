# BLUELOGIC — Complete 2D-to-3D Construction Intelligence Build Specification

> **Instruction to the coding agent:** You own the entire project end-to-end. Read this document completely, inspect the existing repository, then implement the working application. Do not stop after proposing architecture. Do not ask the user to assign separate roles. You are responsible for integration, implementation, testing, UI, and delivery.

---

## 0. Mission

Build **BLUELOGIC**, a multimodal construction and architectural intelligence application that turns heterogeneous technical documents into an evidence-linked, queryable spatial representation of a building.

A user uploads construction drawings and/or existing BIM models, asks a question in natural language, and receives an answer grounded in the source documents and building geometry. For 2D inputs, the system reconstructs as much meaningful 3D geometry as the available drawings support. For existing 3D/BIM inputs, it preserves and uses the native model rather than unnecessarily rebuilding it. The application then answers questions by dynamically selecting document retrieval, computer vision, geometric, spatial, and BIM tools.

The central product idea is:

**Transform 2D construction information into a structured, evidence-linked 3D building representation, then use that representation—together with the original documents—to answer engineering questions accurately and verifiably.**

This is not merely a chatbot, a PDF viewer, or a visually plausible 3D generator. The 3D representation must be geometrically meaningful, semantically structured, traceable to source evidence, and honest about missing or inferred information.

### Core user journey

1. User uploads one or more construction documents and/or BIM models.
2. System detects every file format and chooses a suitable parser.
3. System extracts text, tables, symbols, dimensions, geometry, BIM entities, and visual elements.
4. System links related sheets, levels, models, and elements where evidence supports the relationship.
5. System reconstructs 2D drawings into 3D where sufficient geometric information exists; existing 3D models are imported and preserved.
6. System creates a unified spatial scene and evidence index.
7. User asks a natural-language question.
8. Groq LLM interprets the question and plans which tools to call.
9. The backend executes validated tools, often combining multiple tools.
10. Deterministic geometry/BIM operations calculate quantities where possible.
11. System verifies the result and records provenance.
12. UI shows the answer alongside an interactive 3D model and the original drawing regions that support it.

### Non-negotiable product principles

- **3D is the shared spatial intelligence layer, not a forced conversion step.** Some questions are best answered directly from a schedule, annotation, PDF, or native IFC property. Use the best evidence source.
- **Do not invent engineering facts.** A single floor plan does not reveal every height, material, depth, or concealed element. Unknown information must remain unknown or be explicitly marked as inferred.
- **Preserve original inputs.** Never overwrite or destructively modify source drawings or models.
- **Every answer must be traceable.** Store source file, page/sheet, source coordinates, entity IDs, extraction method, and confidence/provenance.
- **Use AI for perception, interpretation, and planning; use deterministic algorithms for exact geometry and arithmetic whenever possible.**
- **Models are tools, not magic.** Do not claim a model has been installed, run, or validated unless it actually has.
- **Build a working end-to-end demo first, then expand capabilities.**
- **Use a polished product UI.** Do not deliver a generic admin dashboard or a plain chat page.

---

## 1. Inspect the existing repository before changing it

Start by inspecting the entire project structure, existing source code, dependencies, scripts, environment configuration, tests, and Git status. Preserve working code. Do not start a parallel replacement project or overwrite existing work without understanding it.

The workspace is expected to contain some or all of:

- `README.md`
- `questions.jsonl`
- `data/` with construction drawings and models
- existing frontend/backend source code
- project documentation and configuration

Read the actual `README.md` and inspect actual sample files. Do not rely only on filenames or earlier descriptions. The dataset documentation describes multiple formats, multiple languages, question types (`count`, `area`, `length`, `volume`, `text`, `other`), and sources such as CubiCasa5K, Swiss dwellings, Opening Design, IFC models, IFC Bench, and others. The data README explains that files with the same basename but different extensions may be alternate representations of the same drawing, and that certain IFC-model floor-plan PDFs were rendered from corresponding IFC models. Confirm these relationships from the actual files.

### Dataset handling rules

1. Never modify original dataset files.
2. Build a dataset inventory and document supported/unsupported formats.
3. Sample intelligently; do not attempt to load or process the entire dataset during initial development.
4. Preserve each source's licence and attribution. Read applicable `data/<source>/LICENSE.md` files before redistributing, displaying, or adapting data. Respect NC, SA, ND, and per-file licence terms.
5. Treat `questions.jsonl` as evaluation/training metadata, not as runtime knowledge available to the answering system.
6. Never expose validation or test reference answers to the runtime question-answering pipeline.
7. Do not assume quantity-takeoff question answers provide object detection or segmentation labels. If the provided subset contains images without box/mask annotations, it is not a supervised CV dataset.

### Required data audit outputs

Create:

- `docs/DATA_AUDIT.md` — file counts, formats, sources, languages if discoverable, sample records, missing/unsupported cases, licence notes, and relationships between alternate formats/models and drawings.
- `data/splits/manifest.jsonl` — grouped train/validation/test assignment for question records and drawing identities.
- `docs/EVALUATION.md` — metrics, split policy, leakage prevention, and how to reproduce evaluation.

### Leakage-safe split

Create a **grouped 70% train / 15% validation / 15% test split** as an initial default, but implement it by logical drawing/building/project identity—not by question row. Use a stable seed and save the manifest.

Group together:

- same drawing represented as PDF, DXF, DWG, SVG, PNG, or another extension;
- pages/sheets belonging to the same drawing set or project where identifiable;
- an IFC model and floor-plan PDFs rendered from that model;
- duplicate or near-duplicate representations that would reveal the same geometry;
- question rows referring to the same underlying drawing.

If a source/project is the strongest available grouping unit, prefer grouping at that level. Report group counts and possible leakage risks. Do not silently fall back to random question-row splitting.

For the initial demo, it is acceptable to use a small number of real files for smoke tests. Keep benchmark evaluation splits separate. Add separate manually annotated samples for CV evaluation if object-detection or segmentation metrics are desired. Human annotations must be versioned and their provenance documented.

### Benchmark evaluation rules

Follow the dataset README's scoring rules exactly where applicable:

- counts: exact match;
- areas, lengths, and volumes: within the specified 2% tolerance;
- text: free-form evaluation, with clear normalization and manual inspection for ambiguous cases.

Also report evidence localization quality, unsupported-answer rate, tool-routing success, latency, and failure rate. Do not optimize only on aggregate answer accuracy.

---

## 2. Target system architecture

Build the system as modular services/adapters with explicit interfaces. Keep the initial implementation simple enough to run locally, but do not create tight coupling that prevents future model replacement.

### High-level architecture

```text
                   ┌────────────────────────────────────┐
                   │      React + Three.js frontend      │
                   │ upload · 2D viewer · 3D viewer      │
                   │ question panel · evidence inspector │
                   └─────────────────┬──────────────────┘
                                     │ HTTP / SSE
                   ┌─────────────────▼──────────────────┐
                   │            FastAPI backend          │
                   └─────────────────┬──────────────────┘
                                     │
            ┌────────────────────────▼────────────────────────┐
            │             Document ingestion layer            │
            │ format detection · parsing · sheet metadata     │
            └────────────────────────┬────────────────────────┘
                                     │
            ┌────────────────────────▼────────────────────────┐
            │          Multimodal extraction adapters          │
            │ OCR · plan parsing · detection · segmentation    │
            │ CAD geometry · tables · IFC/BIM · vector PDFs     │
            └────────────────────────┬────────────────────────┘
                                     │
            ┌────────────────────────▼────────────────────────┐
            │        Spatial / evidence representation         │
            │ 2D geometry · 3D scene · entity graph · sources   │
            └────────────────────────┬────────────────────────┘
                                     │
    User question                      │
        │                              │
        ▼                              │
   ┌───────────────────────────────────▼──────────────────────┐
   │ Groq LLM question interpreter + execution planner         │
   │ creates a validated plan using registered tools           │
   └───────────────────────────────────┬──────────────────────┘
                                       │
   ┌───────────────────────────────────▼──────────────────────┐
   │ Tool execution engine                                     │
   │ text search · OCR · vision · geometry · IFC · graph       │
   └───────────────────────────────────┬──────────────────────┘
                                       │
   ┌───────────────────────────────────▼──────────────────────┐
   │ Evidence aggregation + deterministic verification         │
   └───────────────────────────────────┬──────────────────────┘
                                       │
   ┌───────────────────────────────────▼──────────────────────┐
   │ Answer + highlighted 2D source + highlighted 3D elements  │
   └──────────────────────────────────────────────────────────┘
```

### Main backend modules

Use the existing stack if already established. Otherwise, the recommended starting point is:

- Python 3.11+ (or compatible project version)
- FastAPI + Pydantic for API and schemas
- React + TypeScript for frontend
- Three.js through `@react-three/fiber` and `@react-three/drei`
- PyMuPDF for PDF reading/rendering and coordinate-aware page processing
- ezdxf for DXF parsing/writing
- a configurable DWG conversion adapter (ODA File Converter or another legally/technically available converter; do not assume a proprietary converter is installed)
- IfcOpenShell for IFC parsing and geometry
- OpenCV for image processing
- Shapely for 2D computational geometry
- Open3D and/or Trimesh for 3D geometry processing
- PaddleOCR for OCR
- PostgreSQL or SQLite for metadata and evidence depending on the existing environment; use pgvector only if vector search is genuinely needed
- local file storage for originals and derived artifacts during the demo

Do not add a graph database just for fashion. A relational schema with explicit entity relationships is sufficient initially. Introduce Neo4j or another graph store only if a tested use case justifies it.

---

## 3. Model and specialist-tool stack

The system must use a **replaceable specialist-model layer**. Do not put all responsibilities into Groq. Groq is used for natural-language question interpretation, plan generation, and tool routing; the specialist tools do the actual extraction, detection, segmentation, reconstruction, and calculation.

### 3.1 Required core vision/document models

#### A. Grounding DINO — open-vocabulary object detection

- Candidate model/checkpoint: `IDEA-Research/grounding-dino-tiny`.
- Purpose: locate objects from text prompts such as `window`, `door`, `column`, `stair`, or other supported classes.
- Output: bounding boxes, label/prompt, confidence, source image/page coordinates.
- Use it for candidate localization, not for exact measurements.
- Implement prompt templates, confidence thresholds, and deduplication.
- Verify checkpoint availability, license, dependency compatibility, and inference on CPU/GPU before integration.

#### B. SAM 2 — promptable segmentation

- Candidate checkpoint: SAM 2.1 Hiera Small (verify official repository/checkpoint identifier and license before downloading).
- Purpose: create pixel masks from detection boxes, points, or user prompts.
- Output: mask, bounding box, area in pixels, source page and prompt/detection linkage.
- SAM 2 is a segmentation model, not a semantic object classifier. Grounding DINO or a floor-plan parser should identify candidate objects; SAM 2 can segment them.
- Preserve transformations from resized/tilled image coordinates back to original page coordinates.

#### C. Floor-plan semantic parsing — CubiCasa5K model

- Investigate the official CubiCasa5K multi-task floor-plan parsing model and available pretrained checkpoint.
- Purpose: parse common floor-plan elements, room regions, walls, doors, windows, and symbols where the model supports them.
- The bundled CubiCasa subset is not assumed to include detection/segmentation labels. Do not train supervised segmentation on unlabeled images.
- First use the available pretrained checkpoint for inference and evaluate its real performance on this project's drawings.
- Check whether the model's label taxonomy matches the required classes; create an explicit class mapping and do not pretend unsupported classes are detected.

#### D. OCR — PaddleOCR

- Use PaddleOCR as the primary local OCR candidate.
- Purpose: read room names, dimensions, labels, callouts, title blocks, schedule text, and engineering annotations.
- Store recognized text with polygons/bounding boxes, page index, OCR confidence, language if identified, and coordinate transforms.
- Support rotation and high-resolution crops. Do not run OCR only on a low-resolution thumbnail.
- Consider table extraction separately; OCR text alone is not a structured schedule parser.

### 3.2 Floor-plan reconstruction research candidate

#### E. RoomFormer — floor-plan structural reconstruction

- Investigate the RoomFormer research implementation and available pretrained weights.
- Purpose: candidate method for reconstructing room polygons and floor-plan topology from raster floor plans.
- Treat it as an experimental parser, not a guaranteed production dependency.
- Compare it with CubiCasa5K and geometric/vector extraction on actual examples. Integrate only if it produces useful, testable outputs and its dependency/license constraints are acceptable.

### 3.3 Vision-language reasoning model

#### F. Gemini image-capable API or local Qwen-VL adapter

- Provide a provider interface for an image-capable model to inspect ambiguous regions, interpret unusual symbols, or help resolve semantic uncertainty.
- Preferred hosted experiment: a currently available Gemini image-capable model through the official Google GenAI SDK, configured with `GEMINI_API_KEY` and a configurable `GEMINI_MODEL`.
- The user prefers free API usage. Before enabling the hosted adapter, verify that the selected model is actually available under the account's free tier and report quotas/limitations. Never silently use a paid model or incur paid usage without explicit authorization.
- Optional local candidate: `Qwen/Qwen2.5-VL-7B-Instruct` if local hardware can run it. Do not download or run a 7B model blindly; first inspect available GPU VRAM/RAM and test quantized/optimized options.
- VLM output is semantic assistance, not authoritative geometry. It must cite image crop/page coordinates and cannot invent dimensions.
- If no hosted/free or local VLM is configured, the application must still function using OCR, detection, segmentation, geometry, IFC, and text retrieval. Display a clear capability status.

### 3.4 Models/tools for 2D-to-3D

There is **no single general-purpose image-to-3D model that can reliably convert arbitrary construction blueprints into engineering-accurate BIM**. Do not treat generic image-to-3D output as validated construction geometry.

Use a structured reconstruction pipeline:

- CubiCasa5K parser and/or RoomFormer: semantic floor-plan interpretation and room topology.
- Grounding DINO: localize requested object classes in raster sheets.
- SAM 2: segment selected detected regions.
- PaddleOCR: read dimensions, level labels, room names and construction notes.
- OpenCV: image rectification, line extraction, contour processing, scale and raster analysis.
- Shapely: room polygons, wall footprints, intersections, boundaries and 2D calculations.
- ezdxf: native CAD entities and geometric coordinates when DXF is available.
- PyMuPDF: vector paths/text and page-coordinate extraction from PDF.
- IfcOpenShell: preserve and inspect existing IFC models and their properties/relationships.
- Open3D and/or Trimesh: 3D meshes, geometry checks, alignment, intersections and export preparation.
- Procedural geometric construction: extrude known wall footprints, place openings/columns/slabs, create storey geometry, and construct 3D objects using explicit dimensions/constraints.

Generic image-to-3D research models such as single-image mesh generators may be evaluated for visual previews only. They must not be used as the source of truth for dimensions, quantities, structural relationships, or safety-relevant construction facts.

### 3.5 Model registry and availability checks

Create `backend/app/vision/model_registry.py` (or equivalent) with:

- model name and version/checkpoint;
- task/capability;
- local or hosted provider;
- required dependencies;
- expected device (CPU/CUDA);
- model license/source;
- installed/downloaded/available status;
- supported input/output types;
- health-check result.

At application startup, do not fail the entire app because an optional heavy model is missing. Report capability status and disable only the affected tool. For mandatory models needed by the demo, provide a clear setup command and test.

Do not fabricate model outputs, confidence scores, masks, or status messages.

---

## 4. Format detection and ingestion

Implement a robust upload and format-detection stage before processing.

### Supported input families

- PDF (vector or raster/scanned)
- DWG
- DXF
- IFC
- SVG
- PNG/JPEG

Detect type using extension plus file signature/content checks. Do not trust the extension alone. Reject unsupported/corrupt files with a useful message. Apply file-size limits and safe temporary storage.

### Format-specific adapters

#### PDF

- Enumerate pages and metadata.
- Extract embedded text and vector paths when available.
- Render page images at an appropriate DPI for visual/OCR processing.
- Detect likely drawing sheets, detail pages, schedules, title blocks, dimensions and annotations.
- Preserve page number, page dimensions, crop box, rotation, and mapping between rendered pixels and PDF coordinates.

#### DWG/DXF

- Parse DXF natively using ezdxf.
- For DWG, inspect available converter options and implement a converter adapter. Prefer an installed and license-compatible tool; report conversion as unavailable if none exists.
- Preserve layers, blocks, entities, units, coordinates, and source handles when possible.
- Avoid flattening CAD data into a screenshot when vector geometry is available.

#### IFC

- Parse IFC natively with IfcOpenShell.
- Extract spatial hierarchy, storeys, spaces, walls, slabs, doors, windows, beams, columns, openings, materials, property sets, quantity sets, placements, representations, relationships and GlobalIds where present.
- Preserve native IFC geometry and semantic properties.
- Generate a web-friendly GLB/glTF preview or equivalent without losing the underlying IFC element mapping.

#### SVG

- Extract vector paths, shapes, text and transforms.
- Preserve original coordinate system and transformation matrices.

#### PNG/JPEG

- Estimate image orientation/skew and rectify only in derived copies.
- Preserve mapping between processed image pixels and original image coordinates.
- Use tiled/high-resolution inference for large sheets.

### Document grouping and sheet linking

Create document/sheet records with fields such as project, building, discipline, floor/storey, sheet number, revision, title, scale, units, source, language, and linked files. Populate only when extracted or supplied; unknown values remain null.

Link sheets using evidence such as title block metadata, matching project identifiers, sheet references, filenames, shared coordinate grids, matching dimensions, or IFC-model associations. Store why a link was established and confidence. Do not blindly link by filename alone.

---

## 5. The 2D-to-3D reconstruction pipeline

This is the main differentiator. Implement it as a staged, confidence-aware process.

### Stage 1 — Normalize coordinate systems

- Establish source coordinate systems for each drawing/sheet.
- Read page size, raster dimensions, vector coordinates, CAD units, scale annotations, and IFC placements.
- Create transforms between source coordinates, normalized 2D plan coordinates, building/world coordinates, and viewer coordinates.
- Store transforms explicitly and test them with known points/dimensions.
- Never mix pixel, PDF point, CAD unit, and world coordinates without an explicit transform.

### Stage 2 — Parse and classify drawing content

- Identify plan, elevation, section, detail, schedule, site plan, and unknown sheet types.
- Use text/title-block cues and visual/layout features.
- Extract room labels, grid labels, dimensions, levels, scales, section markers, elevation markers, and references to other sheets.
- Run vector extraction first where available; use raster AI where needed.

### Stage 3 — Build 2D semantic geometry

Identify and represent:

- room/space polygons;
- wall footprints or wall centerlines and thicknesses;
- columns and structural supports;
- doors and windows as openings/objects;
- stairs, ramps, shafts, cores, slabs, and other classes when supported;
- dimension lines and values;
- grid axes and level markers;
- annotations and schedule entries.

For each element, store class, geometry, source, confidence, and provenance. A detected bounding box is not automatically an accurate wall polygon. Prefer CAD/vector geometry and explicit dimensions when available.

### Stage 4 — Link plans, elevations, and sections

- Match floor plans with corresponding elevations and sections using drawing references, grid axes, levels, title blocks, dimensions, and geometric anchors.
- Align sheets only when there is enough evidence.
- Resolve storey heights and wall heights from explicit dimensions or linked elevations/sections where possible.
- Link vertical elements across floors where supported.
- Keep ambiguous alignments unresolved rather than guessing.

### Stage 5 — Construct 3D geometry

Create procedural geometry from verified 2D footprints and dimensions:

- walls: extrude footprint/centerline + thickness using supported height;
- slabs: extrude floor/roof polygon using supported thickness;
- columns: create solids using actual dimensions and vertical extents;
- beams: create solids using section dimensions and placement when available;
- doors/windows: construct openings or placeholder geometry with measured size/location where supported;
- stairs/ramps: reconstruct from plan and section evidence where available;
- rooms: create semantic volumes/bounds from floor polygon and known/inferred storey height.

If only a 2D floor plan exists and wall height is unknown, do not present a guessed extrusion as fact. Options:

1. keep a 2D/2.5D representation;
2. make a clearly labelled **visual-only inferred height** using a configurable display value;
3. mark the 3D element's height as unknown and exclude it from exact height/volume calculations.

The UI must visually distinguish measured/explicit geometry from inferred or illustrative geometry.

### Stage 6 — Native 3D/BIM ingestion

For IFC or other supported 3D sources:

- retain the source model as authoritative;
- extract semantic entity data and relationships;
- convert/render geometry for the browser;
- map each visible mesh/component to IFC GlobalId or stable element ID;
- maintain source file and property references;
- do not reconstruct a native IFC model from a 2D plan unless needed to supplement missing content.

### Stage 7 — Unified scene model

Create one common scene schema that can contain:

- native IFC entities/geometry;
- reconstructed 3D geometry from 2D sheets;
- original 2D drawing entities;
- relationships and annotations;
- source/evidence references;
- confidence and provenance.

Do not force source geometry into an inaccurate lossy format. Store native-source references alongside web-renderable geometry.

### Stage 8 — Validation

Validate reconstructed geometry using:

- explicit dimensions and scale;
- consistency between plan/elevation/section;
- repeated grid spacing;
- room closure and wall intersection checks;
- known IFC geometry where linked;
- duplicate and overlap checks;
- unit validation.

Create a reconstruction report that identifies missing heights, ambiguous objects, unsupported classes, coordinate uncertainty, and assumptions.

---

## 6. Shared spatial data model and evidence graph

Create Pydantic schemas and matching frontend TypeScript types. Define them once and use them throughout.

### Minimum entity schema

Each building element should support fields similar to:

```json
{
  "id": "stable-internal-id",
  "global_id": null,
  "entity_type": "wall",
  "name": "W12",
  "geometry": {
    "kind": "mesh_or_extrusion_or_polygon",
    "coordinate_system": "building_world",
    "source_geometry_ref": "geometry-id",
    "viewer_asset_ref": "optional-glb-or-mesh"
  },
  "properties": {
    "length": {"value": 5.2, "unit": "m", "status": "measured"},
    "thickness": {"value": 0.2, "unit": "m", "status": "extracted"},
    "height": {"value": null, "unit": "m", "status": "unknown"}
  },
  "relationships": [],
  "provenance": {
    "method": "cad_extraction",
    "source_document_id": "doc-id",
    "page_or_sheet": "A-102",
    "source_region": [0, 0, 100, 100],
    "source_coordinate_system": "pdf_points",
    "confidence": 0.95,
    "status": "explicit_or_measured_or_detected_or_inferred_or_unknown"
  }
}
```

The example is illustrative; do not hardcode fake values.

### Required provenance statuses

Use a controlled vocabulary, for example:

- `explicit` — explicitly stated in a source property/annotation;
- `measured` — calculated from reliable source geometry/dimensions;
- `detected` — recognized by a model but not independently verified;
- `inferred` — derived from linked sheets or constraints with assumptions;
- `illustrative` — visual-only value, never used for engineering quantities;
- `unknown` — unavailable.

### Relationships

Support relationships such as:

- `belongs_to_storey`
- `located_in_space`
- `bounds_space`
- `adjacent_to`
- `connected_to`
- `supports`
- `intersects`
- `contains_opening`
- `represented_by`
- `referred_to_by_annotation`
- `same_element_as`
- `derived_from`

Every inferred relationship must carry provenance and confidence. Do not assume structural support from geometric proximity alone.

### Evidence record

Every answer/tool result should be able to refer to:

- source document and version;
- source page/sheet;
- original 2D coordinates or crop;
- 3D element IDs/GlobalIds;
- extraction tool/model/version;
- extracted text, property, geometry, or calculation;
- units;
- confidence and provenance status;
- transformation path between source and viewer coordinate systems.

---

## 7. Groq LLM: question interpretation and tool routing

Groq is the primary LLM provider for question understanding, task planning, and routing. Do not use Groq as the authoritative visual detector or geometric calculator.

Use `GROQ_API_KEY` from environment/secrets. Use a configurable `GROQ_MODEL`. Do not hardcode credentials or print them. If a key was previously exposed, instruct the user to rotate it and configure the replacement in local `.env` or hosting secrets.

### Tool registry

Register tools with explicit JSON/Pydantic schemas, descriptions, preconditions, supported input types, output schemas, and provenance behavior. Example capabilities:

- `search_documents`
- `search_annotations`
- `extract_schedule`
- `run_ocr`
- `detect_objects`
- `segment_region`
- `get_2d_geometry`
- `get_3d_element`
- `query_ifc`
- `find_spatial_relations`
- `calculate_area`
- `calculate_length`
- `calculate_volume`
- `find_intersections`
- `aggregate_quantities`
- `render_2d_evidence`
- `render_3d_evidence`
- `compare_sources`

Only expose tools that are actually implemented and healthy. Never fabricate a tool result.

### Planner output

Groq should return a structured plan, not a free-form list of imagined actions. The plan should include:

- intent and requested quantity/property;
- entities/classes and scope (building, level, space, drawing, revision);
- units and constraints;
- evidence sources to search;
- ordered or parallel tool calls;
- expected outputs;
- verification rules;
- missing-information policy.

Validate the plan server-side against an allowlist. Do not execute arbitrary code generated by the LLM. Apply timeouts, iteration limits, input validation, and tool-call budgets.

### Dynamic routing principle

Do not hardcode `count -> YOLO`, `area -> geometry`, etc. as universal rules. The choice depends on both the question and the available source capabilities.

Examples:

- Window count in IFC: query IFC elements, then cross-check drawing if needed.
- Window count in scanned plan: use plan parser/detector, optionally segmentation, then count deduplicated instances.
- Room area in DXF: use vector room boundary and Shapely.
- Room area in raster plan: reconstruct polygon with vision/geometric methods, verify scale and closure, then calculate.
- Wall material: search schedule/annotation/IFC property; do not infer from wall color.
- Structural support: query explicit BIM relationships or supported structural analysis data; do not infer merely because elements touch.

Allow multi-tool plans, parallel calls when independent, and iterative plans when first evidence is insufficient. Stop safely when evidence is inadequate.

---

## 8. Answering and verification

Use deterministic calculation for counts, areas, lengths, volumes, coordinates, intersections, and aggregation whenever source geometry is reliable.

### Verification checks

- units and unit conversions;
- duplicate entities across different sheets/representations;
- geometry validity and polygon closure;
- consistent building coordinate system;
- source revision conflicts;
- missing/unknown dimensions;
- gross vs net area/volume definitions;
- treatment of openings;
- agreement/disagreement between IFC and drawings;
- evidence coverage for all aggregated elements.

Do not report an exact result if the needed geometry or dimensions are unknown. Explain limitations in the answer.

### Final answer structure

Return structured results that include:

- concise natural-language answer;
- value and unit where relevant;
- calculation method;
- assumptions and limitations;
- source documents/pages/sheets;
- related 2D evidence regions;
- highlighted 3D element IDs;
- confidence/provenance explanation;
- any unresolved discrepancies.

The UI should distinguish `verified`, `partially supported`, and `insufficient evidence`. Avoid arbitrary confidence percentages unless calibrated; show the basis for confidence.

---

## 9. Frontend: React + Three.js, with a distinctive professional UI

The frontend is a critical hackathon deliverable. Build a polished, coherent product experience—not a generic dashboard, not a plain chat page, and not a static mockup.

### Required technology

- React + TypeScript.
- Three.js using `@react-three/fiber` and `@react-three/drei` (or direct Three.js if the existing app already uses it).
- PDF.js/react-pdf or the existing coordinate-aware PDF viewer for 2D source sheets.
- A clean component system and responsive layout.
- Backend communication through typed API clients.
- SSE or WebSocket for live processing/execution updates where useful.

### Design direction

Create a premium technical workspace for architects and construction engineers. It should feel like a modern engineering product: precise, calm, spatial, information-dense but readable. Avoid generic purple AI gradients, excessive rounded cards, default dashboard templates, and decorative charts with no purpose.

Suggested visual direction:

- dark graphite/navy workspace or a carefully designed light technical canvas;
- warm neutral surfaces for document sheets;
- restrained electric blue/cyan for selected geometry;
- amber for uncertain/inferred elements;
- green for verified evidence;
- red only for errors/conflicts;
- crisp typography, strong grid, disciplined spacing, subtle borders;
- purposeful motion when selecting/isolating/highlighting geometry;
- high-contrast labels and clear status indicators.

Make the product name **BLUELOGIC** visible but do not overdo branding.

### Main application workspace

Build a distinctive multi-panel workspace:

**Left panel — Project / document navigator**
- uploaded documents and models;
- file type and processing status;
- drawing sheet list, page numbers, levels and revisions where available;
- document relationships and linked IFC models;
- search/filter.

**Center — Spatial workbench**
- synchronized 2D drawing viewer and 3D Three.js viewer;
- switch between 2D, 3D, and split view;
- zoom, pan, orbit, fit-to-view, reset camera;
- floor/storey selector;
- layer toggles for walls, rooms, doors, windows, columns, beams, slabs, annotations, dimensions, detected objects, inferred geometry;
- select, isolate, hide/show, focus, measure, section/cut plane where feasible;
- click a 3D object and highlight its source 2D region;
- click a 2D evidence region and select/highlight the corresponding 3D element;
- distinguish native IFC, measured, detected, inferred, and illustrative geometry visually.

**Right panel — BLUELOGIC assistant**
- natural-language question input;
- answer and calculation summary;
- references/evidence list;
- selected element properties;
- verification status and limitations;
- expandable execution trace showing which tools were selected and what they returned.

**Bottom/secondary inspector**
- element/property inspector;
- source evidence details;
- dimensions and unit details;
- reconstruction warnings and uncertainty report;
- model/processing status.

### Important visual behavior

- Selecting a question result highlights corresponding 3D elements and source 2D regions.
- Selecting an element reveals its properties, IDs, provenance, and source references.
- Inferred geometry must use a visibly different style (e.g. dashed/transparent amber) from measured/native geometry.
- Unknown geometry must not silently appear as verified solid geometry.
- Segmentation masks and detections must come from actual model outputs.
- Add a clear legend. Users must be able to toggle visual layers.
- Viewer loading and errors must be handled gracefully.

### Demo flow

The initial demo should support:

1. Open BLUELOGIC workspace.
2. Upload a supported floor plan and, if available, a related elevation/section or IFC model.
3. Show format detection and processing progress.
4. Display extracted 2D structure and a 3D representation (native IFC or reconstructed geometry).
5. Ask a question such as “How many windows are on Level 1?” or “What is the area of Room 205?”
6. Show the planner/tool execution trace.
7. Display the answer, calculation/evidence, highlighted 3D elements, and highlighted original drawing region.
8. Allow the judge to inspect the model and source evidence interactively.

Do not use a fabricated drawing or hardcoded answer to simulate success. Use real sample data from the workspace and clearly label any visual-only inferred geometry.

---

## 10. API and service interfaces

Define stable typed contracts before wiring components together. Use Pydantic backend models and matching TypeScript interfaces.

Suggested endpoints (adapt to existing code if present):

- `POST /api/documents` — upload files and create document records.
- `GET /api/documents/{document_id}` — metadata, format, processing status, capabilities.
- `POST /api/documents/{document_id}/process` — run ingestion/reconstruction.
- `GET /api/documents/{document_id}/scene` — unified scene metadata and viewer assets.
- `GET /api/documents/{document_id}/sheets` — pages/sheets and coordinate transforms.
- `POST /api/questions` — submit a question and create an execution run.
- `GET /api/runs/{run_id}` — answer, status, tool trace, evidence, warnings.
- `GET /api/runs/{run_id}/events` — SSE stream for progress if implemented.
- `GET /api/elements/{element_id}` — properties, geometry references, relationships, provenance.
- `GET /api/evidence/{evidence_id}` — evidence metadata/crop/overlay asset.

Use background tasks for long processing. Ensure errors are returned in a structured way. Do not block the UI while reconstructing a large model.

---

## 11. Security, reliability, and configuration

- Read `GROQ_API_KEY` from environment variables.
- Read `GROQ_MODEL` from environment; choose a currently supported Groq model and make it configurable.
- If Gemini VLM is used, read `GEMINI_API_KEY` and `GEMINI_MODEL` from environment. Do not require it for basic operation.
- If local Qwen VLM is used, configure model path and device through environment/config.
- Keep `.env` out of Git. Provide `.env.example` with placeholders only.
- Never ask the user to paste secrets in chat. Never log credentials.
- If the previously shared Groq key is still active, treat it as compromised and advise rotation. Do not include any exposed key in code, prompts, logs, or project files.
- Validate file type/signature and size; use safe filenames and storage paths; protect against path traversal.
- Do not execute arbitrary LLM-generated code or shell commands.
- Apply request timeouts, model timeouts, file limits, and tool-call budgets.
- Handle missing model weights with actionable setup messages.
- Track dependency/model licenses and attribution.

---

## 12. Project structure recommendation

Adapt to the existing repository rather than blindly replacing it. A possible structure:

```text
blue logic/
├── README.md
├── .env.example
├── .gitignore
├── docs/
│   ├── DATA_AUDIT.md
│   ├── ARCHITECTURE.md
│   ├── EVALUATION.md
│   ├── STATUS.md
│   ├── DECISIONS.md
│   └── NEXT_AGENT_HANDOFF.md
├── data/
│   ├── splits/                 # manifests only; do not duplicate originals
│   └── annotations/            # manually labelled CV evaluation samples
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── api/
│   │   ├── core/
│   │   ├── schemas/
│   │   ├── ingestion/
│   │   │   ├── format_detector.py
│   │   │   ├── pdf_adapter.py
│   │   │   ├── cad_adapter.py
│   │   │   ├── dwg_converter.py
│   │   │   ├── svg_adapter.py
│   │   │   ├── image_adapter.py
│   │   │   └── ifc_adapter.py
│   │   ├── vision/
│   │   │   ├── model_registry.py
│   │   │   ├── grounding_dino.py
│   │   │   ├── sam2.py
│   │   │   ├── cubicasa.py
│   │   │   ├── roomformer.py
│   │   │   ├── ocr.py
│   │   │   └── vlm_provider.py
│   │   ├── reconstruction/
│   │   │   ├── coordinates.py
│   │   │   ├── sheet_linking.py
│   │   │   ├── plan_parser.py
│   │   │   ├── geometry_2d.py
│   │   │   ├── geometry_3d.py
│   │   │   ├── alignment.py
│   │   │   ├── scene_builder.py
│   │   │   └── validation.py
│   │   ├── spatial/
│   │   │   ├── entity_store.py
│   │   │   ├── relationships.py
│   │   │   └── queries.py
│   │   ├── tools/
│   │   │   ├── registry.py
│   │   │   ├── retrieval_tools.py
│   │   │   ├── vision_tools.py
│   │   │   ├── geometry_tools.py
│   │   │   ├── ifc_tools.py
│   │   │   └── evidence_tools.py
│   │   ├── orchestration/
│   │   │   ├── groq_client.py
│   │   │   ├── question_parser.py
│   │   │   ├── planner.py
│   │   │   ├── executor.py
│   │   │   └── verifier.py
│   │   └── storage/
│   └── tests/
└── frontend/
    ├── src/
    │   ├── app/
    │   ├── components/
    │   │   ├── workspace/
    │   │   ├── viewer2d/
    │   │   ├── viewer3d/
    │   │   ├── assistant/
    │   │   ├── evidence/
    │   │   └── inspector/
    │   ├── hooks/
    │   ├── services/
    │   ├── types/
    │   └── styles/
    └── tests/
```

---

## 13. Step-by-step implementation plan

Follow this order. Do not build all components independently and leave integration until the end.

### Phase 1 — Repository and dataset audit

1. Inspect current repository, scripts, dependencies, dataset, README and questions.
2. Run the app/tests if they exist and record current status.
3. Inventory actual file formats and choose a small demo sample.
4. Identify alternate formats of the same drawing and IFC/PDF model associations.
5. Create leakage-safe grouped split manifest.
6. Create `docs/DATA_AUDIT.md`, `docs/EVALUATION.md`, and `docs/ARCHITECTURE.md`.

**Exit criterion:** We know what files exist, what can be parsed, what the first demo sample is, and the split is reproducible without leakage.

### Phase 2 — Shared schemas and ingestion

1. Define document, sheet, geometry, entity, scene, evidence, question, plan, tool-result, and answer schemas.
2. Implement format detection.
3. Implement PDF and image ingestion first.
4. Implement DXF and IFC adapters; add DWG conversion adapter with clear availability detection.
5. Preserve coordinate transforms and provenance from the start.
6. Expose ingestion status through API.

**Exit criterion:** Upload a real file and inspect its format, pages/entities, metadata, capabilities, and source coordinates.

### Phase 3 — 2D understanding and vision

1. Install compatible OCR and vision dependencies.
2. Verify actual pretrained checkpoint availability/license and device compatibility.
3. Integrate PaddleOCR.
4. Integrate Grounding DINO.
5. Integrate SAM 2 prompt segmentation.
6. Integrate a CubiCasa5K pretrained parser; compare RoomFormer only if practical.
7. Build tiled inference and source-coordinate restoration.
8. Store genuine masks/detections and create overlay assets.
9. Add model health checks and tests.

**Exit criterion:** On a real raster drawing, extract OCR and show actual detections/masks with correct page coordinates. Unsupported classes must be reported honestly.

### Phase 4 — 2D geometry and 3D reconstruction

1. Extract PDF vector paths and DXF entities where available.
2. Parse room polygons, wall geometry, dimensions, grids, levels, doors/windows and columns where supported.
3. Normalize units and coordinate frames.
4. Link plans to elevations/sections using explicit references and geometry.
5. Reconstruct supported elements using procedural geometry.
6. Mark all modelled properties as explicit/measured/detected/inferred/illustrative/unknown.
7. Import and preserve native IFC models.
8. Create unified scene output and export viewer assets (GLB/glTF or another suitable format) with stable element mappings.
9. Validate model geometry and compare where linked sources allow.

**Exit criterion:** A real drawing/model opens in the 3D viewer, selected elements retain source evidence, and unknown dimensions are not presented as exact.

### Phase 5 — Spatial representation and query tools

1. Implement entity store and graph-like relationships.
2. Implement geometry, spatial, IFC, text and evidence tools.
3. Build deterministic area/length/volume/count/intersection operations.
4. Add duplicate handling and source revision awareness.
5. Add tests for coordinate systems, units, polygons, intersections and quantities.

**Exit criterion:** Backend can run reliable tools against the unified scene and return evidence-linked structured results.

### Phase 6 — Groq planner and dynamic execution

1. Configure Groq securely.
2. Define tool descriptions and JSON schemas.
3. Implement question parsing and structured execution plans.
4. Validate plans server-side against available tools.
5. Execute sequential/parallel tools with budgets and timeouts.
6. Support iterative follow-up when evidence is insufficient.
7. Verify result units, calculations, provenance and conflicts.
8. Return structured answers and trace.

**Exit criterion:** Different natural-language questions cause different valid tool workflows, and no arbitrary generated code is executed.

### Phase 7 — Premium React + Three.js UI

1. Build product shell and project/document navigator.
2. Implement 2D viewer with coordinate-aware evidence overlays.
3. Implement 3D viewer using React Three Fiber/Three.js.
4. Add synchronized selection/highlighting between 2D and 3D.
5. Add layers, floor selector, isolate/hide, inspect, orbit, zoom and fit-to-view.
6. Build assistant panel, answers, evidence cards and execution trace.
7. Add reconstruction confidence/provenance styling and warnings.
8. Polish loading, error, empty and unsupported-format states.
9. Test responsive behavior and accessibility.

**Exit criterion:** A judge can upload a real sample, see it processed, inspect the 3D result, ask a question, and verify the answer by clicking highlighted evidence.

### Phase 8 — End-to-end testing and submission hardening

1. Run backend and frontend from a clean start.
2. Test actual LLM connection through configured Groq secret.
3. Test each available format and document limitations.
4. Test at least three question workflows that use different tool combinations.
5. Test a native IFC model and a reconstructed 2D drawing.
6. Test 2D/3D highlight synchronization.
7. Test invalid files, missing model weights, unavailable API, timeout, and missing dimensions.
8. Run benchmark evaluation on the held-out test split.
9. Fix critical bugs and performance issues.
10. Create a reproducible README with setup, run commands, model downloads, environment variables, and demo steps.
11. Update status and next-agent handoff.

**Exit criterion:** The application runs, the main demo flow works end-to-end on real files, and all incomplete capabilities are honestly documented.

---

## 14. Required demo questions and scenarios

Build and test multiple scenarios, not just one hardcoded prompt.

### Scenario A — Raster floor plan

Question example: “How many windows are shown on Level 1?”

Expected workflow: image/PDF page → OCR/plan parser or Grounding DINO → optional SAM 2 → deduplication/count → evidence regions → highlighted 2D/3D elements if reconstructed.

### Scenario B — Room geometry

Question example: “What is the area of Room 205?”

Expected workflow: room label retrieval → locate room boundary → validate scale/units → polygon area calculation → answer with polygon and source dimensions. If boundary or scale is not reliable, do not invent an exact area.

### Scenario C — Existing IFC model

Question example: “How many doors are on Level 2?”

Expected workflow: identify Level 2 → query IFC door entities → count → map IFC GlobalIds to viewer geometry → highlight doors in 3D and linked plan if available.

### Scenario D — Cross-sheet question

Question example: “What is the height of the wall shown on this floor plan?”

Expected workflow: find wall reference → find linked section/elevation → extract dimension → associate the evidence with wall → answer. If no height is present, state that it cannot be determined from supplied sources.

### Scenario E — Spatial relationship

Question example: “Which rooms share a wall with Room 205?”

Expected workflow: retrieve room polygon and adjacent room polygons → compute shared boundaries → return relationships with 2D/3D highlights. Do not infer adjacency from labels alone.

---

## 15. Testing requirements

### Unit tests

- format detection and file signature checks;
- PDF/DXF/IFC parser outputs;
- coordinate transforms between source pixels/PDF/CAD/world/viewer;
- geometry validity and polygon area;
- 3D extrusion dimensions;
- IFC GlobalId mapping;
- model output coordinate restoration after tiling/resizing;
- tool input/output validation;
- answer provenance completeness;
- unit conversions and quantity aggregation.

### Integration tests

- upload → parse → scene creation;
- raster image → detection → segmentation → overlay;
- DXF → geometric extraction → 3D reconstruction;
- IFC → parse → viewer asset → selectable semantic elements;
- question → Groq plan → tools → verifier → answer;
- answer evidence → 2D/3D selection synchronization.

### End-to-end tests

At minimum, test one real raster/PDF sample, one vector/CAD sample if converter/parser is available, and one IFC sample if present. Use stable sample IDs and report exact test commands/results.

### Quality metrics

- exact count accuracy;
- area/length/volume relative error against benchmark scoring rules;
- OCR word/character accuracy on labelled sample;
- detection precision/recall on manually annotated sample;
- segmentation IoU on manually annotated sample;
- room polygon/geometry error where ground truth exists;
- source evidence localization accuracy;
- tool routing success and unnecessary tool call rate;
- unsupported/abstention quality;
- end-to-end latency and failure rate.

Do not report metrics without a real evaluation set and reproducible script.

---

## 16. Performance and practical constraints

- Inspect GPU/CPU/RAM before selecting model variants.
- Do not download multiple giant checkpoints without checking storage and VRAM.
- Prefer small/base checkpoints for the first demo where quality is acceptable.
- Cache processed pages, OCR, detections, segmentations, geometries and scene assets.
- Do not rerun full document processing for every question.
- Use high-resolution crops/tiles for small annotations; preserve coordinate maps.
- Load models lazily and expose availability status.
- Use asynchronous/background jobs for expensive processing.
- Provide progress and cancellation where practical.
- Avoid loading the entire dataset into memory.
- Use deterministic seeded processing where possible.

---

## 17. Definition of “complete” — do not stop before this

The system is **not complete** merely because a frontend loads, an LLM returns text, a 3D cube appears, or placeholder detections are drawn.

A credible first demo is complete only when all of the following are true:

- [ ] The application starts locally using documented commands.
- [ ] User can upload a real supported construction drawing/model.
- [ ] File format is detected and displayed.
- [ ] A genuine format-specific parser runs.
- [ ] At least one real 2D-to-3D reconstruction path works on a real drawing, with uncertainty/provenance labels.
- [ ] At least one existing IFC/BIM path works if IFC data is available in the workspace; native geometry is preserved.
- [ ] The 3D result is displayed in an interactive Three.js viewer.
- [ ] Original 2D drawing can be viewed and zoomed.
- [ ] User can ask a natural-language question.
- [ ] Groq is called using a configured environment secret and returns a validated tool plan.
- [ ] At least two different tool paths work for different questions.
- [ ] The answer is derived from real tool outputs, not a hardcoded response.
- [ ] Evidence points to the actual source page/region and/or IFC element.
- [ ] Selecting evidence highlights the correct source 2D region and 3D element where mapping exists.
- [ ] Unknown or inferred geometry is visibly distinguished from verified geometry.
- [ ] Errors and unsupported formats are handled honestly.
- [ ] Tests are written and run.
- [ ] Setup and demo instructions are documented.

If some advanced capability cannot be completed within the hackathon, do not fake it. Build the strongest smaller end-to-end path and clearly mark the remaining work as unsupported or planned.

---

## 18. Execution and continuity instructions

You are the primary developer responsible for the entire application from A to Z. Do not assign the user a role or require them to coordinate separate agents. You may use available coding subagents/tools if genuinely helpful, but you own the complete integration and final result.

### Work autonomously

- Inspect first, then make decisions and implement.
- Install dependencies only after checking project compatibility.
- Create/modify code and run it.
- Fix errors rather than stopping at the first failure.
- Use actual files from the dataset.
- Do not replace working code without reason.
- Do not leave TODOs in the main demo path.
- Do not claim features work unless tested.
- Do not ask for confirmation for routine engineering choices; make sensible choices and document them.
- Ask the user only when a truly required external credential or unavailable system-level dependency blocks execution. Explain exactly what is needed.

### Maintain handoff documentation

Keep these files current:

- `docs/STATUS.md` — implemented, tested, partial, blocked, not started.
- `docs/DECISIONS.md` — architecture/technology decisions and rationale.
- `docs/NEXT_AGENT_HANDOFF.md` — exact current state, commands run, known bugs, and next steps.
- `docs/DEMO_SCRIPT.md` — reliable peer-submission demonstration flow.

If context/tokens are running low, update those files before stopping so another coding model can continue without relying on chat history.

### Final response after implementation

When you finish a development session, report:

1. What you implemented.
2. What actually works and how it was tested.
3. Exact command(s) to run the application.
4. Required environment variables (names only; never reveal values).
5. Models/weights installed and their locations/license references.
6. Features still incomplete or unavailable.
7. Current bugs/performance limitations.
8. The next highest-priority tasks.

**Start now: inspect the repository and dataset, create the audit, define schemas, and implement the first complete upload → format detection → 2D/3D representation → question → tool execution → evidence answer workflow. Continue until it runs end-to-end.**
