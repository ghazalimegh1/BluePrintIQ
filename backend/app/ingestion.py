from __future__ import annotations

import hashlib
import math
import re
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any

from .ocr import ocr_is_available
from .schemas import Capability, DocumentRecord


ROOT = Path(__file__).resolve().parents[2]
DATASET_ROOT = ROOT / "junction-dataset-preview"
DATA_ROOT = DATASET_ROOT / "data"
UPLOAD_ROOT = ROOT / "runtime" / "uploads"
ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".svg", ".dxf", ".dwg", ".ifc"}
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_RENDER_PIXELS = 16_000_000


@dataclass(frozen=True)
class DXFPreview:
    content: bytes
    width: float
    height: float
    view_box: tuple[float, float, float, float]
    model_to_viewbox: tuple[float, float, float, float, float, float]

    def transform_point(self, x: float, y: float) -> tuple[float, float]:
        origin_x, origin_y, x_axis_x, x_axis_y, y_axis_x, y_axis_y = self.model_to_viewbox
        return (
            origin_x + x * x_axis_x + y * y_axis_x,
            origin_y + x * x_axis_y + y * y_axis_y,
        )


def _doc_id(relative_path: str) -> str:
    return hashlib.sha256(relative_path.encode("utf-8")).hexdigest()[:24]


def _safe_join(root: Path, relative_path: str) -> Path:
    candidate = (root / Path(*PurePosixPath(relative_path).parts)).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("Path escapes its allowed root") from exc
    return candidate


def _source_for(path: str) -> str:
    parts = PurePosixPath(path).parts
    if len(parts) >= 2 and parts[0] == "data":
        return parts[1]
    return "uploaded"


def _license_metadata(path: str) -> tuple[str | None, str | None]:
    source = _source_for(path)
    if source == "uploaded":
        return None, "User-uploaded document"
    license_path = DATA_ROOT / source / "LICENSE.md"
    if not license_path.is_file():
        return None, "Licence metadata not found; inspect the dataset README before reuse"
    relative_file = "/".join(PurePosixPath(path).parts[2:]).casefold()
    credit = None
    for line in license_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith("|"):
            continue
        columns = [column.strip().strip("`") for column in line.split("|")[1:-1]]
        if len(columns) >= 4 and columns[0].casefold() == relative_file:
            credit = columns[3]
            break
    if not credit:
        source_credits = {
            "cubicasa5k": "CubiCasa5K (c) 2019 CubiCasa; Kalervo et al., SCIA 2019; CC BY-NC-SA 4.0.",
            "swiss_dwellings": "Swiss Dwellings v3.0.0 by Archilyse AG et al.; CC BY 4.0.",
        }
        credit = source_credits.get(
            source, f"Source-specific credit and licence: data/{source}/LICENSE.md"
        )
    return f"data/{source}/LICENSE.md", credit


def _file_format(path: Path) -> str:
    return path.suffix.casefold().lstrip(".")


def _capabilities(path: Path) -> tuple[list[Capability], int | None, str]:
    extension = path.suffix.casefold()
    capabilities: list[Capability] = []
    page_count: int | None = None
    status = "ready"

    if extension == ".pdf":
        try:
            import pymupdf as fitz
        except ImportError:
            capabilities.append(Capability(
                capability_type="pdf_document", available=True,
                details={"page_count": None},
                limitations=["PyMuPDF is not installed; text extraction and page rendering are unavailable"],
            ))
            return capabilities, None, "limited"
        try:
            with fitz.open(path) as document:
                page_count = len(document)
                if page_count > 0:
                    first_page = document[0]
                    text = first_page.get_text("text")
                    vector_items = len(first_page.get_drawings())
                    ocr_available = ocr_is_available()
                    capabilities.extend([
                        Capability(
                            capability_type="pdf_text", available=bool(text.strip()),
                            details={"first_page_characters": len(text), "pages_inspected": 1},
                            limitations=[] if text.strip() else ["No extractable text on the first page; OCR is not configured"],
                            coordinate_system="pdf_points",
                        ),
                        Capability(
                            capability_type="pdf_render", available=True,
                            details={"page_count": page_count, "vector_drawings_first_page": vector_items},
                            coordinate_system="pdf_points",
                        ),
                        Capability(
                            capability_type="ocr",
                            available=ocr_available,
                            details={"engine": "EasyOCR", "languages": ["en"]} if ocr_available else {},
                            limitations=[] if ocr_available else [
                                "Install the optional EasyOCR requirements and local English model weights to process scanned pages"
                            ],
                        ),
                    ])
        except (RuntimeError, ValueError, OSError) as exc:
            capabilities.append(Capability(
                capability_type="pdf_document", available=False,
                limitations=[f"PDF could not be opened: {exc}"],
            ))
            return capabilities, None, "limited"
    elif extension in {".png", ".jpg", ".jpeg"}:
        try:
            from PIL import Image
            with Image.open(path) as image:
                dimensions = list(image.size)
                image.verify()
            ocr_available = ocr_is_available()
            capabilities.extend([
                Capability(
                    capability_type="raster", available=True,
                    details={"width": dimensions[0], "height": dimensions[1]},
                    coordinate_system="image_pixels",
                ),
                Capability(
                    capability_type="ocr",
                    available=ocr_available,
                    details={"engine": "EasyOCR", "languages": ["en"]} if ocr_available else {},
                    limitations=[] if ocr_available else [
                        "Install the optional EasyOCR requirements and local English model weights"
                    ],
                ),
                Capability(
                    capability_type="object_detection", available=False,
                    limitations=["No detector or segmentation model is configured"],
                ),
            ])
            status = "limited"
        except (ImportError, OSError, ValueError) as exc:
            capabilities.append(Capability(
                capability_type="raster", available=False,
                limitations=[f"Image could not be inspected: {exc}"],
            ))
            status = "limited"
    elif extension == ".svg":
        try:
            root = ET.parse(path).getroot()
            tag_counts = Counter(
                element.tag.rsplit("}", 1)[-1].casefold()
                for element in root.iter()
            )
            view_box = read_svg_viewbox(path)
            capabilities.extend([
                Capability(
                    capability_type="svg_vector",
                    available=True,
                    details={
                        "view_box": root.attrib.get("viewBox"),
                        "width": root.attrib.get("width"),
                        "height": root.attrib.get("height"),
                        "element_counts": dict(tag_counts),
                    },
                    coordinate_system="svg_viewbox",
                ),
                Capability(
                    capability_type="svg_text",
                    available=tag_counts.get("text", 0) > 0,
                    details={"text_element_count": tag_counts.get("text", 0)},
                    limitations=[] if tag_counts.get("text", 0) else ["No SVG text elements were found"],
                    coordinate_system="svg_viewbox" if view_box else None,
                ),
            ])
        except (ET.ParseError, OSError) as exc:
            capabilities.append(Capability(
                capability_type="svg_vector", available=False,
                limitations=[f"SVG could not be parsed: {exc}"],
            ))
            status = "limited"
    elif extension == ".dxf":
        try:
            import ezdxf
        except ImportError:
            capabilities.append(Capability(
                capability_type="dxf_geometry", available=False,
                limitations=["ezdxf is not installed"],
            ))
            status = "limited"
        else:
            try:
                drawing = ezdxf.readfile(path)
                modelspace = drawing.modelspace()
                entity_counts = Counter(entity.dxftype() for entity in modelspace)
                capabilities.append(Capability(
                    capability_type="dxf_geometry",
                    available=True,
                    details={
                        "entity_counts": dict(entity_counts),
                        "layers": sorted({entity.dxf.layer for entity in modelspace}),
                        "block_names": sorted(
                            {entity.dxf.name for entity in modelspace if entity.dxftype() == "INSERT"}
                        ),
                    },
                    coordinate_system="dxf_modelspace",
                ))
            except (OSError, ValueError, ezdxf.DXFStructureError) as exc:
                capabilities.append(Capability(
                    capability_type="dxf_geometry", available=False,
                    limitations=[f"DXF could not be parsed: {exc}"],
                ))
                status = "limited"
    elif extension == ".dwg":
        capabilities.append(Capability(
            capability_type="dwg_conversion",
            available=False,
            limitations=[
                "DWG is recognized, but no DWG-to-DXF converter is configured."
            ],
        ))
        status = "limited"
    elif extension == ".ifc":
        try:
            import ifcopenshell  # noqa: F401
        except ImportError:
            capabilities.append(Capability(
                capability_type="ifc_entities", available=False,
                limitations=["IfcOpenShell is not installed"],
            ))
            status = "limited"
        else:
            capabilities.extend([
                Capability(
                    capability_type="ifc_entities", available=True,
                    details={"operations": ["typed entity lookup", "spatial containment"]},
                    coordinate_system="ifc_model_coordinates",
                ),
                Capability(
                    capability_type="ifc_geometry", available=False,
                    limitations=["3D geometry extraction and drawing projection are not enabled in this demo"],
                ),
            ])
            status = "limited"
    else:
        status = "unsupported"
    return capabilities, page_count, status


def build_document_record(
    relative_path: str, path: Path, *, inspect_capabilities: bool = True
) -> DocumentRecord:
    if inspect_capabilities:
        capabilities, page_count, status = _capabilities(path)
    else:
        capabilities, page_count, status = [], None, "uninspected"
    license_file, credit = _license_metadata(relative_path)
    return DocumentRecord(
        document_id=_doc_id(relative_path),
        path=relative_path,
        source=_source_for(relative_path),
        format=_file_format(path),
        size_bytes=path.stat().st_size,
        license_file=license_file,
        license_credit=credit,
        capabilities=capabilities,
        ingestion_status=status,
        page_count=page_count,
    )


def read_svg_viewbox(path: Path) -> list[float] | None:
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise ValueError("SVG XML is malformed.") from exc
    value = root.attrib.get("viewBox")
    if not value:
        return None
    try:
        view_box = [float(part) for part in re.split(r"[\s,]+", value.strip())]
    except ValueError:
        return None
    if (
        len(view_box) != 4
        or any(not math.isfinite(value) for value in view_box)
        or view_box[2] <= 0
        or view_box[3] <= 0
    ):
        return None
    return view_box


def render_dxf_preview(path: Path) -> DXFPreview:
    try:
        import ezdxf
        from ezdxf.addons.drawing import Frontend, RenderContext, layout
        from ezdxf.addons.drawing.svg import SVGBackend
    except ImportError as exc:
        raise ImportError("ezdxf is required to render DXF drawings.") from exc

    try:
        document = ezdxf.readfile(path)
        backend = SVGBackend()
        Frontend(RenderContext(document), backend).draw_layout(document.modelspace(), finalize=True)
        svg = backend.get_string(layout.Page(1000, 700, units=layout.Units.px))
        root = ET.fromstring(svg)
        raw_view_box = root.attrib.get("viewBox")
        view_box = [float(part) for part in re.split(r"[\s,]+", raw_view_box.strip())] if raw_view_box else []
        if len(view_box) != 4 or any(not math.isfinite(value) for value in view_box):
            raise ValueError("DXF renderer returned an invalid viewBox.")
        if view_box[2] <= 0 or view_box[3] <= 0:
            raise ValueError("DXF renderer returned an empty viewBox.")
        transform = backend.transformation_matrix
        origin = transform.transform((0, 0, 0))
        x_unit = transform.transform((1, 0, 0))
        y_unit = transform.transform((0, 1, 0))
        width = float(view_box[2])
        height = float(view_box[3])
        if width <= 0 or height <= 0:
            raise ValueError("DXF renderer returned invalid page dimensions.")
        return DXFPreview(
            content=svg.encode("utf-8"),
            width=width,
            height=height,
            view_box=tuple(view_box),
            model_to_viewbox=(
                float(origin[0]),
                float(origin[1]),
                float(x_unit[0] - origin[0]),
                float(x_unit[1] - origin[1]),
                float(y_unit[0] - origin[0]),
                float(y_unit[1] - origin[1]),
            ),
        )
    except (OSError, RuntimeError, ValueError, ezdxf.DXFStructureError) as exc:
        raise ValueError(f"DXF rendering failed: {exc}") from exc


@lru_cache(maxsize=1)
def list_documents() -> list[DocumentRecord]:
    documents: list[DocumentRecord] = []
    file_entries: list[tuple[str, Path]] = []
    if DATA_ROOT.is_dir():
        file_entries.extend(
            (f"data/{path.relative_to(DATA_ROOT).as_posix()}", path)
            for path in DATA_ROOT.rglob("*")
            if path.is_file() and path.name.casefold() != "license.md"
        )
    if UPLOAD_ROOT.is_dir():
        file_entries.extend(
            (f"upload/{path.name}", path)
            for path in UPLOAD_ROOT.iterdir()
            if path.is_file()
        )

    for relative_path, path in sorted(file_entries, key=lambda entry: entry[0].casefold()):
        extension = path.suffix.casefold()
        if extension not in ALLOWED_EXTENSIONS and extension != ".dwg":
            continue
        documents.append(
            build_document_record(relative_path, path, inspect_capabilities=False)
        )

    by_path = {document.path: document for document in documents}
    for document in documents:
        if document.format != "ifc":
            continue
        base = PurePosixPath(document.path)
        folder = DATASET_ROOT / Path(*base.parts[:-1])
        prefix = base.stem
        candidates = sorted(folder.glob(f"{prefix}_plan-*.pdf"))
        if candidates:
            companion_path = f"{'/'.join(base.parts[:-1])}/{candidates[0].name}"
            companion = by_path.get(companion_path)
            if companion:
                document.companion_document_id = companion.document_id
    return documents


def find_document(document_id: str) -> tuple[DocumentRecord, Path]:
    if UPLOAD_ROOT.is_dir():
        for candidate in UPLOAD_ROOT.iterdir():
            if not candidate.is_file():
                continue
            relative_path = f"upload/{candidate.name}"
            if _doc_id(relative_path) == document_id:
                path = _safe_join(UPLOAD_ROOT, candidate.name)
                return (
                    build_document_record(
                        relative_path, path, inspect_capabilities=False
                    ),
                    path,
                )

    for document in list_documents():
        if document.document_id != document_id:
            continue
        if document.path.startswith("upload/"):
            path = _safe_join(UPLOAD_ROOT, document.path.removeprefix("upload/"))
        else:
            path = _safe_join(DATASET_ROOT, document.path)
        return document, path
    raise KeyError("Document not found")


def read_license(document: DocumentRecord) -> str:
    if not document.license_file:
        return "User-uploaded file; confirm rights before sharing or redistributing it."
    license_path = _safe_join(DATASET_ROOT, document.license_file)
    return license_path.read_text(encoding="utf-8", errors="replace")


def render_pdf_page(path: Path, page_number: int) -> tuple[bytes, float, float, int]:
    import pymupdf as fitz

    with fitz.open(path) as document:
        if page_number < 1 or page_number > len(document):
            raise IndexError(f"Page must be between 1 and {len(document)}")
        page = document[page_number - 1]
        zoom = min(1.7, (MAX_RENDER_PIXELS / max(page.rect.width * page.rect.height, 1)) ** 0.5)
        pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        return pixmap.tobytes("png"), float(page.rect.width), float(page.rect.height), len(document)


def read_pdf_text(path: Path, max_pages: int = 500) -> list[dict[str, Any]]:
    import pymupdf

    pages: list[dict[str, Any]] = []
    with pymupdf.open(path) as document:
        for page_index, page in enumerate(document[:max_pages]):
            spans: list[dict[str, Any]] = []
            data = page.get_text("dict")
            for block in data.get("blocks", []):
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        text = span.get("text", "").strip()
                        if text:
                            spans.append({"text": text, "bbox": list(span["bbox"])})
            pages.append({
                "page": page_index + 1,
                "width": float(page.rect.width),
                "height": float(page.rect.height),
                "spans": spans,
            })
    return pages
