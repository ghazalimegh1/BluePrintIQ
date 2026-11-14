# Evaluation

Evaluation data is kept outside the runtime answering path. The application may inspect a drawing and produce a prediction, but it must not load `questions.jsonl`, the gold answers, or a split manifest while answering a user question.

## Reproducible answer evaluation

Generate predictions from answer-free inputs with the runtime harness:

```powershell
python scripts\run_runtime_eval.py `
  --inputs artifacts\data_splits\test_inputs.jsonl `
  --source ifc_bench `
  --limit 20 `
  --output artifacts\evaluation\predictions.jsonl
```

The harness resolves source paths beneath the dataset root, calls the same
`answer_question` path used by the API, and writes answer/evidence/status data
only. It never reads `*_gold.jsonl`. Run the scorer below as a separate step.

The scorer expects two JSONL files:

```powershell
python scripts\evaluate.py `
  --predictions artifacts\evaluation\predictions.jsonl `
  --gold artifacts\evaluation\gold\test.jsonl `
  --output artifacts\evaluation\reports\test.json
```

Each prediction and gold row must contain a unique `question_id`. Prediction rows use `value`, `unit`, `status`, and optional `evidence`; gold rows additionally contain the benchmark `type`, `source`, and `group_id`. The scorer applies exact matching to counts and a 2% relative tolerance to length, area, and volume after unit conversion. Text is normalized for case and punctuation only.

Rows with `partial`, `uncertain`, `unable`, or `error` status are retained in the report. Only rows with a value and a non-abstaining status count as answered. The report includes overall accuracy, answered accuracy, abstention rate, evidence coverage, per-type/source metrics, and mean group accuracy.

## Leakage-safe protocol

1. Generate the grouped manifest with `scripts\create_splits.py` from the answer-bearing dataset metadata.
2. Keep the gold copy under ignored `artifacts\evaluation\gold\`; never import it from `backend`.
3. Generate predictions using only the drawing path, question text, and the selected runtime tools.
4. Score predictions only after the run has completed.
5. Report results separately for train, validation, and held-out test groups.

The group is the drawing/building identity, not an individual question row. Alternate PDF, raster, CAD, and IFC representations of the same drawing must remain in one group.

## Raster perception evaluation

Question answers alone are not object-detection ground truth. For a credible window/door/room evaluation, create a versioned annotation file under `data/annotations/` containing source-relative paths, image dimensions, class labels, and source-pixel boxes or polygons. Split annotations by drawing identity and report precision, recall, duplicate rate, and evidence-localization quality in addition to answer accuracy.

Until that annotation set exists, raster counts from Grounding DINO, SAM 2, or CubiCasa are explicitly partial model predictions. For example, the current CubiCasa run on `colorful-34.png` produced two retained window regions; this is useful source-linked evidence, but it is not a validated answer to the benchmark's window-count question.

## Current status

- Grouped question splitting and answer scoring are implemented.
- Gold references remain isolated from the application runtime.
- A manually annotated, drawing-identity-split raster subset is not yet available.
- Native IFC counts and evidence can be evaluated deterministically when the model contains the requested entity type.
