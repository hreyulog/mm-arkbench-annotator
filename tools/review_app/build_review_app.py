from __future__ import annotations

import argparse
import functools
import hashlib
import http.server
import json
import os
import shutil
import socketserver
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

from datasets import load_dataset


DEFAULT_DATASET = "hreyulog/Arkts-mm-ui-pilot"
ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = Path(__file__).resolve().parent / "static" / "index.html"


def code_window(content: str, path: str, max_chars: int = 9000) -> str:
    """Return a compact ArkUI-ish snippet for manual inspection."""
    if not content:
        return ""
    markers = ["@Entry", "@Component", "build()", "Column(", "Row(", "Text(", "Image("]
    positions = [content.find(marker) for marker in markers if content.find(marker) >= 0]
    start = max(0, min(positions) - 1200) if positions else 0
    snippet = content[start : start + max_chars]
    if start > 0:
        snippet = f"// ... earlier in {path}\n" + snippet
    if start + max_chars < len(content):
        snippet += "\n// ... truncated"
    return snippet


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


def load_config(config: str, dataset: str, dataset_dir: Path | None) -> list[dict]:
    if dataset_dir:
        ds = load_dataset("parquet", data_files=parquet_files(dataset_dir, config))
    else:
        ds = load_dataset(dataset, config)

    rows: list[dict] = []
    for split, part in ds.items():
        for row in part:
            item = dict(row)
            item["split"] = split
            rows.append(item)
    return rows


def balanced_review_queries(queries: list[dict], limit: int, min_per_query_type: int) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for query in queries:
        groups[query.get("query_type") or "unknown"].append(query)

    preferred_order = [
        "runtime_screenshot",
        "build_run_screenshot",
        "repo_screenshot",
        "doc_or_promo",
        "unknown",
    ]
    type_order = preferred_order + sorted(t for t in groups if t not in preferred_order)

    selected: list[dict] = []
    seen: set[str] = set()
    for query_type in type_order:
        for query in groups.get(query_type, [])[: min_per_query_type]:
            if query["query_id"] in seen:
                continue
            selected.append(query)
            seen.add(query["query_id"])
            if len(selected) >= limit:
                return selected

    for query in queries:
        if query["query_id"] in seen:
            continue
        selected.append(query)
        seen.add(query["query_id"])
        if len(selected) >= limit:
            break
    return selected


def evidence_value(evidence: list[str], prefix: str, default: str = "") -> str:
    for item in evidence or []:
        if item.startswith(prefix):
            return item[len(prefix):]
    return default


def evidence_source_type(evidence: list[str]) -> str:
    return evidence_value(evidence, "source:", "unknown")


def evidence_readme_candidates(evidence: list[str]) -> list[dict]:
    raw = evidence_value(evidence, "readme:candidates_json=", "[]")
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def iter_local_query_images(dataset_dir: Path | None) -> Iterable[Path]:
    if not dataset_dir:
        return []
    query_image_dir = dataset_dir / "intermediate" / "query_images"
    if not query_image_dir.exists():
        return []
    return (path for path in query_image_dir.iterdir() if path.is_file())


def save_query_image(query: dict, assets: Path, image_by_sha: dict[str, Path]) -> str | None:
    image_path = image_by_sha.get(query.get("image_sha256", ""))
    if image_path:
        asset_name = f"{query['query_id']}{image_path.suffix.lower()}"
        shutil.copy2(image_path, assets / asset_name)
        return asset_name

    image_obj = query.get("image")
    if not image_obj or not hasattr(image_obj, "save"):
        return None
    image_format = (getattr(image_obj, "format", None) or "PNG").lower()
    if image_format not in {"png", "jpeg", "jpg", "webp"}:
        image_format = "png"
    asset_name = f"{query['query_id']}.{image_format}"
    image_obj.save(assets / asset_name)
    return asset_name


def build_review_app(
    *,
    dataset: str,
    dataset_dir: Path | None,
    output: Path,
    limit: int,
    min_per_query_type: int,
) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    assets = output / "assets"
    if assets.exists():
        shutil.rmtree(assets)
    assets.mkdir(parents=True, exist_ok=True)

    queries = load_config("queries", dataset, dataset_dir)
    corpus = {row["file_id"]: row for row in load_config("corpus", dataset, dataset_dir)}
    symbols = {row["symbol_id"]: row for row in load_config("symbols", dataset, dataset_dir)}
    repos = {row["repo_id"]: row for row in load_config("repositories", dataset, dataset_dir)}

    image_by_sha: dict[str, Path] = {}
    for image_path in iter_local_query_images(dataset_dir):
        try:
            image_by_sha[hashlib.sha256(image_path.read_bytes()).hexdigest()] = image_path
        except OSError:
            pass

    queries.sort(
        key=lambda query: (
            {"test": 0, "validation": 1, "train": 2}.get(query["split"], 9),
            -float(query.get("label_confidence") or 0),
            -len(query.get("ocr_text") or ""),
            query["query_id"],
        )
    )
    selected_queries = balanced_review_queries(queries, limit, min_per_query_type)

    items: list[dict] = []
    skipped_missing_image: Counter[str] = Counter()
    for query in selected_queries:
        asset_name = save_query_image(query, assets, image_by_sha)
        if not asset_name:
            skipped_missing_image[query.get("query_type") or "unknown"] += 1
            continue

        positive_files = []
        for file_id in list(query.get("positive_file_ids") or [])[:8]:
            file_row = corpus.get(file_id)
            if not file_row:
                continue
            file_symbols = [
                symbols[symbol_id]
                for symbol_id in list(file_row.get("symbols") or [])[:20]
                if symbol_id in symbols
            ]
            positive_files.append(
                {
                    "file_id": file_id,
                    "path": file_row["path"],
                    "is_arkui_page": bool(file_row.get("is_arkui_page", False)),
                    "ui_text": list(file_row.get("ui_text") or [])[:30],
                    "imports": list(file_row.get("imports") or [])[:30],
                    "routes": list(file_row.get("routes") or [])[:20],
                    "content_sha256": file_row.get("content_sha256", ""),
                    "content_available": bool(file_row.get("content_available", False)),
                    "code": code_window(file_row.get("content", ""), file_row["path"]),
                    "symbols": [
                        {
                            "symbol_id": symbol["symbol_id"],
                            "qualified_name": symbol["qualified_name"],
                            "symbol_type": symbol["symbol_type"],
                            "start_line": symbol["start_line"],
                            "end_line": symbol["end_line"],
                            "ui_text": list(symbol.get("ui_text") or [])[:20],
                            "code": code_window(symbol.get("code", ""), symbol["qualified_name"], 4000),
                        }
                        for symbol in file_symbols[:8]
                    ],
                }
            )

        positive_symbol_cards = []
        for symbol_id in list(query.get("positive_symbol_ids") or [])[:12]:
            symbol = symbols.get(symbol_id)
            if not symbol:
                continue
            positive_symbol_cards.append(
                {
                    "symbol_id": symbol_id,
                    "file_id": symbol["file_id"],
                    "qualified_name": symbol["qualified_name"],
                    "symbol_type": symbol["symbol_type"],
                    "start_line": symbol["start_line"],
                    "end_line": symbol["end_line"],
                }
            )

        repo = repos.get(query["repo_id"], {})
        evidence = list(query.get("matching_evidence") or [])
        readme_candidates = evidence_readme_candidates(evidence)
        if not readme_candidates and query.get("readme_candidates_json"):
            try:
                parsed = json.loads(query.get("readme_candidates_json") or "[]")
                readme_candidates = parsed if isinstance(parsed, list) else []
            except json.JSONDecodeError:
                readme_candidates = []

        items.append(
            {
                "query_id": query["query_id"],
                "split": query["split"],
                "query_type": query.get("query_type", "unknown"),
                "repo_id": query["repo_id"],
                "repo_key": repo.get("repo_key", ""),
                "repo_url": repo.get("repo_url", ""),
                "commit": query["commit"],
                "source_url": query["source_url"],
                "source_path": query.get("source_path", ""),
                "source_type": query.get("source_type") or evidence_source_type(evidence),
                "image": f"assets/{asset_name}",
                "caption": query.get("caption", ""),
                "ocr_text": query.get("ocr_text", ""),
                "context_text": query.get("context_text", ""),
                "markdown_path": query.get("markdown_path") or evidence_value(evidence, "readme:markdown_path="),
                "markdown_heading": query.get("markdown_heading") or evidence_value(evidence, "readme:heading="),
                "markdown_line": query.get("markdown_line") or int(evidence_value(evidence, "readme:line=", "0") or 0),
                "readme_candidates": readme_candidates,
                "label_status": query.get("label_status", "automatic"),
                "label_confidence": query.get("label_confidence", 0.0),
                "matching_evidence": evidence,
                "positive_file_ids": list(query.get("positive_file_ids") or []),
                "positive_symbol_ids": list(query.get("positive_symbol_ids") or []),
                "positive_files": positive_files,
                "positive_symbols": positive_symbol_cards,
            }
        )

    shutil.copy2(TEMPLATE, output / "index.html")
    (output / "review_items.json").write_text(json.dumps(items, ensure_ascii=False, indent=2), "utf-8")

    stats = {
        "dataset": str(dataset_dir) if dataset_dir else dataset,
        "items": len(items),
        "assets": len(list(assets.iterdir())),
        "query_type_counts": dict(Counter(item["query_type"] for item in items)),
        "source_type_counts": dict(Counter(item["source_type"] for item in items)),
        "skipped_missing_image_by_query_type": dict(skipped_missing_image),
        "min_per_query_type": min_per_query_type,
    }
    (output / "review_app_stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), "utf-8")
    return stats


def serve(directory: Path, port: int) -> None:
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    with socketserver.TCPServer(("127.0.0.1", port), handler) as httpd:
        print(f"Serving review app at http://127.0.0.1:{port}/index.html")
        httpd.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a static human-review app for MM-ArkBench.")
    parser.add_argument("--dataset", default=DEFAULT_DATASET, help="Hugging Face dataset id.")
    parser.add_argument("--dataset-dir", type=Path, default=None, help="Local HF-style dataset directory.")
    parser.add_argument("--output", type=Path, default=ROOT / "review_app")
    parser.add_argument("--limit", type=int, default=300)
    parser.add_argument("--min-per-query-type", type=int, default=30)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--port", type=int, default=int(os.environ.get("MMARKBENCH_REVIEW_PORT", "8765")))
    args = parser.parse_args()

    stats = build_review_app(
        dataset=args.dataset,
        dataset_dir=args.dataset_dir,
        output=args.output,
        limit=args.limit,
        min_per_query_type=args.min_per_query_type,
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    if args.serve:
        serve(args.output, args.port)


if __name__ == "__main__":
    main()
