# Dataset audit

Audit date: 2026-11-13

## Workspace and environment

- Project root: `C:\Users\HP\Desktop\JunctionHack`
- Dataset root: `junction-dataset-preview/`
- Dataset README: `junction-dataset-preview/README.md`
- No Git repository, app source, dependency manifest, tests, or `docs/` directory existed at the start of this work.
- Python 3.13.13; Pillow 13.0.0 is installed. FastAPI, PyMuPDF, ezdxf, IfcOpenShell, OpenCV, and Tesseract were not present at audit time.
- The project root and dataset root are different. Do not write application outputs into the source `data/` tree.

## Question-file validation

`junction-dataset-preview/questions.jsonl` was parsed record by record:

- 7,990 records; all are valid JSON objects with `path`, `question`, `answer`, `unit`, and `type`.
- 320 distinct referenced paths; all 320 exist under the dataset root.
- Source rows: `cubicasa5k` 4,270; `swiss_dwellings` 2,358; `ifc_models` 1,049; `ifc_bench` 249; `opening_design` 64.
- Types: `count` 6,076; `area` 1,599; `text` 265; `volume` 34; `length` 16.
- Units: `count` 6,076; `m2` 1,590; `ft2` 9; `m3` 34; `m` 16; absent 265.
- Referenced formats: PNG 4,270 rows; PDF 2,644; IFC 1,076.

These are counts from the supplied question file, not the larger challenge collection described by the README.

## Local data tree and licences

The local data tree has nine source folders and 913 non-license files (approximately 725 MB):

| Source | Files | Formats | Questions | Licence / handling note |
|---|---:|---|---:|---|
| `cubicasa5k` | 241 | PNG | 4,270 | CC BY-NC-SA 4.0; non-commercial, preserve credit and share-alike terms |
| `swiss_dwellings` | 195 | DXF, PDF, PNG | 2,358 | CC BY 4.0; preserve attribution |
| `ifc_models` | 10 | IFC, PDF, SVG | 1,049 | Per-file; includes an ND model, do not modify that source |
| `ifc_bench` | 5 | IFC | 249 | Per-file, including ND and GPL-3.0 sources; preserve the supplied notices |
| `opening_design` | 81 | PDF, IFC, DWG, DXF | 64 | Per-file, mostly CC BY-SA 4.0 plus MIT; preserve project attribution and SA terms |
| `habs` | 92 | JPG | 0 | Source-specific terms in its licence file |
| `finna` | 96 | JPG | 0 | Source-specific terms in its licence file |
| `europeana` | 61 | JPG | 0 | Per-file licences; some NC and SA terms |
| `wikimedia` | 132 | JPG, SVG | 0 | Per-file licences |

Every source folder has a `LICENSE.md`. The README and the licences for question-bearing sources were reviewed before selecting processing examples. Rendering is read-only and source files must remain unchanged. The application must show the source and licence notice and must not send drawings to an external service by default.

## Data integrity and remaining audit work

- All question-referenced paths currently resolve; no missing paths were reported.
- Similar questions are multilingual and repeated. They are labels, not localization annotations; keep all variants of a drawing together in data splits.
- `swiss_dwellings` provides same-basename DXF/PDF/PNG representations and filenames with `site`, `bldg`, and `floor` identifiers.
- README-defined `ifc_models` pairs relate IFC models to generated PDF/SVG floor-plan views. These families must be grouped before splitting.
- `opening_design` files use project folders; all questions for one project should stay in one split.
- Hash-based duplicate grouping and image perceptual near-duplicate checks are to be produced by the split pipeline. The initial audit did not modify or export source material.

