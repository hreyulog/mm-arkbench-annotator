from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from datasets import Dataset, load_dataset


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


def parquet_files(dataset_dir: Path, config: str) -> dict[str, list[str]]:
    config_dir = dataset_dir / "data" / config
    files: dict[str, list[str]] = {}
    for split in ["train", "validation", "test"]:
        split_files = sorted(config_dir.glob(f"{split}-*.parquet"))
        if split_files:
            files[split] = [str(path) for path in split_files]
    if not files:
        raise FileNotFoundError(f"No parquet files found under {config_dir}")
    return files


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply exported MM-ArkBench review JSONL to a local HF-style dataset.")
    parser.add_argument("review_jsonl", type=Path)
    parser.add_argument("--input", type=Path, required=True, help="Input dataset root containing data/queries.")
    parser.add_argument("--output", type=Path, required=True, help="Output reviewed dataset root.")
    parser.add_argument("--keep-skipped", action="store_true")
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    reviews = {row["query_id"]: row for row in load_jsonl(args.review_jsonl)}
    ds = load_dataset("parquet", data_files=parquet_files(args.input, "queries"))

    counts: dict[str, int] = {"accept": 0, "correct": 0, "reject": 0, "skip": 0, "unreviewed": 0}
    out_dir = args.output / "data" / "queries"
    out_dir.mkdir(parents=True, exist_ok=True)

    for split, part in ds.items():
        rows: list[dict] = []
        for row in part:
            item = dict(row)
            review = reviews.get(item["query_id"])
            if not review:
                counts["unreviewed"] += 1
                rows.append(item)
                continue

            decision = review.get("decision", "skip")
            counts[decision] = counts.get(decision, 0) + 1
            if decision == "reject":
                continue
            if decision == "skip" and not args.keep_skipped:
                rows.append(item)
                continue
            if decision == "correct":
                corrected = [
                    value.strip()
                    for value in str(review.get("correct_files") or "").split(",")
                    if value.strip()
                ]
                if corrected:
                    item["positive_file_ids"] = corrected
                    item["positive_symbol_ids"] = []
            if decision in {"accept", "correct"}:
                item["label_status"] = "human_verified"
                item["matching_evidence"] = list(item.get("matching_evidence") or []) + [
                    f"human_review:{decision}",
                    f"human_note:{review.get('notes', '')}"[:500],
                ]
            rows.append(item)

        Dataset.from_list(rows, features=part.features).to_parquet(str(out_dir / f"{split}-00000-of-00001.parquet"))

    for name in ["corpus", "symbols", "repositories"]:
        src = args.input / "data" / name
        dst = args.output / "data" / name
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)

    for name in ["README.md", "dataset_info.json", ".gitattributes"]:
        src = args.input / name
        if src.exists():
            shutil.copy2(src, args.output / name)

    (args.output / "review_application_report.json").write_text(json.dumps(counts, indent=2), "utf-8")
    print(json.dumps(counts, indent=2))


if __name__ == "__main__":
    main()
