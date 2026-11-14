# Data splits and evaluation

Run the splitter from the project root:

```powershell
python scripts\create_splits.py --seed 2026
```

The command writes `train.jsonl`, answer-free `validation_inputs.jsonl` and `test_inputs.jsonl`, the split manifest, and leakage audit under `artifacts/data_splits/`. Validation/test answers are written separately to `artifacts/evaluation/gold/`; that directory is gitignored and must never be mounted into runtime services.

The resolver groups CubiCasa question variants by image, Swiss dwelling floors/formats by site/building, IFC floor-plan renders with their model by shared basename, IFC-Bench records by model, and OpeningDesign drawings by project folder. Exact SHA-256 duplicates merge groups. A 64-bit image difference hash flags close raster pairs for manual review but does not merge them. Whole groups are assigned deterministically with the requested seed and a greedy row/source/type balancing objective.

The offline evaluator accepts solver predictions and a protected gold file:

```powershell
python scripts\evaluate.py --predictions predictions.jsonl --gold artifacts\evaluation\gold\validation_gold.jsonl
```

Count values are exact. Area, length, and volume use explicit unit conversions and a 2% relative-error threshold. Text scoring is normalized exact match only. The evaluator also reports abstention, evidence coverage, source/type and group-level results.
