from __future__ import annotations

import importlib.util
import math
import os
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageOps

from .gemini_vision import gemini_vl_configured
from .ingestion import render_pdf_page


GROUNDING_DINO_MODEL = "IDEA-Research/grounding-dino-tiny"
SAM2_MODEL = "facebook/sam2.1-hiera-small"


class VisionInferenceError(RuntimeError):
    """A specialist vision capability is unavailable or failed."""


@dataclass(frozen=True)
class ImageTile:
    image: Image.Image
    x: int
    y: int
    index: int


@dataclass(frozen=True)
class Detection:
    label: str
    score: float
    bbox: tuple[float, float, float, float]
    tile: ImageTile
    tile_bbox: tuple[float, float, float, float]


@dataclass(frozen=True)
class SourceImage:
    image: Image.Image
    coordinate_system: str
    native_width: float
    native_height: float
    page_number: int

    @property
    def scale_x(self) -> float:
        return self.native_width / self.image.width

    @property
    def scale_y(self) -> float:
        return self.native_height / self.image.height


def capability_status() -> dict[str, bool]:
    def cached_weights(model_id: str) -> bool:
        try:
            from huggingface_hub import try_to_load_from_cache
        except ImportError:
            return False
        cached = try_to_load_from_cache(model_id, "model.safetensors")
        return isinstance(cached, str) and Path(cached).is_file()

    dependencies = all(
        importlib.util.find_spec(module) is not None
        for module in ("torch", "transformers", "safetensors")
    )
    paddle_dependencies = all(
        importlib.util.find_spec(module) is not None
        for module in ("paddle", "paddleocr", "numpy")
    )
    paddle_downloads_enabled = (
        os.getenv("STOA_OCR_DOWNLOAD_MODELS", "").strip().lower()
        in {"1", "true", "yes"}
    )
    return {
        "grounding_dino": dependencies and cached_weights(GROUNDING_DINO_MODEL),
        "sam2": dependencies
        and importlib.util.find_spec("cv2") is not None
        and cached_weights(SAM2_MODEL),
        "paddle_ocr": paddle_dependencies
        and (paddle_ocr_models_cached() or paddle_downloads_enabled),
        "cubicasa": cubicasa_configured(),
        "gemini_vl": gemini_vl_configured(),
    }


def paddle_ocr_models_cached() -> bool:
    cache_dir = Path(
        os.getenv("PADDLE_PDX_CACHE_HOME", str(Path.home() / ".paddlex"))
    )
    official_models = cache_dir / "official_models"
    return all(
        (official_models / model_name / "inference.json").is_file()
        and (official_models / model_name / "inference.pdiparams").is_file()
        for model_name in ("PP-OCRv6_medium_det", "PP-OCRv6_medium_rec")
    )


def cubicasa_configured() -> bool:
    source = os.getenv("STOA_CUBICASA_SOURCE_DIR")
    checkpoint = os.getenv("STOA_CUBICASA_CHECKPOINT")
    return bool(
        source
        and checkpoint
        and (Path(source) / "floortrans" / "models").is_dir()
        and Path(checkpoint).is_file()
    )


def _environment_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise VisionInferenceError(f"{name} must be an integer.") from exc
    if not minimum <= value <= maximum:
        raise VisionInferenceError(f"{name} must be between {minimum} and {maximum}.")
    return value


def _environment_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError as exc:
        raise VisionInferenceError(f"{name} must be a number.") from exc
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise VisionInferenceError(f"{name} must be between {minimum} and {maximum}.")
    return value


def make_tiles(
    image: Image.Image,
    *,
    tile_size: int = 1024,
    overlap: int = 160,
    max_tiles: int | None = None,
) -> list[ImageTile]:
    if tile_size < 128 or overlap < 0 or overlap >= tile_size:
        raise ValueError("Tile size must be at least 128 and overlap must be smaller than tile size.")
    step = tile_size - overlap
    xs = list(range(0, max(1, image.width - tile_size + 1), step))
    ys = list(range(0, max(1, image.height - tile_size + 1), step))
    if not xs or xs[-1] + tile_size < image.width:
        xs.append(max(0, image.width - tile_size))
    if not ys or ys[-1] + tile_size < image.height:
        ys.append(max(0, image.height - tile_size))
    tiles = [
        ImageTile(
            image=image.crop((x, y, min(image.width, x + tile_size), min(image.height, y + tile_size))),
            x=x,
            y=y,
            index=index,
        )
        for index, (y, x) in enumerate((y, x) for y in ys for x in xs)
    ]
    if max_tiles is not None and len(tiles) > max_tiles:
        raise VisionInferenceError(
            f"High-resolution drawing needs {len(tiles)} tiles; the configured limit is {max_tiles}."
        )
    return tiles


def load_source_image(path: Path, document_format: str, page_number: int = 1) -> SourceImage:
    if document_format == "pdf":
        try:
            data, page_width, page_height, _ = render_pdf_page(path, page_number)
        except IndexError as exc:
            raise VisionInferenceError(str(exc)) from exc
        except (OSError, RuntimeError, ValueError, ImportError) as exc:
            raise VisionInferenceError("The selected PDF page could not be rendered.") from exc
        try:
            import io

            with Image.open(io.BytesIO(data)) as source:
                image = source.convert("RGB")
        except (OSError, ValueError) as exc:
            raise VisionInferenceError("The selected PDF page could not be decoded.") from exc
        native_width, native_height = page_width, page_height
        coordinate_system = "pdf_points"
    elif document_format in {"png", "jpg", "jpeg"}:
        try:
            with Image.open(path) as source:
                if source.width * source.height > 64_000_000:
                    raise VisionInferenceError("Image exceeds the 64-megapixel processing limit.")
                image = ImageOps.exif_transpose(source).convert("RGB")
        except (OSError, ValueError) as exc:
            raise VisionInferenceError("The raster drawing could not be decoded.") from exc
        native_width, native_height = image.size
        coordinate_system = "image_pixels"
    else:
        raise VisionInferenceError(f"Raster vision is not supported for {document_format.upper()}.")
    if image.width < 1 or image.height < 1:
        raise VisionInferenceError("The selected drawing has invalid dimensions.")
    return SourceImage(image, coordinate_system, native_width, native_height, page_number)


def _iou(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> float:
    x0 = max(first[0], second[0])
    y0 = max(first[1], second[1])
    x1 = min(first[2], second[2])
    y1 = min(first[3], second[3])
    intersection = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    first_area = max(0.0, first[2] - first[0]) * max(0.0, first[3] - first[1])
    second_area = max(0.0, second[2] - second[0]) * max(0.0, second[3] - second[1])
    union = first_area + second_area - intersection
    return intersection / union if union else 0.0


def suppress_duplicate_detections(
    detections: Iterable[Detection], threshold: float = 0.5
) -> list[Detection]:
    ordered = sorted(detections, key=lambda item: item.score, reverse=True)
    kept: list[Detection] = []
    for candidate in ordered:
        if all(
            candidate.label.casefold() != existing.label.casefold()
            or _iou(candidate.bbox, existing.bbox) <= threshold
            for existing in kept
        ):
            kept.append(candidate)
    return kept


@lru_cache(maxsize=1)
def _load_grounding_dino() -> tuple[Any, Any, Any]:
    try:
        import torch
        from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor
    except ImportError as exc:
        raise VisionInferenceError(
            "Grounding DINO requires the optional requirements-vision.txt dependencies."
        ) from exc
    local_only = os.getenv("STOA_VISION_DOWNLOAD_MODELS", "false").casefold() != "true"
    try:
        processor = AutoProcessor.from_pretrained(
            GROUNDING_DINO_MODEL, local_files_only=local_only
        )
        model = AutoModelForZeroShotObjectDetection.from_pretrained(
            GROUNDING_DINO_MODEL,
            local_files_only=local_only,
            use_safetensors=True,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        detail = (
            "Pretrained Grounding DINO weights are not cached. Run "
            "`python scripts/download_vision_models.py --models grounding-dino-tiny`."
            if local_only
            else "Grounding DINO weights could not be downloaded or loaded."
        )
        raise VisionInferenceError(detail) from exc
    device = os.getenv("STOA_VISION_DEVICE", "cpu").strip() or "cpu"
    try:
        model.to(device)
    except (RuntimeError, ValueError) as exc:
        raise VisionInferenceError(f"Grounding DINO could not use device {device}.") from exc
    model.eval()
    return torch, processor, model


def detect_objects(
    source: SourceImage,
    labels: list[str],
    *,
    threshold: float | None = None,
) -> list[Detection]:
    if not labels:
        raise VisionInferenceError("Object detection requires at least one recognized entity label.")
    torch, processor, model = _load_grounding_dino()
    score_threshold = threshold if threshold is not None else _environment_float(
        "STOA_DINO_CONFIDENCE_THRESHOLD", 0.35, 0.05, 0.95
    )
    tile_size = _environment_int("STOA_VISION_TILE_SIZE", 1024, 128, 4096)
    overlap = _environment_int("STOA_VISION_TILE_OVERLAP", 160, 0, tile_size - 1)
    max_tiles = _environment_int("STOA_VISION_MAX_TILES", 32, 1, 512)
    tiles = make_tiles(
        source.image, tile_size=tile_size, overlap=overlap, max_tiles=max_tiles
    )
    prompts = [f"a {label}." for label in labels]
    detections: list[Detection] = []
    for tile in tiles:
        inputs = processor(
            images=tile.image,
            text=" ".join(prompts),
            return_tensors="pt",
        )
        try:
            inputs = inputs.to(model.device)
        except AttributeError:
            pass
        with torch.inference_mode():
            outputs = model(**inputs)
        postprocess = getattr(processor, "post_process_grounded_object_detection", None)
        if postprocess is None:
            raise VisionInferenceError("Installed Transformers lacks Grounding DINO post-processing.")
        results = postprocess(
            outputs,
            inputs.input_ids,
            threshold=score_threshold,
            text_threshold=score_threshold,
            target_sizes=[(tile.image.height, tile.image.width)],
        )
        if not results:
            continue
        result = results[0]
        boxes = result.get("boxes", [])
        scores = result.get("scores", [])
        names = result.get("text_labels", result.get("labels", []))
        for box, score, name in zip(boxes, scores, names):
            coordinates = box.tolist() if hasattr(box, "tolist") else list(box)
            confidence = float(score.item() if hasattr(score, "item") else score)
            label = str(name).strip().rstrip(".")
            if (
                len(coordinates) != 4
                or not math.isfinite(confidence)
                or not score_threshold <= confidence <= 1
                or not label
            ):
                continue
            x0, y0, x1, y1 = (float(value) for value in coordinates)
            if x1 <= x0 or y1 <= y0:
                continue
            tile_bbox = (x0, y0, x1, y1)
            scale_x, scale_y = source.scale_x, source.scale_y
            bbox = (
                (tile.x + x0) * scale_x,
                (tile.y + y0) * scale_y,
                (tile.x + x1) * scale_x,
                (tile.y + y1) * scale_y,
            )
            detections.append(Detection(label, confidence, bbox, tile, tile_bbox))
    return suppress_duplicate_detections(detections)


@lru_cache(maxsize=1)
def _load_sam2() -> tuple[Any, Any, Any]:
    try:
        import torch
        from transformers import Sam2Model, Sam2Processor
    except ImportError as exc:
        raise VisionInferenceError(
            "SAM 2 requires the optional requirements-vision.txt dependencies."
        ) from exc
    local_only = os.getenv("STOA_VISION_DOWNLOAD_MODELS", "false").casefold() != "true"
    try:
        processor = Sam2Processor.from_pretrained(SAM2_MODEL, local_files_only=local_only)
        model = Sam2Model.from_pretrained(
            SAM2_MODEL, local_files_only=local_only, use_safetensors=True
        )
    except (OSError, ValueError, RuntimeError) as exc:
        detail = (
            "Pretrained SAM 2.1 weights are not cached. Run "
            "`python scripts/download_vision_models.py --models sam2.1-hiera-small`."
            if local_only
            else "SAM 2.1 weights could not be downloaded or loaded."
        )
        raise VisionInferenceError(detail) from exc
    device = os.getenv("STOA_VISION_DEVICE", "cpu").strip() or "cpu"
    try:
        model.to(device)
    except (RuntimeError, ValueError) as exc:
        raise VisionInferenceError(f"SAM 2 could not use device {device}.") from exc
    model.eval()
    return torch, processor, model


def segment_detections(
    source: SourceImage, detections: list[Detection]
) -> list[tuple[Detection, list[list[list[float]]], float]]:
    if not detections:
        return []
    torch, processor, model = _load_sam2()
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise VisionInferenceError("SAM 2 mask serialization requires OpenCV and NumPy.") from exc

    segmented: list[tuple[Detection, list[list[list[float]]], float]] = []
    tile_groups: dict[int, list[Detection]] = {}
    for detection in detections:
        tile_groups.setdefault(detection.tile.index, []).append(detection)
    for group in tile_groups.values():
        tile = group[0].tile
        boxes = [[list(detection.tile_bbox) for detection in group]]
        inputs = processor(images=tile.image, input_boxes=boxes, return_tensors="pt")
        try:
            inputs = inputs.to(model.device)
        except AttributeError:
            pass
        with torch.inference_mode():
            outputs = model(**inputs)
        masks = processor.post_process_masks(outputs.pred_masks, inputs["original_sizes"])
        if not masks:
            continue
        mask_batch = masks[0]
        scores = getattr(outputs, "iou_scores", None)
        for index, detection in enumerate(group):
            candidates = mask_batch[index]
            if hasattr(candidates, "detach"):
                candidates = candidates.detach().cpu().numpy()
            if candidates.ndim == 2:
                candidates = candidates[None, ...]
            score_values = (
                scores[index].detach().cpu().numpy().reshape(-1)
                if scores is not None
                else [1.0] * len(candidates)
            )
            best_index = int(np.argmax(score_values))
            confidence = float(score_values[best_index])
            if not math.isfinite(confidence) or confidence < 0.25:
                continue
            mask = (candidates[best_index] > 0).astype("uint8")
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if not contours:
                continue
            contour = max(contours, key=cv2.contourArea)
            if cv2.contourArea(contour) < 4:
                continue
            epsilon = max(1.0, 0.002 * cv2.arcLength(contour, True))
            contour = cv2.approxPolyDP(contour, epsilon, True).reshape(-1, 2)
            points = [
                [
                    (tile.x + float(x)) * source.scale_x,
                    (tile.y + float(y)) * source.scale_y,
                ]
                for x, y in contour
            ]
            if len(points) >= 3:
                segmented.append((detection, [points], confidence))
    return segmented


@lru_cache(maxsize=1)
def _load_cubicasa() -> tuple[Any, Any, Any]:
    try:
        import torch
    except ImportError as exc:
        raise VisionInferenceError("CubiCasa inference requires PyTorch.") from exc
    source_dir = os.getenv("STOA_CUBICASA_SOURCE_DIR", "").strip()
    checkpoint_path = os.getenv("STOA_CUBICASA_CHECKPOINT", "").strip()
    if not cubicasa_configured():
        raise VisionInferenceError(
            "CubiCasa requires the official source checkout and checkpoint; see docs/ARCHITECTURE.md."
        )
    source_path = str(Path(source_dir).resolve())
    if source_path not in sys.path:
        sys.path.insert(0, source_path)
    try:
        from floortrans.models.hg_furukawa_original import hg_furukawa_original
    except ImportError as exc:
        raise VisionInferenceError(
            "The configured CubiCasa source checkout is missing its official model implementation."
        ) from exc
    try:
        checkpoint = torch.load(
            checkpoint_path, map_location="cpu", weights_only=True
        )
        state = checkpoint.get("model_state", checkpoint) if isinstance(checkpoint, dict) else checkpoint
        model = hg_furukawa_original(n_classes=44)
        model.load_state_dict(state)
        model.eval()
    except (OSError, RuntimeError, ValueError, TypeError) as exc:
        raise VisionInferenceError(
            "The CubiCasa checkpoint could not be loaded with the configured official model source."
        ) from exc
    device = os.getenv("STOA_VISION_DEVICE", "cpu").strip() or "cpu"
    try:
        model.to(device)
    except (RuntimeError, ValueError) as exc:
        raise VisionInferenceError(f"CubiCasa could not use device {device}.") from exc
    return torch, model, device


def segment_floorplan_cubicasa(source: SourceImage) -> list[dict[str, Any]]:
    torch, model, _ = _load_cubicasa()
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise VisionInferenceError("CubiCasa mask extraction requires OpenCV and NumPy.") from exc

    max_side = _environment_int("STOA_CUBICASA_MAX_SIDE", 1024, 256, 2048)
    scale = min(1.0, max_side / max(source.image.size))
    width = max(64, int(source.image.width * scale))
    height = max(64, int(source.image.height * scale))
    width = max(64, width - width % 64)
    height = max(64, height - height % 64)
    resized = source.image.resize((width, height), Image.Resampling.LANCZOS)
    pixels = np.asarray(resized, dtype=np.float32)
    tensor = torch.from_numpy((pixels.transpose(2, 0, 1) / 127.5) - 1.0).unsqueeze(0)
    try:
        tensor = tensor.to(model.conv1_.weight.device)
        with torch.inference_mode():
            prediction = model(tensor)[0]
        room_logits = prediction[21:33]
        icon_logits = prediction[33:44]
        room_probabilities = torch.softmax(room_logits, dim=0).cpu().numpy()
        icon_probabilities = torch.softmax(icon_logits, dim=0).cpu().numpy()
    except (RuntimeError, ValueError) as exc:
        raise VisionInferenceError("CubiCasa could not segment the selected drawing.") from exc

    labels = [
        (room_probabilities, [
            "background", "outdoor", "wall", "kitchen", "living room", "bedroom",
            "bath", "hallway", "railing", "storage", "garage", "other room",
        ]),
        (icon_probabilities, [
            "empty", "window", "door", "closet", "electrical appliance", "toilet",
            "sink", "sauna bench", "fireplace", "bathtub", "chimney",
        ]),
    ]
    minimum_area = _environment_int("STOA_CUBICASA_MIN_REGION_PIXELS", 20, 1, 100000)
    results: list[dict[str, Any]] = []
    for probabilities, class_names in labels:
        classes = probabilities.argmax(axis=0).astype("uint8")
        for class_index, label in enumerate(class_names):
            if class_index == 0:
                continue
            binary = (classes == class_index).astype("uint8")
            contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for contour in contours:
                area = float(cv2.contourArea(contour))
                if area < minimum_area:
                    continue
                epsilon = max(1.0, 0.002 * cv2.arcLength(contour, True))
                contour = cv2.approxPolyDP(contour, epsilon, True).reshape(-1, 2)
                if len(contour) < 3:
                    continue
                points = [
                    [
                        float(x) * source.native_width / width,
                        float(y) * source.native_height / height,
                    ]
                    for x, y in contour
                ]
                confidence = float(probabilities[class_index][classes == class_index].mean())
                xs, ys = [point[0] for point in points], [point[1] for point in points]
                results.append({
                    "label": label,
                    "score": confidence,
                    "bbox": [min(xs), min(ys), max(xs), max(ys)],
                    "points": points,
                    "area_pixels": area,
                })
    return results


def run_paddle_ocr(image: Image.Image) -> list[dict[str, Any]]:
    try:
        import numpy as np
    except ImportError as exc:
        raise VisionInferenceError("PaddleOCR requires NumPy.") from exc
    result = _load_paddle_ocr().predict(np.asarray(image.convert("RGB")))
    regions: list[dict[str, Any]] = []
    for page_result in result or []:
        data = page_result.json if hasattr(page_result, "json") else page_result
        if isinstance(data, dict) and isinstance(data.get("res"), dict):
            data = data["res"]
        if not isinstance(data, dict):
            continue
        texts = data.get("rec_texts", [])
        scores = data.get("rec_scores", [])
        boxes = data.get("rec_polys", data.get("dt_polys", []))
        for text, score, box in zip(texts, scores, boxes):
            coordinates = box.tolist() if hasattr(box, "tolist") else box
            confidence = float(score)
            if not isinstance(text, str) or not text.strip() or not math.isfinite(confidence):
                continue
            points = [[float(x), float(y)] for x, y in coordinates]
            if len(points) < 3:
                continue
            xs, ys = [point[0] for point in points], [point[1] for point in points]
            regions.append({
                "text": text.strip(),
                "score": confidence,
                "points": points,
                "bbox": [min(xs), min(ys), max(xs), max(ys)],
            })
    return regions


@lru_cache(maxsize=1)
def _load_paddle_ocr() -> Any:
    try:
        from paddleocr import PaddleOCR
    except ImportError as exc:
        raise VisionInferenceError(
            "PaddleOCR is optional; install PaddlePaddle and requirements-vision-ocr.txt."
        ) from exc
    downloads_enabled = (
        os.getenv("STOA_OCR_DOWNLOAD_MODELS", "").strip().lower() == "true"
    )
    if not paddle_ocr_models_cached() and not downloads_enabled:
        raise VisionInferenceError(
            "PaddleOCR weights are missing; run scripts/download_ocr_models.py or set "
            "STOA_OCR_DOWNLOAD_MODELS=true to allow first-use downloads."
        )
    try:
        return PaddleOCR(
            lang="en",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            device="cpu",
            enable_mkldnn=False,
            cpu_threads=_environment_int("STOA_OCR_CPU_THREADS", 1, 1, 8),
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise VisionInferenceError("PaddleOCR could not initialize its English models.") from exc
