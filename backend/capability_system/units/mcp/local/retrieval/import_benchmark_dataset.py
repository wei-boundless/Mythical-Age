from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any


def _read_parquet_rows(path: Path) -> list[dict[str, Any]]:
    try:
        import pyarrow.parquet as pq  # type: ignore

        table = pq.read_table(path)
        return table.to_pylist()
    except Exception:
        import pandas as pd  # type: ignore

        frame = pd.read_parquet(path)
        return frame.to_dict(orient="records")


def _first_matching(data_dir: Path, prefix: str) -> Path:
    matches = sorted(path for path in data_dir.glob("*.parquet") if prefix in path.name)
    if not matches:
        raise FileNotFoundError(f"No parquet file containing '{prefix}' found under {data_dir}")
    return matches[0]


def _sanitize_filename(value: str) -> str:
    cleaned = "".join(ch for ch in value if ch.isalnum() or ch in {"-", "_"})
    return cleaned[:80] or "doc"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import benchmark corpus into a dedicated local test library.")
    parser.add_argument("--dataset-dir", required=True, help="Path to retrieval dataset directory")
    parser.add_argument("--target-dir", default="", help="Optional target dir under backend. Defaults to backend/knowledge-benchmark/ecomretrieval_5000")
    parser.add_argument("--max-docs", type=int, default=5000, help="How many documents to import")
    parser.add_argument("--seed", type=int, default=42, help="Deterministic sampling seed")
    parser.add_argument("--prefix", default="ecom", help="Filename prefix for imported docs")
    return parser


def main() -> int:
    args = _build_parser().parse_args()

    backend_dir = Path(__file__).resolve().parents[1]
    dataset_dir = Path(args.dataset_dir).resolve()
    data_dir = dataset_dir / "data"
    corpus_path = _first_matching(data_dir, "corpus")
    corpus_rows = _read_parquet_rows(corpus_path)

    if len(corpus_rows) <= args.max_docs:
        selected = corpus_rows
    else:
        rng = random.Random(args.seed)
        selected = rng.sample(corpus_rows, args.max_docs)
        selected.sort(key=lambda row: str(row.get("id", "")))

    target_dir = (
        (backend_dir / args.target_dir).resolve()
        if args.target_dir.strip()
        else (backend_dir / "knowledge-benchmark" / f"{args.prefix}retrieval_{args.max_docs}").resolve()
    )
    target_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    for row in selected:
        doc_id = str(row.get("id", "")).strip()
        text = str(row.get("text", "")).strip()
        if not doc_id or not text:
            continue
        filename = f"{args.prefix}_{_sanitize_filename(doc_id)}.json"
        payload = {
            "id": doc_id,
            "dataset": dataset_dir.name,
            "text": text,
        }
        (target_dir / filename).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        written += 1

    manifest = {
        "dataset_dir": str(dataset_dir),
        "target_dir": str(target_dir),
        "sample_size": written,
        "seed": args.seed,
        "prefix": args.prefix,
    }
    (target_dir / "_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
