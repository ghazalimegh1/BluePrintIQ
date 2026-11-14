#!/usr/bin/env python
"""Evaluate predictions against a separate protected gold JSONL file."""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


LENGTH_FACTORS = {
    "m": Decimal("1"), "meter": Decimal("1"), "meters": Decimal("1"),
    "metre": Decimal("1"), "metres": Decimal("1"),
    "mm": Decimal("0.001"), "millimeter": Decimal("0.001"), "millimeters": Decimal("0.001"),
    "cm": Decimal("0.01"), "centimeter": Decimal("0.01"), "centimeters": Decimal("0.01"),
    "km": Decimal("1000"), "ft": Decimal("0.3048"), "feet": Decimal("0.3048"),
    "in": Decimal("0.0254"), "inch": Decimal("0.0254"), "inches": Decimal("0.0254"),
}
AREA_FACTORS = {
    "m2": Decimal("1"), "m^2": Decimal("1"), "sqm": Decimal("1"),
    "ft2": Decimal("0.09290304"), "ft^2": Decimal("0.09290304"), "sqft": Decimal("0.09290304"),
    "mm2": Decimal("0.000001"), "mm^2": Decimal("0.000001"),
    "cm2": Decimal("0.0001"), "cm^2": Decimal("0.0001"),
}
VOLUME_FACTORS = {
    "m3": Decimal("1"), "m^3": Decimal("1"),
    "ft3": Decimal("0.028316846592"), "ft^3": Decimal("0.028316846592"),
    "l": Decimal("0.001"), "liter": Decimal("0.001"), "litre": Decimal("0.001"),
}
UNIT_MAPS = {"length": LENGTH_FACTORS, "area": AREA_FACTORS, "volume": VOLUME_FACTORS}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
            if not isinstance(record, dict):
                raise ValueError(f"{path}:{line_number}: expected an object")
            records.append(record)
    return records


def parse_number(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        try:
            number = Decimal(str(value))
            return number if number.is_finite() else None
        except InvalidOperation:
            return None
    if not isinstance(value, str):
        return None
    candidate = value.strip().replace("\u2212", "-")
    candidate = re.sub(r"(?<=\d)[,\s](?=\d{3}(?:\D|$))", "", candidate)
    match = re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", candidate)
    if not match:
        return None
    try:
        number = Decimal(candidate)
        return number if number.is_finite() else None
    except InvalidOperation:
        return None


def normalize_unit(unit: Any) -> str:
    if not isinstance(unit, str):
        return ""
    value = unit.casefold().strip().replace("²", "2").replace("³", "3")
    value = re.sub(r"\s+", "", value)
    return value


def numeric_score(
    prediction: dict[str, Any], reference: dict[str, Any]
) -> tuple[bool, str]:
    predicted = parse_number(prediction.get("value"))
    expected = parse_number(reference.get("answer"))
    if predicted is None or expected is None:
        return False, "non_numeric"

    question_type = str(reference.get("type", "")).casefold()
    if question_type == "count":
        return predicted == expected, "exact_count"
    factors = UNIT_MAPS.get(question_type)
    if factors is None:
        return predicted == expected, "numeric_exact"

    predicted_unit = normalize_unit(prediction.get("unit"))
    expected_unit = normalize_unit(reference.get("unit"))
    if predicted_unit not in factors or expected_unit not in factors:
        if predicted_unit == expected_unit:
            expected_value, predicted_value = expected, predicted
        else:
            return False, "unsupported_or_mismatched_unit"
    else:
        expected_value = expected * factors[expected_unit]
        predicted_value = predicted * factors[predicted_unit]

    if expected_value == 0:
        return predicted_value == 0, "within_2_percent"
    relative_error = abs(predicted_value - expected_value) / abs(expected_value)
    return relative_error <= Decimal("0.02"), "within_2_percent"


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = "".join(char for char in text if not unicodedata.category(char).startswith("P"))
    return " ".join(text.split())


def score_pair(prediction: dict[str, Any], reference: dict[str, Any]) -> tuple[bool, str]:
    kind = str(reference.get("type", "other")).casefold()
    if kind in {"count", "area", "length", "volume"}:
        return numeric_score(prediction, reference)
    return (
        normalize_text(prediction.get("value")) == normalize_text(reference.get("answer")),
        "normalized_text_exact",
    )


def evaluate(predictions: list[dict[str, Any]], gold: list[dict[str, Any]]) -> dict[str, Any]:
    def unique_index(records: list[dict[str, Any]], label: str) -> dict[str, dict[str, Any]]:
        indexed: dict[str, dict[str, Any]] = {}
        for record in records:
            question_id = record.get("question_id")
            if not isinstance(question_id, str) or not question_id:
                raise ValueError(f"{label} row is missing question_id")
            if question_id in indexed:
                raise ValueError(f"Duplicate question_id in {label}: {question_id}")
            indexed[question_id] = record
        return indexed

    predictions_by_id = unique_index(predictions, "predictions")
    gold_by_id = unique_index(gold, "gold")
    missing = sorted(set(gold_by_id) - set(predictions_by_id))
    unexpected = sorted(set(predictions_by_id) - set(gold_by_id))

    rows: list[dict[str, Any]] = []
    for question_id, reference in gold_by_id.items():
        prediction = predictions_by_id.get(question_id, {})
        status = str(prediction.get("status", "abstain")).casefold()
        answered = status not in {"abstain", "unable", "unsupported", "error", "unknown"} and "value" in prediction
        correct, metric = score_pair(prediction, reference) if answered else (False, "abstained")
        rows.append(
            {
                "question_id": question_id,
                "source": reference.get("source", "unknown"),
                "type": reference.get("type", "unknown"),
                "group_id": reference.get("group_id", "unknown"),
                "answered": answered,
                "correct": correct,
                "metric": metric,
                "evidence": bool(prediction.get("evidence")),
                "status": status,
            }
        )

    total = len(rows)
    answered_rows = [row for row in rows if row["answered"]]
    correct_count = sum(row["correct"] for row in rows)
    group_scores: dict[str, dict[str, int]] = defaultdict(lambda: {"rows": 0, "correct": 0, "answered": 0})
    for row in rows:
        stats = group_scores[row["group_id"]]
        stats["rows"] += 1
        stats["correct"] += int(row["correct"])
        stats["answered"] += int(row["answered"])

    def category_metrics(key: str) -> dict[str, Any]:
        categories: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            categories[str(row[key])].append(row)
        return {
            category: {
                "rows": len(category_rows),
                "answered": sum(row["answered"] for row in category_rows),
                "correct": sum(row["correct"] for row in category_rows),
                "accuracy_all": sum(row["correct"] for row in category_rows) / len(category_rows),
            }
            for category, category_rows in sorted(categories.items())
        }

    return {
        "total_gold": total,
        "matched_predictions": len(set(predictions_by_id) & set(gold_by_id)),
        "missing_predictions": missing,
        "unexpected_predictions": unexpected,
        "correct": correct_count,
        "accuracy_all": correct_count / total if total else None,
        "answered": len(answered_rows),
        "accuracy_answered": (
            sum(row["correct"] for row in answered_rows) / len(answered_rows)
            if answered_rows else None
        ),
        "abstention_rate": 1 - len(answered_rows) / total if total else None,
        "evidence_coverage": (
            sum(row["evidence"] for row in answered_rows) / len(answered_rows)
            if answered_rows else None
        ),
        "by_type": category_metrics("type"),
        "by_source": category_metrics("source"),
        "group_level": {
            "groups": len(group_scores),
            "mean_group_accuracy": (
                sum(stats["correct"] / stats["rows"] for stats in group_scores.values()) / len(group_scores)
                if group_scores else None
            ),
        },
        "text_metric": "normalized exact match only; no LLM judge substituted",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = evaluate(load_jsonl(args.predictions), load_jsonl(args.gold))
    except (OSError, ValueError) as exc:
        print(f"Evaluation failed: {exc}", file=sys.stderr)
        return 2
    serialized = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    else:
        print(serialized, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
