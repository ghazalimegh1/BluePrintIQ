from __future__ import annotations

import base64
import json
import math
import os
from typing import Any

from PIL import Image, ImageDraw


DEFAULT_GEMINI_MODEL = "gemini-3.5-flash-lite"
FREE_TIER_MODELS = frozenset({DEFAULT_GEMINI_MODEL})
MAX_REVIEW_CANDIDATES = 64
MAX_IMAGE_SIDE = 2048

SEMANTIC_REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "matches": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "candidate_id": {"type": "string"},
                    "matches_label": {"type": "boolean"},
                    "note": {"type": "string"},
                },
                "required": ["candidate_id", "matches_label", "note"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["matches"],
    "additionalProperties": False,
}


class GeminiVisionError(RuntimeError):
    """Gemini semantic review is unavailable or returned invalid data."""


def configured_gemini_model() -> str:
    model = os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL).strip()
    if model not in FREE_TIER_MODELS:
        raise GeminiVisionError(
            "GEMINI_MODEL must be the allowlisted free-tier model "
            f"{DEFAULT_GEMINI_MODEL}; no other model or paid fallback is used."
        )
    return model


def gemini_vl_configured() -> bool:
    try:
        configured_gemini_model()
    except GeminiVisionError:
        return False
    return bool(os.getenv("GEMINI_API_KEY", "").strip())


def gemini_vl_status() -> dict[str, Any]:
    model = os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL).strip()
    try:
        configured_gemini_model()
        model_error = None
    except GeminiVisionError as exc:
        model_error = str(exc)
    return {
        "configured": bool(os.getenv("GEMINI_API_KEY", "").strip()) and model_error is None,
        "model": model or DEFAULT_GEMINI_MODEL,
        "model_error": model_error,
        "free_tier_only": True,
    }


def _annotated_image(
    image: Image.Image, candidates: list[dict[str, Any]]
) -> bytes:
    preview = image.convert("RGB")
    preview.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE), Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(preview)
    for candidate in candidates:
        x0, y0, x1, y1 = candidate["bbox_normalized"]
        bounds = (
            round(x0 * preview.width),
            round(y0 * preview.height),
            round(x1 * preview.width),
            round(y1 * preview.height),
        )
        draw.rectangle(bounds, outline=(255, 64, 64), width=3)
        draw.text((bounds[0] + 3, bounds[1] + 3), candidate["candidate_id"], fill=(255, 64, 64))
    import io

    output = io.BytesIO()
    preview.save(output, format="JPEG", quality=85, optimize=True)
    return output.getvalue()


def _validate_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not candidates or len(candidates) > MAX_REVIEW_CANDIDATES:
        raise GeminiVisionError(
            f"Gemini semantic review accepts 1 to {MAX_REVIEW_CANDIDATES} detector candidates."
        )
    validated = []
    seen_ids: set[str] = set()
    for candidate in candidates:
        candidate_id = candidate.get("candidate_id")
        label = candidate.get("label")
        bbox = candidate.get("bbox_normalized")
        if (
            not isinstance(candidate_id, str)
            or not candidate_id
            or candidate_id in seen_ids
            or not isinstance(label, str)
            or not label.strip()
            or not isinstance(bbox, (list, tuple))
            or len(bbox) != 4
        ):
            raise GeminiVisionError("Gemini semantic review received an invalid candidate.")
        try:
            if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in bbox):
                raise ValueError("box coordinates must be numbers")
            coordinates = [float(value) for value in bbox]
        except (TypeError, ValueError) as exc:
            raise GeminiVisionError("Gemini semantic review received an invalid candidate box.") from exc
        if (
            any(not math.isfinite(value) or value < 0 or value > 1 for value in coordinates)
            or coordinates[2] <= coordinates[0]
            or coordinates[3] <= coordinates[1]
        ):
            raise GeminiVisionError("Gemini semantic review received an invalid candidate box.")
        score = candidate.get("score")
        if score is not None and (
            not isinstance(score, (int, float))
            or not math.isfinite(float(score))
            or not 0 <= float(score) <= 1
        ):
            raise GeminiVisionError("Gemini semantic review received an invalid candidate score.")
        seen_ids.add(candidate_id)
        validated.append({
            "candidate_id": candidate_id,
            "label": label.strip(),
            "bbox_normalized": coordinates,
            "score": float(score) if score is not None else None,
        })
    return validated


def review_detection_semantics(
    image: Image.Image,
    question: str,
    detections: list[dict[str, Any]],
) -> dict[str, Any]:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise GeminiVisionError("Set GEMINI_API_KEY in the backend environment or ignored .env file.")
    model = configured_gemini_model()
    candidates = _validate_candidates(detections)
    image_bytes = _annotated_image(image, candidates)
    prompt = (
        "Review the red numbered candidate boxes in this construction drawing. "
        "Use the supplied question only as context. For each candidate ID, state whether "
        "the visible region plausibly matches the detector's supplied label and provide a "
        "brief ambiguity note. Do not count objects, answer the question, add candidates, "
        "estimate dimensions, or change any detector box. Return exactly one result per "
        "candidate ID. A match is a semantic opinion, not verification.\n"
        f"Question: {question}\n"
        f"Image size in pixels: {image.width} x {image.height}\n"
        f"Candidates: {json.dumps(candidates, separators=(',', ':'))}"
    )
    try:
        from google import genai
        from google.genai import errors, types
        import httpx
        import httpx2
    except ImportError as exc:
        raise GeminiVisionError(
            "Gemini semantic review requires the google-genai SDK from requirements.txt."
        ) from exc

    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            timeout=45_000,
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )
    try:
        response = client.interactions.create(
            model=model,
            input=[
                {"type": "text", "text": prompt},
                {
                    "type": "image",
                    "data": base64.b64encode(image_bytes).decode("ascii"),
                    "mime_type": "image/jpeg",
                },
            ],
            response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema": SEMANTIC_REVIEW_SCHEMA,
            },
        )
    except errors.APIError as exc:
        status = getattr(exc, "code", None) or getattr(exc, "status_code", None)
        if status == 429 or status == "429":
            raise GeminiVisionError(
                "Gemini free-tier rate limit or quota reached; retry later or check AI Studio quotas."
            ) from None
        raise GeminiVisionError(
            f"Gemini semantic review failed with API status {status or 'unknown'}."
        ) from None
    except (httpx.TimeoutException, httpx2.TimeoutException):
        raise GeminiVisionError("Gemini semantic review timed out.") from None
    except (httpx.TransportError, httpx2.TransportError):
        raise GeminiVisionError("Could not connect to Gemini for semantic review.") from None
    except TimeoutError as exc:
        raise GeminiVisionError("Gemini semantic review timed out.") from None

    try:
        output_text = response.output_text
        if not isinstance(output_text, str) or not output_text.strip():
            raise ValueError("empty structured response")
        parsed = json.loads(output_text)
        if not isinstance(parsed, dict) or set(parsed) != {"matches"}:
            raise ValueError("response object contains unexpected fields")
        matches = parsed["matches"]
        expected_ids = {candidate["candidate_id"] for candidate in candidates}
        returned_ids: set[str] = set()
        if not isinstance(matches, list):
            raise ValueError("matches is not an array")
        for item in matches:
            if (
                not isinstance(item, dict)
                or set(item) != {"candidate_id", "matches_label", "note"}
                or not isinstance(item.get("candidate_id"), str)
                or item["candidate_id"] not in expected_ids
                or item["candidate_id"] in returned_ids
                or not isinstance(item.get("matches_label"), bool)
                or not isinstance(item.get("note"), str)
            ):
                raise ValueError("invalid candidate review")
            returned_ids.add(item["candidate_id"])
        if returned_ids != expected_ids:
            raise ValueError("candidate review omitted a detector candidate")
    except (AttributeError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise GeminiVisionError("Gemini returned invalid structured semantic-review data.") from exc
    return {"model": model, "matches": matches}
