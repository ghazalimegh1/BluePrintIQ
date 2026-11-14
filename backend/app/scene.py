from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path
from typing import Any

from .schemas import SceneElement, SceneRelationship, SceneResponse


IFC_SCENE_TYPES = (
    "IfcWall",
    "IfcSlab",
    "IfcDoor",
    "IfcWindow",
    "IfcColumn",
    "IfcBeam",
    "IfcStair",
    "IfcRailing",
    "IfcRamp",
    "IfcSpace",
)
IFC_DISPLAY_COLORS = {
    "IfcWall": "#91a5a5",
    "IfcWallStandardCase": "#91a5a5",
    "IfcSlab": "#748b92",
    "IfcDoor": "#d2a66c",
    "IfcWindow": "#61c5d0",
    "IfcColumn": "#ab9ace",
    "IfcBeam": "#83ad87",
    "IfcStair": "#b2a17a",
    "IfcRailing": "#b2a17a",
    "IfcRamp": "#b2a17a",
    "IfcSpace": "#70b79d",
}
RASTER_ROOM_LABELS = {
    "outdoor",
    "kitchen",
    "living room",
    "bedroom",
    "bath",
    "hallway",
    "storage",
    "garage",
    "other room",
}


class SceneUnavailable(RuntimeError):
    """Raised when a source cannot produce a real spatial scene."""


def _finite_vertices(values: Any) -> list[float]:
    result = [float(value) for value in values]
    if not result or len(result) % 3 or any(not math.isfinite(value) for value in result):
        raise SceneUnavailable("The geometry engine returned invalid vertex coordinates.")
    return result


def _ifc_products(model: Any) -> list[Any]:
    products: dict[int, Any] = {}
    for type_name in IFC_SCENE_TYPES:
        for product in model.by_type(type_name):
            if getattr(product, "Representation", None) is not None:
                products[product.id()] = product
    return sorted(
        products.values(),
        key=lambda product: (
            IFC_SCENE_TYPES.index(product.is_a())
            if product.is_a() in IFC_SCENE_TYPES
            else next(
                (
                    index for index, type_name in enumerate(IFC_SCENE_TYPES)
                    if product.is_a(type_name)
                ),
                len(IFC_SCENE_TYPES),
            ),
            product.id(),
        ),
    )


@lru_cache(maxsize=3)
def _ifc_model(path: str, modified_ns: int) -> Any:
    del modified_ns
    try:
        import ifcopenshell
    except ImportError as exc:
        raise SceneUnavailable("IFC geometry requires IfcOpenShell.") from exc
    try:
        return ifcopenshell.open(path)
    except (OSError, RuntimeError, ValueError) as exc:
        raise SceneUnavailable("The IFC file could not be opened for geometry extraction.") from exc


def _ifc_geometry(model: Any) -> Any:
    try:
        import ifcopenshell.geom
    except ImportError as exc:
        raise SceneUnavailable("IfcOpenShell geometry support is unavailable.") from exc
    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)
    return settings


def _element_geometry(
    settings: Any,
    product: Any,
    source_origin: tuple[float, float, float],
    document_id: str,
    relative_path: str,
) -> SceneElement:
    import ifcopenshell.geom
    from ifcopenshell.util.element import get_container

    shape = ifcopenshell.geom.create_shape(settings, product)
    geometry = shape.geometry
    original_vertices = _finite_vertices(geometry.verts)
    vertices: list[float] = []
    for index in range(0, len(original_vertices), 3):
        vertices.extend(
            round(original_vertices[index + axis] - source_origin[axis], 6)
            for axis in range(3)
        )
    indices = [int(value) for value in geometry.faces]
    if not indices or len(indices) % 3 or min(indices) < 0 or max(indices) >= len(vertices) // 3:
        raise SceneUnavailable("The geometry engine returned invalid triangle indices.")

    global_id = str(getattr(product, "GlobalId", "") or "")
    express_id = product.id()
    storey = get_container(product)
    relationships: list[SceneRelationship] = []
    if storey is not None and getattr(storey, "GlobalId", None):
        relationships.append(SceneRelationship(
            relationship_type="belongs_to_storey",
            target_id=str(storey.GlobalId),
            provenance_status="explicit",
            confidence=1.0,
        ))
    entity_type = product.is_a()
    name = str(getattr(product, "Name", "") or entity_type)
    properties: dict[str, dict[str, Any]] = {
        "entity_type": {"value": entity_type, "unit": None, "status": "explicit"},
        "global_id": {"value": global_id or None, "unit": None, "status": "explicit"},
    }
    if storey is not None:
        properties["storey"] = {
            "value": str(getattr(storey, "Name", "") or storey.is_a()),
            "unit": None,
            "status": "explicit",
        }
    predefined_type = getattr(product, "PredefinedType", None)
    if predefined_type:
        properties["predefined_type"] = {
            "value": str(predefined_type),
            "unit": None,
            "status": "explicit",
        }
    return SceneElement(
        id=f"ifc:{global_id or express_id}",
        global_id=global_id or None,
        entity_type=entity_type,
        name=name,
        geometry_kind="triangle_mesh",
        vertices=vertices,
        indices=indices,
        coordinate_system="ifc_world_m",
        unit="m",
        properties=properties,
        relationships=relationships,
        provenance={
            "method": "IfcOpenShell native IFC tessellation",
            "source_document_id": document_id,
            "source_path": relative_path,
            "source_entity_id": global_id or f"#{express_id}",
            "source_entity_type": entity_type,
            "source_coordinate_system": "ifc_world_m",
            "source_region": None,
            "confidence": 1.0,
            "status": "explicit",
            "display_color": IFC_DISPLAY_COLORS.get(entity_type, "#8ca2a4"),
            "source_tool": "ifcopenshell.geom",
        },
    )


def build_ifc_scene(
    document_id: str,
    relative_path: str,
    path: Path,
    *,
    offset: int = 0,
    limit: int = 150,
    selected_ids: list[str] | None = None,
) -> SceneResponse:
    model = _ifc_model(str(path.resolve()), path.stat().st_mtime_ns)
    products = _ifc_products(model)
    if not products:
        raise SceneUnavailable("The IFC file contains no supported products with geometry.")

    settings = _ifc_geometry(model)
    origin_product = products[0]
    try:
        origin_shape = _element_geometry_raw(settings, origin_product)
    except (RuntimeError, TypeError, ValueError) as exc:
        raise SceneUnavailable("The IFC model origin could not be established from its geometry.") from exc
    origin_vertices = _finite_vertices(origin_shape.verts)
    source_origin = tuple(origin_vertices[:3])

    if selected_ids is not None:
        requested = list(dict.fromkeys(selected_ids))
        selected_products = []
        not_found: list[str] = []
        for element_id in requested:
            global_id = element_id.removeprefix("ifc:")
            try:
                product = model.by_guid(global_id)
            except (RuntimeError, ValueError):
                product = None
            if product is None or not product.is_a("IfcProduct") or not getattr(product, "Representation", None):
                not_found.append(element_id)
            else:
                selected_products.append(product)
        total_elements = len(selected_products)
        products_to_render = selected_products
        warnings = (
            [f"{len(not_found)} selected element reference(s) were not present in the IFC geometry."]
            if not_found else []
        )
    else:
        total_elements = len(products)
        products_to_render = products[offset : offset + limit]
        warnings = []

    elements: list[SceneElement] = []
    failures = 0
    for product in products_to_render:
        try:
            elements.append(_element_geometry(
                settings, product, source_origin, document_id, relative_path
            ))
        except (RuntimeError, TypeError, ValueError, SceneUnavailable):
            failures += 1
    if failures:
        warnings.append(f"{failures} IFC element(s) had unsupported or invalid geometry and were omitted.")
    if not elements:
        raise SceneUnavailable("No supported IFC element geometry could be tessellated.")
    if selected_ids is not None and warnings:
        status = "partial"
    elif failures:
        status = "partial"
    else:
        status = "ready"
    has_more = selected_ids is None and offset + len(products_to_render) < total_elements
    return SceneResponse(
        document_id=document_id,
        source_path=relative_path,
        source_format="ifc",
        status=status,
        coordinate_system="ifc_world_m",
        unit="m",
        source_origin=list(source_origin),
        total_elements=total_elements,
        offset=offset,
        limit=limit,
        has_more=has_more,
        elements=elements,
        warnings=warnings,
    )


def _element_geometry_raw(settings: Any, product: Any) -> Any:
    import ifcopenshell.geom

    return ifcopenshell.geom.create_shape(settings, product).geometry


def _extrude_raster_region(
    polygon: Any,
    height: float,
) -> tuple[list[float], list[int]]:
    from shapely.geometry import Polygon
    from shapely.ops import triangulate

    geometry = polygon if polygon.is_valid else polygon.buffer(0)
    polygons = [geometry] if isinstance(geometry, Polygon) else list(getattr(geometry, "geoms", []))
    vertices: list[float] = []
    indices: list[int] = []

    def add_vertex(x: float, y: float, z: float) -> int:
        vertices.extend((round(float(x), 3), round(float(y), 3), round(float(z), 3)))
        return len(vertices) // 3 - 1

    for item in polygons:
        if not isinstance(item, Polygon) or item.is_empty or item.area <= 1:
            continue
        for triangle in triangulate(item):
            if not item.covers(triangle):
                continue
            coordinates = list(triangle.exterior.coords)[:3]
            bottom = [add_vertex(x, y, 0) for x, y in coordinates]
            top = [add_vertex(x, y, height) for x, y in coordinates]
            indices.extend((bottom[0], bottom[2], bottom[1], top[0], top[1], top[2]))
        for ring in (item.exterior, *item.interiors):
            points = list(ring.coords)
            for first, second in zip(points, points[1:]):
                low_a = add_vertex(first[0], first[1], 0)
                low_b = add_vertex(second[0], second[1], 0)
                high_b = add_vertex(second[0], second[1], height)
                high_a = add_vertex(first[0], first[1], height)
                indices.extend((low_a, low_b, high_b, low_a, high_b, high_a))
    return vertices, indices


def build_raster_scene(
    document_id: str,
    relative_path: str,
    path: Path,
    document_format: str,
    *,
    page_number: int = 1,
) -> SceneResponse:
    try:
        from shapely.geometry import Polygon
        from .vision_models import (
            VisionInferenceError,
            load_source_image,
            retain_significant_room_regions,
            segment_floorplan_cubicasa,
        )
    except ImportError as exc:
        raise SceneUnavailable("Raster reconstruction requires Shapely and the local vision dependencies.") from exc
    try:
        source = load_source_image(path, document_format, page_number)
        regions = segment_floorplan_cubicasa(source)
    except VisionInferenceError as exc:
        raise SceneUnavailable(str(exc)) from exc
    if not regions:
        raise SceneUnavailable("CubiCasa did not return any floor-plan regions for this page.")
    regions = retain_significant_room_regions(
        regions, source.native_width, source.native_height
    )

    # Keep the raster scene legible as a plan. Pixel coordinates are not a
    # metric scale, so these heights are deliberately conservative display
    # proportions rather than invented building dimensions.
    display_height = max(8.0, min(24.0, max(source.image.size) * 0.03))
    elements: list[SceneElement] = []
    region_records: list[tuple[dict[str, Any], SceneElement, Any]] = []
    for index, region in enumerate(regions):
        label = str(region["label"]).casefold()
        # CubiCasa's outdoor mask is useful for source overlays, but turning
        # it into a solid 3D slab makes the building look like two floating
        # platforms. Preserve it as evidence in answer overlays, not as a
        # building element in the spatial inspection view.
        if label == "outdoor":
            continue
        points = region.get("points", [])
        if len(points) < 3:
            continue
        polygon = Polygon(points)
        is_room = label in RASTER_ROOM_LABELS
        is_symbol = not is_room and label != "wall"
        height = (
            display_height * 0.55
            if label == "wall"
            else 2.5
            if is_symbol
            else 0.35
        )
        try:
            vertices, indices = _extrude_raster_region(polygon, height)
        except (ValueError, TypeError):
            continue
        if not vertices or not indices:
            continue
        region_id = f"{document_id}:page-{page_number}:{label}:{index}"
        evidence_id = f"{document_id}-mask-p{page_number}-{index}"
        category = "room" if is_room else label
        element = SceneElement(
            id=region_id,
            entity_type=category,
            name=f"{label.title()} region {index + 1}",
            geometry_kind="triangle_mesh",
            vertices=vertices,
            indices=indices,
            coordinate_system="source_pixels_display_only",
            unit="px",
            properties={
                "floor_area": {
                    "value": None,
                    "unit": "m2",
                    "status": "unknown",
                },
                "height": {
                    "value": None,
                    "unit": "m",
                    "status": "unknown",
                },
                "display_height": {
                    "value": height,
                    "unit": "px",
                    "status": "illustrative",
                },
                "geometry_role": {
                    "value": "room_floor" if is_room else "wall_mass" if label == "wall" else "detected_symbol",
                    "unit": None,
                    "status": "explicit",
                },
                "source_area": {
                    "value": round(float(polygon.area), 3),
                    "unit": "px2",
                    "status": "measured",
                },
                "evidence_id": {
                    "value": evidence_id,
                    "unit": None,
                    "status": "explicit",
                },
            },
            provenance={
                "method": "CubiCasa5K pretrained floor-plan segmentation",
                "source_document_id": document_id,
                "source_path": relative_path,
                "page_or_sheet": page_number,
                "source_region": region.get("bbox"),
                "source_evidence_id": evidence_id,
                "source_coordinate_system": source.coordinate_system,
                "confidence": float(region["score"]),
                "status": "detected",
                "display_color": "#55c8ad" if is_room else (
                    "#d0a05f" if label == "wall" else "#60b8d0"
                ),
                "source_tool": "cubicasa_floorplan_segmentation",
            },
        )
        elements.append(element)
        region_records.append((region, element, polygon))
    if not elements:
        raise SceneUnavailable("CubiCasa regions could not be converted into valid spatial geometry.")

    # Build only relationships supported by the detected 2D polygons. An icon is
    # associated with a room when its centroid is inside that room polygon; this
    # is a source-pixel relationship, not a claim about a physical BIM topology.
    room_records = [
        (element, polygon)
        for _, element, polygon in region_records
        if element.entity_type == "room"
    ]
    for _, element, polygon in region_records:
        if element.entity_type == "room":
            continue
        centroid = polygon.representative_point()
        containing_room = next(
            (
                room
                for room, room_polygon in room_records
                if room_polygon.covers(centroid)
            ),
            None,
        )
        if containing_room is not None:
            element.relationships.append(SceneRelationship(
                relationship_type="detected_inside_room",
                target_id=containing_room.id,
                provenance_status="detected",
                confidence=min(
                    float(element.provenance.get("confidence", 0.0)),
                    float(containing_room.provenance.get("confidence", 0.0)),
                ),
            ))
    return SceneResponse(
        document_id=document_id,
        source_path=relative_path,
        source_format=document_format,
        status="partial",
        coordinate_system="source_pixels_display_only",
        unit="px",
        source_origin=[0.0, 0.0, 0.0],
        total_elements=len(elements),
        limit=len(elements),
        elements=elements,
        warnings=[
            "This source-grounded hybrid view uses detected floor-plan polygons plus deterministic extrusion. Heights are illustrative, image scale is unknown, and geometry is not suitable for metric quantities."
        ],
    )


def build_scene(
    document_id: str,
    relative_path: str,
    path: Path,
    document_format: str,
    *,
    offset: int = 0,
    limit: int = 150,
    page_number: int = 1,
    selected_ids: list[str] | None = None,
) -> SceneResponse:
    normalized_format = document_format.casefold()
    if normalized_format == "ifc":
        return build_ifc_scene(
            document_id,
            relative_path,
            path,
            offset=offset,
            limit=limit,
            selected_ids=selected_ids,
        )
    if normalized_format in {"pdf", "png", "jpg", "jpeg"}:
        return build_raster_scene(
            document_id,
            relative_path,
            path,
            normalized_format,
            page_number=page_number,
        )
    return SceneResponse(
        document_id=document_id,
        source_path=relative_path,
        source_format=normalized_format,
        status="unavailable",
        coordinate_system="unknown",
        unit="unknown",
        warnings=[f"No 3D scene adapter is implemented for {normalized_format.upper()} sources."],
    )
