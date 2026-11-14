#!/usr/bin/env python
"""Run BLUELOGIC on answer-free evaluation inputs.

This runner deliberately imports only the input split and source documents. It
never loads evaluator gold answers; score the generated JSONL separately with
``scripts/evaluate.py``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DEFAULT_DATASET_ROOT = ROOT / "junction-dataset-preview"
DEFAULT_INPUTS = ROOT / "artifacts" / "data_splits" / "test_inputs.jsonl"
DEFAULT_OUTPUT = ROOT / "artifacts" / "evaluation" / "predictions.jsonl"


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number}: expected an object")
            rows.append(value)
    return rows


def safe_source_path(dataset_root: Path, relative_path: str) -> Path:
    candidate = (dataset_root / Path(*PurePosixPath(relative_path).parts)).resolve()
    try:
        candidate.relative_to(dataset_root.resolve())
    except ValueError as exc:
        raise ValueError(f"Input path escapes dataset root: {relative_path}") from exc
    if not candidate.is_file():
        raise FileNotFoundError(candidate)
    return candidate


def document_id(relative_path: str) -> str:
    return hashlib.sha256(relative_path.encode("utf-8")).hexdigest()[:24]


def run(rows: list[dict[str, Any]], dataset_root: Path, limit: int = 0) -> list[dict[str, Any]]:
    # Import the runtime after argument validation so this tool remains a
    # thin offline harness and does not initialize the evaluator or gold data.
    from backend.app.routing import answer_question

    predictions: list[dict[str, Any]] = []
    selected = rows if limit <= 0 else rows[:limit]
    for index, row in enumerate(selected, start=1):
        relative_path = row.get("path")
        question = row.get("question")
        question_id = row.get("question_id")
        if not all(isinstance(value, str) and value for value in (relative_path, question, question_id)):
            raise ValueError(f"Input row {index} is missing path, question, or question_id")
        source_path = safe_source_path(dataset_root, relative_path)
        result = answer_question(
            document_id(relative_path),
            relative_path,
            source_path,
            source_path.suffix.casefold().lstrip("."),
            question,
            page_number=1,
        )
        predictions.append({
            "question_id": question_id,
            "path": relative_path,
            "source": row.get("source"),
            "group_id": row.get("group_id"),
            "status": result.status,
            "value": result.value,
            "unit": result.unit,
            "answer": result.answer,
            "evidence": [evidence.model_dump() for evidence in result.evidence],
            "warnings": result.warnings,
            "validation": result.validation,
        })
        print(f"[{index}/{len(selected)}] {relative_path} -> {result.status}: {result.answer}")
    return predictions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, default=DEFAULT_INPUTS)
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=0, help="Maximum rows to run; 0 means all")
    parser.add_argument("--source", help="Only run rows whose source matches, e.g. ifc_models")
    args = parser.parse_args(argv)
    try:
        rows = load_jsonl(args.inputs)
        if args.source:
            rows = [row for row in rows if row.get("source") == args.source]
        predictions = run(rows, args.dataset_root.resolve(), args.limit)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8") as stream:
            for prediction in predictions:
                stream.write(json.dumps(prediction, ensure_ascii=False) + "\n")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Runtime evaluation failed: {exc}", file=sys.stderr)
        return 2
    print(f"Wrote {len(predictions)} answer-free runtime predictions to {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
