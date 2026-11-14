"""Small, explainable classical-CV primitives for drawing analysis.

These routines produce geometric candidates only. They deliberately do not
assign architectural labels or claim object counts.
"""

from __future__ import annotations

from typing import Any


class ClassicalCVUnavailable(RuntimeError):
    """OpenCV/NumPy is not installed for the optional classical route."""


def analyze_plan_image(
    image: Any,
    *,
    max_lines: int = 80,
    max_components: int = 80,
) -> dict[str, Any]:
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise ClassicalCVUnavailable(
            "Classical drawing analysis requires the optional OpenCV and NumPy dependencies."
        ) from exc

    if image.width < 1 or image.height < 1:
        raise ValueError("The drawing has invalid dimensions.")
    rgb = np.asarray(image.convert("RGB"))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150, apertureSize=3)
    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 180,
        threshold=max(30, min(image.width, image.height) // 12),
        minLineLength=max(25, min(image.width, image.height) // 20),
        maxLineGap=max(5, min(image.width, image.height) // 100),
    )
    line_records: list[dict[str, Any]] = []
    if lines is not None:
        candidates = []
        for raw in lines.reshape(-1, 4):
            x0, y0, x1, y1 = (int(value) for value in raw)
            length = float(((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5)
            angle = float(np.degrees(np.arctan2(y1 - y0, x1 - x0)) % 180)
            candidates.append((length, {
                "points": [[x0, y0], [x1, y1]],
                "length_pixels": round(length, 3),
                "angle_degrees": round(angle, 3),
            }))
        for _, record in sorted(candidates, key=lambda item: item[0], reverse=True)[:max_lines]:
            line_records.append(record)

    binary = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV,  blockSize=31, C=7
    )
    kernel = np.ones((3, 3), dtype=np.uint8)
    cleaned = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel, iterations=1)
    count, labels, stats, centroids = cv2.connectedComponentsWithStats(cleaned, connectivity=8)
    component_records: list[dict[str, Any]] = []
    for index in range(1, count):
        x, y, width, height, area = (int(value) for value in stats[index])
        if area < 20:
            continue
        component_records.append({
            "bbox": [x, y, x + width, y + height],
            "area_pixels": area,
            "centroid": [round(float(centroids[index][0]), 3), round(float(centroids[index][1]), 3)],
        })
    component_records.sort(key=lambda item: item["area_pixels"], reverse=True)
    edge_density = float(np.count_nonzero(edges)) / float(edges.size)
    return {
        "lines": line_records,
        "components": component_records[:max_components],
        "edge_density": round(edge_density, 6),
        "image_width": image.width,
        "image_height": image.height,
    }
