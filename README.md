# MM-ArkBench Annotator

Lightweight local annotation UI for MM-ArkBench / ArkTS multimodal retrieval datasets.

This repository intentionally contains only review/annotation code. It does not include dataset parquet files, screenshots, cloned repositories, OpenHarmony/HarmonyOS SDK files, runtime build logs, signing materials, tokens, or model evaluation code.

## Install

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
```

## Quick start: load from Hugging Face

```powershell
.\.venv\Scripts\python tools\review_app\build_review_app.py `
  --dataset hreyulog/Arkts-mm-ui-pilot `
  --limit 500 `
  --min-per-query-type 50 `
  --serve
```

Then open:

```text
http://127.0.0.1:8765/index.html
```

## Use a local HF-style dataset directory

```powershell
.\.venv\Scripts\python tools\review_app\build_review_app.py `
  --dataset-dir C:\path\to\hf_dataset_full `
  --output review_app `
  --limit 500 `
  --min-per-query-type 50 `
  --serve
```

Expected local layout:

```text
DATASET_ROOT/
  data/
    queries/
    corpus/
    symbols/
    repositories/
```

The generated review app contains:

- `index.html`
- `review_items.json`
- `review_app_stats.json`
- `assets/`

## Query type semantics

- `repo_screenshot`: repository README/docs/assets UI screenshot; the right panel shows ArkTS code candidates.
- `runtime_screenshot`: actual device/emulator runtime screenshot; the right panel shows ArkTS code candidates.
- `doc_or_promo`: documentation, architecture, or promotional image; the right panel emphasizes README/docs/source provenance rather than code positives.

README/docs provenance is read from `matching_evidence`, for example:

- `source:readme`
- `readme:markdown_path=...`
- `readme:heading=...`
- `readme:line=...`

## Review output

The browser stores annotations in `localStorage`. Use the buttons in the UI to download:

- `mmarkbench_review.jsonl`
- `mmarkbench_review.csv`

## Apply review results

```powershell
.\.venv\Scripts\python tools\review_app\apply_review_results.py mmarkbench_review.jsonl `
  --input C:\path\to\hf_dataset_full `
  --output C:\path\to\hf_dataset_reviewed
```

`accept` and `correct` become `human_verified`; `correct` can replace `positive_file_ids`.

## Repository layout

```text
tools/review_app/
  build_review_app.py       # Build and optionally serve the static review UI
  apply_review_results.py   # Apply exported human review JSONL to queries
  static/index.html         # Frontend template
requirements.txt
```

## Deliberately excluded

- `hf_dataset*/`
- `corpus/`
- `metadata/`
- generated `review_app/`
- runtime captures/build directories
- credentials, tokens, and signing materials
