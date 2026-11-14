import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.create_splits import build_splits, resolve_group, safe_dataset_path
from scripts.evaluate import evaluate, numeric_score, parse_number


class GroupResolverTests(unittest.TestCase):
    def test_swiss_floors_group_by_building(self):
        first, _ = resolve_group("data/swiss_dwellings/site1000_bldg2082_floor9385.pdf")
        second, _ = resolve_group("data/swiss_dwellings/site1000_bldg2082_floor9386.png")
        self.assertEqual(first, second)

    def test_ifc_render_groups_with_model(self):
        model, _ = resolve_group("data/ifc_models/bsc-molio_molio-with-uris.ifc")
        plan, _ = resolve_group("data/ifc_models/bsc-molio_molio-with-uris_plan-02-klder.pdf")
        self.assertEqual(model, plan)

    def test_opening_design_groups_by_project(self):
        first, _ = resolve_group("data/opening_design/Sports_Complex/Sheets/A.pdf")
        second, _ = resolve_group("data/opening_design/Sports_Complex/Models/B.ifc")
        other, _ = resolve_group("data/opening_design/CTR/Sheets/C.pdf")
        self.assertEqual(first, second)
        self.assertNotEqual(first, other)

    def test_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                safe_dataset_path(Path(temp), "data/../../outside.txt")


class SplitTests(unittest.TestCase):
    def test_group_integrity_and_answer_free_evaluation_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for source, name in [
                ("cubicasa5k", "plan-a.png"),
                ("cubicasa5k", "plan-b.png"),
                ("swiss_dwellings", "site1_bldg10_floor1.pdf"),
                ("swiss_dwellings", "site1_bldg10_floor2.png"),
                ("ifc_bench", "model.ifc"),
                ("ifc_bench", "other.ifc"),
            ]:
                path = root / "data" / source / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(f"{source}/{name}".encode())
            rows = []
            for index in range(12):
                path = [
                    "data/cubicasa5k/plan-a.png",
                    "data/cubicasa5k/plan-b.png",
                    "data/swiss_dwellings/site1_bldg10_floor1.pdf",
                    "data/swiss_dwellings/site1_bldg10_floor2.png",
                    "data/ifc_bench/model.ifc",
                    "data/ifc_bench/other.ifc",
                ][index % 6]
                rows.append(
                    {
                        "path": path,
                        "question": f"Q{index}",
                        "answer": index,
                        "unit": "count",
                        "type": "count",
                    }
                )
            split_rows, manifest, audit = build_splits(rows, root, seed=7)
            self.assertTrue(audit["passed"])
            group_to_splits = {}
            for row in split_rows:
                group_to_splits.setdefault(row["group_id"], set()).add(row["split"])
            self.assertTrue(all(len(splits) == 1 for splits in group_to_splits.values()))
            self.assertEqual(manifest["row_count"], 12)

    def test_question_ids_are_stable_across_split_seed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "data" / "cubicasa5k" / "x.png"
            path.parent.mkdir(parents=True)
            path.write_bytes(b"sample")
            row = {
                "path": "data/cubicasa5k/x.png",
                "question": "How many doors?",
                "answer": 2,
                "unit": "count",
                "type": "count",
            }
            first, _, _ = build_splits([row], root, seed=1)
            second, _, _ = build_splits([row], root, seed=2)
            self.assertEqual(first[0]["question_id"], second[0]["question_id"])


class EvaluationTests(unittest.TestCase):
    def test_count_is_exact(self):
        ref = {"answer": "4", "unit": "count", "type": "count"}
        self.assertTrue(numeric_score({"value": 4.0, "unit": "count"}, ref)[0])
        self.assertFalse(numeric_score({"value": 4.01, "unit": "count"}, ref)[0])

    def test_measurement_tolerance_and_conversion(self):
        ref = {"answer": 10, "unit": "m2", "type": "area"}
        self.assertTrue(numeric_score({"value": 107.639, "unit": "ft2"}, ref)[0])
        self.assertFalse(numeric_score({"value": 105, "unit": "ft2"}, ref)[0])

    def test_text_normalization_and_evidence_metrics(self):
        result = evaluate(
            [
                {
                    "question_id": "a",
                    "value": "Door Schedule",
                    "status": "supported",
                    "evidence": [{"path": "plan.pdf", "page": 1}],
                }
            ],
            [
                {
                    "question_id": "a",
                    "answer": "door schedule.",
                    "type": "text",
                    "source": "opening_design",
                    "group_id": "p1",
                }
            ],
        )
        self.assertEqual(result["correct"], 1)
        self.assertEqual(result["evidence_coverage"], 1.0)

    def test_number_parser_rejects_booleans_and_non_finite(self):
        self.assertIsNone(parse_number(True))
        self.assertIsNone(parse_number("NaN"))
        self.assertEqual(parse_number("1,200"), 1200)


if __name__ == "__main__":
    unittest.main()
