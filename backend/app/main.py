from __future__ import annotations

import os
import re
import uuid
from pathlib import Path, PurePosixPath
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from . import ingestion
from .routing import answer_question, available_tools
from .gemini_vision import gemini_vl_status
from .scene import SceneUnavailable, build_scene
from .schemas import AskRequest, SceneResponse, SceneSelectionRequest


ROOT = Path(__file__).resolve().parents[2]
FRONTEND_ROOT = ROOT / "frontend"
BLUELOGIC_DIST = FRONTEND_ROOT / "dist"
app = FastAPI(title="STOA Construction Document Intelligence", version="0.1.0")
app.mount("/static", StaticFiles(directory=FRONTEND_ROOT), name="static")
if (BLUELOGIC_DIST / "assets").is_dir():
    app.mount(
        "/assets",
        StaticFiles(directory=BLUELOGIC_DIST / "assets"),
        name="blue-logic-assets",
    )


@app.get("/")
def home() -> FileResponse:
    index = BLUELOGIC_DIST / "index.html"
    return FileResponse(index if index.is_file() else FRONTEND_ROOT / "index.html")


@app.get("/legacy")
def legacy_home() -> FileResponse:
    return FileResponse(FRONTEND_ROOT / "index.html")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "stoa-local"}


@app.get("/api/tools")
def tools() -> list[dict[str, Any]]:
    return available_tools()


@app.get("/api/llm/status")
def llm_status() -> dict[str, Any]:
    gemini = gemini_vl_status()
    return {
        "provider": "groq",
        "api_key_configured": bool(os.getenv("GROQ_API_KEY")),
        "model": os.getenv("GROQ_MODEL", "").strip() or None,
        "gemini_vl_configured": gemini["configured"],
        "gemini_vl_model": gemini["model"],
        "gemini_vl_model_error": gemini["model_error"],
        "gemini_free_tier_only": gemini["free_tier_only"],
    }


@app.get("/api/documents")
def documents(source: str | None = None, q: str | None = None) -> list[dict[str, Any]]:
    records = ingestion.list_documents()
    if source:
        records = [record for record in records if record.source.casefold() == source.casefold()]
    if q:
        lowered = q.casefold()
        records = [
            record for record in records
            if lowered in record.path.casefold() or lowered in record.source.casefold()
        ]
    return [record.model_dump() for record in records]


@app.get("/api/documents/{document_id}")
def document_details(document_id: str) -> dict[str, Any]:
    try:
        listed_document, path = ingestion.find_document(document_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    document = ingestion.build_document_record(listed_document.path, path)
    document.companion_document_id = listed_document.companion_document_id
    records = ingestion.list_documents()
    preview_id = document.document_id
    preview_format = document.format
    representation = "source document"
    if document.companion_document_id:
        companion = next(
            (
                record
                for record in records
                if record.document_id == document.companion_document_id
            ),
            None,
        )
        if companion:
            preview_id = companion.document_id
            preview_format = companion.format
            representation = "companion plan rendered from this IFC model"
    elif document.format == "dxf":
        stem = PurePosixPath(document.path).stem
        parent = PurePosixPath(document.path).parent
        candidates = [
            record for record in records
            if PurePosixPath(record.path).parent == parent
            and PurePosixPath(record.path).stem == stem
            and record.format in {"pdf", "png", "svg"}
        ]
        if candidates:
            preview = next((record for record in candidates if record.format == "png"), candidates[0])
            preview_id = preview.document_id
            preview_format = preview.format
            representation = f"{preview.format.upper()} companion with the same drawing basename"
        else:
            preview_format = "svg"
            representation = "Faithful vector rendering generated from this DXF source"
    return {
        **document.model_dump(),
        "preview_document_id": preview_id,
        "preview_format": preview_format,
        "preview_relationship": representation,
    }


@app.get("/api/documents/{document_id}/license")
def document_license(document_id: str) -> dict[str, str]:
    try:
        document, _ = ingestion.find_document(document_id)
        text = ingestion.read_license(document)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Licence file could not be read: {exc}") from exc
    return {
        "path": document.license_file or "",
        "credit": document.license_credit or "",
        "text": text,
    }


def _scene_for_document(
    document: ingestion.DocumentRecord,
    path: Path,
    *,
    offset: int = 0,
    limit: int = 150,
    page_number: int = 1,
    selected_ids: list[str] | None = None,
) -> SceneResponse:
    try:
        return build_scene(
            document.document_id,
            document.path,
            path,
            document.format,
            offset=offset,
            limit=limit,
            page_number=page_number,
            selected_ids=selected_ids,
        )
    except SceneUnavailable as exc:
        return SceneResponse(
            document_id=document.document_id,
            source_path=document.path,
            source_format=document.format,
            status="unavailable",
            coordinate_system="unknown",
            unit="unknown",
            warnings=[str(exc)],
        )


@app.get("/api/documents/{document_id}/scene", response_model=SceneResponse)
def document_scene(
    document_id: str,
    offset: int = 0,
    limit: int = 150,
    page: int = 1,
) -> SceneResponse:
    if offset < 0 or not 1 <= limit <= 400 or page < 1:
        raise HTTPException(
            status_code=422,
            detail="Scene offset must be non-negative; limit must be 1–400; page starts at 1.",
        )
    try:
        document, path = ingestion.find_document(document_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _scene_for_document(
        document, path, offset=offset, limit=limit, page_number=page
    )


@app.post(
    "/api/documents/{document_id}/scene/elements",
    response_model=SceneResponse,
)
def selected_scene_elements(
    document_id: str, request: SceneSelectionRequest
) -> SceneResponse:
    try:
        document, path = ingestion.find_document(document_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if document.format != "ifc":
        raise HTTPException(
            status_code=415,
            detail="Selecting 3D geometry by GlobalId is supported only for IFC models.",
        )
    return _scene_for_document(
        document, path, selected_ids=request.element_ids
    )


@app.get("/api/documents/{document_id}/preview")
def document_preview(document_id: str, page: int = 1) -> Response:
    try:
        document, path = ingestion.find_document(document_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if page < 1:
        raise HTTPException(status_code=400, detail="Page numbers start at 1")
    if document.format == "pdf":
        try:
            image, width, height, page_count = ingestion.render_pdf_page(path, page)
        except ImportError as exc:
            raise HTTPException(status_code=503, detail="PyMuPDF is required to render PDF pages") from exc
        except IndexError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (RuntimeError, ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=f"PDF render failed: {exc}") from exc
        return Response(
            content=image,
            media_type="image/png",
            headers={
                "X-Page-Width": str(width),
                "X-Page-Height": str(height),
                "X-Page-Number": str(page),
                "X-Page-Count": str(page_count),
                "X-Coordinate-System": "pdf_points",
            },
        )
    if document.format == "dxf":
        try:
            preview = ingestion.render_dxf_preview(path)
        except ImportError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except (RuntimeError, ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return Response(
            content=preview.content,
            media_type="image/svg+xml",
            headers={
                "X-Page-Width": str(preview.width),
                "X-Page-Height": str(preview.height),
                "X-Page-Viewbox": ",".join(str(value) for value in preview.view_box),
                "X-Page-Number": "1",
                "X-Page-Count": "1",
                "X-Coordinate-System": "dxf_rendered_svg_viewbox",
            },
        )
    if document.format in {"png", "jpg", "jpeg", "svg"}:
        media_type = {
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "svg": "image/svg+xml",
        }[document.format]
        headers = {}
        if document.format in {"png", "jpg", "jpeg"}:
            try:
                from PIL import Image

                with Image.open(path) as image:
                    width, height = image.size
            except (ImportError, OSError, ValueError) as exc:
                raise HTTPException(status_code=422, detail=f"Raster preview failed: {exc}") from exc
            headers = {
                "X-Page-Width": str(width),
                "X-Page-Height": str(height),
                "X-Page-Number": "1",
                "X-Page-Count": "1",
                "X-Coordinate-System": "source_pixels_display_only",
            }
        if document.format == "svg":
            try:
                view_box = ingestion.read_svg_viewbox(path)
            except (OSError, ValueError) as exc:
                raise HTTPException(status_code=422, detail=f"SVG preview failed: {exc}") from exc
            if view_box:
                headers = {
                    "X-Page-Width": str(view_box[2]),
                    "X-Page-Height": str(view_box[3]),
                    "X-Page-Viewbox": ",".join(str(value) for value in view_box),
                    "X-Coordinate-System": "svg_viewbox",
                }
        return FileResponse(path, media_type=media_type, headers=headers)
    raise HTTPException(
        status_code=415,
        detail=f"No faithful 2D preview is implemented for {document.format.upper()}.",
    )


@app.post("/api/ask")
def ask(request: AskRequest) -> dict[str, Any]:
    try:
        document, path = ingestion.find_document(request.document_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    result = answer_question(
        document_id=document.document_id,
        relative_path=document.path,
        file_path=path,
        document_format=document.format,
        question=request.question.strip(),
        llm_config=request.llm,
        page_number=request.page_number,
        gemini_vl_consent=request.gemini_vl_consent,
    )
    return result.model_dump()


@app.post("/api/upload")
async def upload(request: Request) -> dict[str, Any]:
    filename = request.headers.get("x-filename", "")
    basename = PurePosixPath(filename.replace("\\", "/")).name
    extension = Path(basename).suffix.casefold()
    if not basename or basename in {".", ".."}:
        raise HTTPException(status_code=400, detail="A valid X-Filename header is required.")
    if extension not in ingestion.ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported upload format: {extension or 'no extension'}.",
        )
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > ingestion.MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Uploads are limited to 25 MiB.")
    chunks = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > ingestion.MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Uploads are limited to 25 MiB.")
        chunks.append(chunk)
    if size == 0:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", basename)[:120]
    ingestion.UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    target = ingestion.UPLOAD_ROOT / f"{uuid.uuid4().hex}_{safe_name}"
    target.write_bytes(b"".join(chunks))
    ingestion.list_documents.cache_clear()
    relative_path = f"upload/{target.name}"
    document = ingestion.build_document_record(
        relative_path, target, inspect_capabilities=False
    )
    return document.model_dump()
