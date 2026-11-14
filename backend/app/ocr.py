from __future__ import annotations

import importlib.util
import math
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


DETECTION_MODEL = "craft_mlt_25k.pth"
ENGLISH_RECOGNITION_MODEL = "english_g2.pth"
MAX_OCR_PIXELS = 16_000_000


class OCRUnavailable(RuntimeError):
    pass


class OCRError(RuntimeError):
    pass


@dataclass(frozen=True)
class OCRLine:
    text: str
    confidence: float
    bbox: tuple[float, float, float, float]


def _model_directory() -> Path:
    configured = os.getenv("STOA_OCR_MODEL_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".EasyOCR" / "model"


def _download_enabled() -> bool:
    value = os.getenv("STOA_OCR_DOWNLOAD_MODELS", "").strip().casefold()
    if value not in {"", "0", "false", "no", "1", "true", "yes"}:
        raise OCRError("STOA_OCR_DOWNLOAD_MODELS must be set to true or false.")
    return value in {"1", "true", "yes"}


def ocr_is_available() -> bool:
    if any(
        importlib.util.find_spec(module) is None
        for module in ("easyocr", "numpy", "torch")
    ):
        return False
    if _download_enabled():
        return True
    model_directory = _model_directory()
    return (
        (model_directory / DETECTION_MODEL).is_file()
        and (model_directory / ENGLISH_RECOGNITION_MODEL).is_file()
    )


def paddle_ocr_is_available() -> bool:
    dependencies_available = all(
        importlib.util.find_spec(module) is not None
        for module in ("paddle", "paddleocr", "numpy")
    )
    if not dependencies_available:
        return False
    from .vision_models import paddle_ocr_models_cached

    return paddle_ocr_models_cached() or _download_enabled()


def extract_paddle_ocr_lines(image: Any) -> list[OCRLine]:
    if not paddle_ocr_is_available():
        raise OCRUnavailable(
            "PaddleOCR is not installed. Install PaddlePaddle and requirements-vision-ocr.txt."
        )
    from .vision_models import VisionInferenceError, run_paddle_ocr

    try:
        regions = run_paddle_ocr(image)
    except VisionInferenceError as exc:
        raise OCRError(str(exc)) from exc
    lines: list[OCRLine] = []
    for region in regions:
        try:
            text = str(region["text"]).strip()
            score = float(region["score"])
            bbox = tuple(float(value) for value in region["bbox"])
        except (KeyError, TypeError, ValueError):
            continue
        if (
            not text
            or len(bbox) != 4
            or not math.isfinite(score)
            or not 0 <= score <= 1
            or any(not math.isfinite(value) for value in bbox)
        ):
            continue
        x0 = max(0.0, min(float(image.width), bbox[0]))
        y0 = max(0.0, min(float(image.height), bbox[1]))
        x1 = max(0.0, min(float(image.width), bbox[2]))
        y1 = max(0.0, min(float(image.height), bbox[3]))
        if x1 > x0 and y1 > y0:
            lines.append(OCRLine(text, score, (x0, y0, x1, y1)))
    return lines


@lru_cache(maxsize=1)
def _reader(model_directory: str, download_enabled: bool) -> Any:
    try:
        import easyocr
    except ImportError as exc:
        raise OCRUnavailable(
            "EasyOCR is not installed. Install the optional OCR requirements first."
        ) from exc

    directory = Path(model_directory)
    if not download_enabled and not (
        (directory / DETECTION_MODEL).is_file()
        and (directory / ENGLISH_RECOGNITION_MODEL).is_file()
    ):
        raise OCRUnavailable(
            "English OCR model weights are missing. Install them locally or explicitly "
            "enable first-use downloads with STOA_OCR_DOWNLOAD_MODELS=true."
        )
    try:
        directory.mkdir(parents=True, exist_ok=True)
        return easyocr.Reader(
            ["en"],
            gpu=False,
            model_storage_directory=str(directory),
            download_enabled=download_enabled,
            verbose=False,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise OCRError(f"EasyOCR could not initialize its English model: {exc}") from exc


def extract_ocr_lines(image: Any) -> list[OCRLine]:
    if image.width <= 0 or image.height <= 0:
        raise OCRError("OCR source image has invalid dimensions.")
    if image.width * image.height > MAX_OCR_PIXELS:
        raise OCRError("OCR is limited to 16 megapixels per page.")

    try:
        import numpy
    except ImportError as exc:
        raise OCRUnavailable("NumPy is required by the optional EasyOCR engine.") from exc

    download_enabled = _download_enabled()
    reader = _reader(str(_model_directory()), download_enabled)
    try:
        detections = reader.readtext(
            numpy.asarray(image.convert("RGB")),
            detail=1,
            paragraph=False,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise OCRError(f"EasyOCR could not process the source image: {exc}") from exc

    lines: list[OCRLine] = []
    for detection in detections:
        if not isinstance(detection, (tuple, list)) or len(detection) < 3:
            continue
        polygon, text, confidence = detection[:3]
        if not isinstance(text, str) or not text.strip():
            continue
        try:
            points = [
                (float(point[0]), float(point[1]))
                for point in polygon
            ]
            score = float(confidence)
        except (TypeError, ValueError, IndexError):
            continue
        if (
            len(points) < 4
            or not math.isfinite(score)
            or not 0 <= score <= 1
            or any(not math.isfinite(value) for point in points for value in point)
        ):
            continue
        x_values = [max(0.0, min(float(image.width), point[0])) for point in points]
        y_values = [max(0.0, min(float(image.height), point[1])) for point in points]
        bbox = (min(x_values), min(y_values), max(x_values), max(y_values))
        if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
            continue
        lines.append(OCRLine(text=text.strip(), confidence=score, bbox=bbox))
    return lines
