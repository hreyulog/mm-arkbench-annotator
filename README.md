# MM-ArkBench

Utilities for building and reviewing MM-ArkBench / ArkTS multimodal datasets.

This repository currently contains the lightweight human-review frontend for the
pilot dataset:

- Hugging Face dataset: `hreyulog/Arkts-mm-ui-pilot`
- Task: screenshot / image query → ArkTS file or symbol candidates
- Review target: accept, correct, reject, or skip automatically generated labels

## Quick start: review the pilot dataset

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python tools\review_app\build_review_app.py --serve
```

Then open:

```text
http://127.0.0.1:8765/index.html
```

The app will:

1. load `queries`, `corpus`, `symbols`, and `repositories` from Hugging Face;
2. sample a balanced review set across query types;
3. export a static review app under `review_app/`;
4. start a local HTTP server when `--serve` is passed.

No dataset build harness or model evaluation code is included here yet.

## Useful options

```powershell
# Generate 500 review examples, with at least 50 per query_type when possible.
python tools\review_app\build_review_app.py --limit 500 --min-per-query-type 50

# Use a local HF-style dataset directory instead of the remote dataset.
python tools\review_app\build_review_app.py --dataset-dir C:\path\to\hf_dataset --serve

# Change output folder or port.
python tools\review_app\build_review_app.py --output C:\tmp\mmarkbench_review --serve --port 9000
```

## Review output

The browser stores annotations in `localStorage`. Use the buttons in the UI to
download:

- `mmarkbench_review.jsonl`
- `mmarkbench_review.csv`

These files can later be merged back into the dataset export pipeline.

## Repository layout

```text
tools/review_app/
  build_review_app.py      # Builds and optionally serves the static review UI
  static/index.html        # Frontend template
requirements.txt
```
