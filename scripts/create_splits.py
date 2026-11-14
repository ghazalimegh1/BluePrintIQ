#!/usr/bin/env python
"""Create reproducible project-family splits with isolated evaluation gold."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "junction-dataset-preview"
DEFAULT_OUTPUT = ROOT / "artifacts" / "data_splits"
DEFAULT_GOLD = ROOT / "artifacts" / "evaluation" / "gold"
SPLITS = ("train", "validation", "test")
TARGETS = {"train": 0.70, "validation": 0.15, "test": 0.15}
ALGORITHM_VERSION = "group-greedy-v1"


class DatasetError(ValueError):
    """Raised when source data is unsafe or malformed."""


def load_questions(question_file: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with question_file.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise DatasetError(f"{question_file}:{line_number}: invalid JSON: {exc}") from exc
            if not isinstance(row, dict):
                raise DatasetError(f"{question_file}:{line_number}: each record must be an object")
            missing = {"path", "question", "answer", "unit", "type"} - row.keys()
            if missing:
                raise DatasetError(
                    f"{question_file}:{line_number}: missing fields {', '.join(sorted(missing))}"
                )
            if not isinstance(row["path"], str) or not isinstance(row["question"], str):
                raise DatasetError(f"{question_file}:{line_number}: path and question must be strings")
            rows.append(row)
    if not rows:
        raise DatasetError(f"No question rows found in {question_file}")
    return rows


def safe_dataset_path(dataset_root: Path, relative_path: str) -> Path:
    """Resolve a POSIX dataset path and reject traversal outside the dataset root."""
    pure_path = PurePosixPath(relative_path)
    if pure_path.is_absolute() or not pure_path.parts or any(part in ("", ".", "..") for part in pure_path.parts):
        raise DatasetError(f"Unsafe dataset path: {relative_path!r}")
    resolved_root = dataset_root.resolve()
    resolved_path = resolved_root.joinpath(*pure_path.parts).resolve()
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise DatasetError(f"Dataset path escapes root: {relative_path!r}") from exc
    return resolved_path


def resolve_group(relative_path: str) -> tuple[str, str]:
    """Return a stable logical drawing/project group and an auditable reason."""
    path = PurePosixPath(relative_path)
    parts = path.parts
    if len(parts) < 3 or parts[0] != "data":
        return f"unclassified:{path.as_posix()}", "path outside data/<source>"
    source = parts[1]
    name = path.name
    stem = path.stem

    if source == "cubicasa5k":
        return f"cubicasa5k:{stem}", "same source image path and all question variants"
    if source == "swiss_dwellings":
        match = re.match(r"site(?P<site>\d+)_bldg(?P<building>\d+)_floor\d+", stem, re.IGNORECASE)
        if match:
            return (
                f"swiss_dwellings:site{match.group('site')}_bldg{match.group('building')}",
                "building family from site/building identifiers; floors and formats stay together",
            )
        return f"swiss_dwellings:{stem}", "same logical basename across available formats"
    if source == "ifc_models":
        model_stem = re.split(r"_plan-", stem, maxsplit=1, flags=re.IGNORECASE)[0]
        return (
            f"ifc_models:{model_stem.casefold()}",
            "IFC model and generated plan views share their pre-_plan basename",
        )
    if source == "ifc_bench":
        return f"ifc_bench:{stem.casefold()}", "all questions for the same IFC-Bench model"
    if source == "opening_design":
        project = parts[2] if len(parts) > 3 else stem
        return f"opening_design:{project.casefold()}", "all drawings in the same project folder"
    return f"{source}:{stem.casefold()}", "same source basename"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def image_dhash(path: Path) -> int | None:
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(path) as image:
            sample = image.convert("L").resize((9, 8))
            pixels = [sample.getpixel((x, y)) for y in range(8) for x in range(9)]
    except (OSError, ValueError):
        return None
    bits = 0
    for y in range(8):
        for x in range(8):
            bits = (bits << 1) | int(pixels[y * 9 + x] > pixels[y * 9 + x + 1])
    return bits


class UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, value: str) -> str:
        self.parent.setdefault(value, value)
        if self.parent[value] != value:
            self.parent[value] = self.find(self.parent[value])
        return self.parent[value]

    def union(self, left: str, right: str) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root != right_root:
            first, second = sorted((left_root, right_root))
            self.parent[second] = first


def _feature_keys(row: dict[str, Any]) -> tuple[str, str]:
    source = PurePosixPath(row["path"]).parts[1] if len(PurePosixPath(row["path"]).parts) > 1 else "unknown"
    return f"source:{source}", f"type:{row.get('type', 'unknown')}"


def assign_group_splits(
    group_rows: dict[str, list[dict[str, Any]]], seed: int
) -> dict[str, str]:
    """Greedily balance row, source, and type counts without splitting a group."""
    rng = random.Random(seed)
    groups = list(group_rows)
    rng.shuffle(groups)
    groups.sort(key=lambda group: len(group_rows[group]), reverse=True)

    total_rows = sum(len(rows) for rows in group_rows.values())
    totals: Counter[str] = Counter()
    for rows in group_rows.values():
        for row in rows:
            totals.update(_feature_keys(row))

    targets: dict[str, dict[str, float]] = {
        split: {
            "rows": total_rows * TARGETS[split],
            **{feature: count * TARGETS[split] for feature, count in totals.items()},
        }
        for split in SPLITS
    }
    current: dict[str, Counter[str]] = {split: Counter() for split in SPLITS}
    assigned: dict[str, str] = {}

    def group_features(rows: list[dict[str, Any]]) -> Counter[str]:
        features: Counter[str] = Counter(rows=len(rows))
        for row in rows:
            features.update(_feature_keys(row))
        return features

    def score(split: str, features: Counter[str]) -> float:
        cost = 0.0
        for candidate in SPLITS:
            for key, target in targets[candidate].items():
                value = current[candidate][key]
                if candidate == split:
                    value += features[key]
                scale = max(target, 1.0)
                cost += ((value - target) / scale) ** 2
        return cost

    for group in groups:
        features = group_features(group_rows[group])
        best_split = min(SPLITS, key=lambda split: score(split, features))
        assigned[group] = best_split
        current[best_split].update(features)
    return assigned


def _count_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_source: Counter[str] = Counter()
    by_type: Counter[str] = Counter()
    for row in rows:
        by_source[_feature_keys(row)[0].removeprefix("source:")] += 1
        by_type[str(row.get("type", "unknown"))] += 1
    return {"rows": len(rows), "by_source": dict(sorted(by_source.items())), "by_type": dict(sorted(by_type.items()))}


def build_splits(
    rows: list[dict[str, Any]], dataset_root: Path, seed: int
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    paths = sorted({row["path"] for row in rows})
    path_metadata: dict[str, dict[str, Any]] = {}
    union = UnionFind()
    hash_groups: dict[str, str] = {}

    for relative_path in paths:
        initial_group, reason = resolve_group(relative_path)
        union.find(initial_group)
        file_path = safe_dataset_path(dataset_root, relative_path)
        if file_path.is_file():
            digest = sha256_file(file_path)
            path_metadata[relative_path] = {
                "initial_group_id": initial_group,
                "group_reason": reason,
                "sha256": digest,
                "exists": True,
            }
            if digest in hash_groups:
                union.union(initial_group, hash_groups[digest])
            else:
                hash_groups[digest] = initial_group
        else:
            path_metadata[relative_path] = {
                "initial_group_id": initial_group,
                "group_reason": reason,
                "sha256": None,
                "exists": False,
            }

    group_by_path = {
        path: union.find(metadata["initial_group_id"])
        for path, metadata in path_metadata.items()
    }
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[group_by_path[row["path"]]].append(row)
    assignment = assign_group_splits(grouped, seed)

    split_rows: dict[str, list[dict[str, Any]]] = {name: [] for name in SPLITS}
    for row in rows:
        group_id = group_by_path[row["path"]]
        split = assignment[group_id]
        source = _feature_keys(row)[0].removeprefix("source:")
        question_id = hashlib.sha256(
            f"{row['path']}\0{row['question']}\0{row.get('unit')}\0{row.get('type')}".encode("utf-8")
        ).hexdigest()[:20]
        split_rows[split].append(
            {**row, "question_id": question_id, "source": source, "group_id": group_id, "split": split}
        )

    hashes_by_path = {path: meta["sha256"] for path, meta in path_metadata.items() if meta["sha256"]}
    split_paths = {
        split: {row["path"] for row in split_rows[split]}
        for split in SPLITS
    }
    path_split = {path: split for split, paths_for_split in split_paths.items() for path in paths_for_split}
    hash_split: dict[str, set[str]] = defaultdict(set)
    for path, digest in hashes_by_path.items():
        if path in path_split:
            hash_split[digest].add(path_split[path])

    near_duplicates: list[dict[str, Any]] = []
    image_hashes: list[tuple[str, int]] = []
    for relative_path in paths:
        if PurePosixPath(relative_path).suffix.casefold() in {".png", ".jpg", ".jpeg"}:
            value = image_dhash(safe_dataset_path(dataset_root, relative_path))
            if value is not None:
                image_hashes.append((relative_path, value))
    for index, (left_path, left_hash) in enumerate(image_hashes):
        for right_path, right_hash in image_hashes[index + 1 :]:
            distance = (left_hash ^ right_hash).bit_count()
            if 0 < distance <= 4:
                near_duplicates.append(
                    {
                        "left": left_path,
                        "right": right_path,
                        "dhash_distance": distance,
                        "action": "flagged for review; not automatically merged",
                    }
                )

    group_paths: dict[str, set[str]] = defaultdict(set)
    for path, group_id in group_by_path.items():
        group_paths[group_id].add(path)
    split_group_ids = {
        split: {row["group_id"] for row in split_rows[split]}
        for split in SPLITS
    }
    group_overlap = {
        f"{left}/{right}": sorted(split_group_ids[left] & split_group_ids[right])
        for i, left in enumerate(SPLITS)
        for right in SPLITS[i + 1 :]
    }
    path_overlap = {
        f"{left}/{right}": sorted(split_paths[left] & split_paths[right])
        for i, left in enumerate(SPLITS)
        for right in SPLITS[i + 1 :]
    }
    hash_overlap = {
        digest: sorted(split_names)
        for digest, split_names in hash_split.items()
        if len(split_names) > 1
    }
    audit = {
        "group_overlap": group_overlap,
        "path_overlap": path_overlap,
        "exact_hash_cross_split": hash_overlap,
        "alternate_format_families": "covered by canonical group assignment",
        "ifc_model_render_families": "covered by canonical group assignment",
        "translation_and_paraphrase_families": "all rows for a path remain in one canonical group",
        "near_duplicates_for_review": near_duplicates,
    }
    audit["passed"] = not any(group_overlap.values()) and not any(path_overlap.values()) and not hash_overlap

    enriched_rows = []
    for relative_path, metadata in path_metadata.items():
        group_id = group_by_path[relative_path]
        enriched_rows.append(
            {
                "path": relative_path,
                "initial_group_id": metadata["initial_group_id"],
                "group_id": group_id,
                "group_reason": metadata["group_reason"],
                "sha256": metadata["sha256"],
                "exists": metadata["exists"],
                "split": assignment[group_id],
            }
        )
    manifest = {
        "algorithm_version": ALGORITHM_VERSION,
        "seed": seed,
        "target_proportions": TARGETS,
        "row_count": len(rows),
        "group_count": len(grouped),
        "path_count": len(paths),
        "split_counts": {
            split: {
                **_count_rows(split_rows[split]),
                "groups": len(split_group_ids[split]),
                "unique_paths": len(split_paths[split]),
            }
            for split in SPLITS
        },
        "resolver_rules": [
            "CubiCasa: same image path",
            "Swiss dwellings: site/building family across floors and formats",
            "IFC models: IFC and generated views share basename before _plan-",
            "IFC-Bench: model path",
            "OpeningDesign: project folder",
            "Other sources: same source basename",
            "Exact SHA-256 duplicates merge groups; uncertain near-duplicates are review-only",
        ],
        "group_assignments": enriched_rows,
        "missing_source_paths": [path for path, meta in path_metadata.items() if not meta["exists"]],
        "near_duplicate_method": (
            "64-bit dHash, hamming distance <= 4; review-only"
            if image_hashes
            else "unavailable (Pillow not installed or no readable raster files)"
        ),
    }
    return [*split_rows["train"], *split_rows["validation"], *split_rows["test"]], manifest, audit


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def write_artifacts(
    split_rows: list[dict[str, Any]],
    manifest: dict[str, Any],
    audit: dict[str, Any],
    output_dir: Path,
    gold_dir: Path,
) -> None:
    by_split = {split: [] for split in SPLITS}
    for row in split_rows:
        by_split[row["split"]].append(row)

    _write_jsonl(output_dir / "train.jsonl", by_split["train"])
    for split in ("validation", "test"):
        inputs: list[dict[str, Any]] = []
        gold: list[dict[str, Any]] = []
        for row in by_split[split]:
            input_row = {key: value for key, value in row.items() if key != "answer"}
            inputs.append(input_row)
            gold.append(
                {
                    "question_id": row["question_id"],
                    "answer": row["answer"],
                    "unit": row.get("unit"),
                    "type": row.get("type"),
                    "source": row["source"],
                    "group_id": row["group_id"],
                    "path": row["path"],
                }
            )
        _write_jsonl(output_dir / f"{split}_inputs.jsonl", inputs)
        _write_jsonl(gold_dir / f"{split}_gold.jsonl", gold)

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "split_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "leakage_audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--questions", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--gold-dir", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--seed", type=int, default=2026)
    args = parser.parse_args(argv)
    question_file = args.questions or args.dataset_root / "questions.jsonl"

    try:
        rows = load_questions(question_file)
        split_rows, manifest, audit = build_splits(rows, args.dataset_root, args.seed)
        write_artifacts(split_rows, manifest, audit, args.output_dir, args.gold_dir)
    except (OSError, DatasetError) as exc:
        print(f"Split generation failed: {exc}", file=sys.stderr)
        return 2

    print(f"Rows: {manifest['row_count']}; groups: {manifest['group_count']}; paths: {manifest['path_count']}")
    for split, counts in manifest["split_counts"].items():
        print(f"{split}: {counts['rows']} rows, {counts['groups']} groups, {counts['unique_paths']} paths")
    print(f"Leakage audit: {'PASS' if audit['passed'] else 'FAIL'}")
    print(f"Artifacts: {args.output_dir.resolve()}")
    print(f"Evaluator-only gold: {args.gold_dir.resolve()}")
    return 0 if audit["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
