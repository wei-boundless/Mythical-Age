from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any


BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from RAG.parser_adapter import MultimodalParserAdapter
from pdf_analysis.engine import PdfAnalysisEngine
from pdf_analysis.parser import PdfSegment, PdfTextParser


@dataclass(slots=True)
class SampleSpec:
    key: str
    label: str
    preferred_tokens: tuple[str, ...]
    folder_hint: str
    browse_query: str
    deep_query: str
    page_target: int


@dataclass(slots=True)
class DocumentCapabilityResult:
    key: str
    label: str
    relative_path: str
    size_bytes: int
    parser: dict[str, Any]
    engine: dict[str, Any]
    rag: dict[str, Any]
    findings: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)


SAMPLE_SPECS: tuple[SampleSpec, ...] = (
    SampleSpec(
        key="finance_report",
        label="table-heavy financial report",
        preferred_tokens=("航天动力", "Q3"),
        folder_hint="Financial Report Data",
        browse_query="营业收入 利润 现金流 财务指标",
        deep_query="请概括这份财报的主要财务情况、重点指标和风险提示",
        page_target=3,
    ),
    SampleSpec(
        key="industry_report",
        label="long AI industry report",
        preferred_tokens=("全球人工智能技术应用洞察报告",),
        folder_hint="AI Knowledge",
        browse_query="人工智能 技术 应用 趋势 市场",
        deep_query="请概括这份 AI 报告的主要主题、结构和结论",
        page_target=10,
    ),
    SampleSpec(
        key="governance_report",
        label="governance or compliance report",
        preferred_tokens=("安全治理研究报告", "合规备案指南", "治理报告"),
        folder_hint="AI Knowledge",
        browse_query="治理 合规 风险 安全 监管",
        deep_query="请概括这份治理报告的重点建议、风险框架和合规关注点",
        page_target=5,
    ),
)


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _artifact_path(path: str | None) -> Path:
    if path:
        return Path(path)
    stamp = date.today().strftime("%Y%m%d")
    return BACKEND_DIR / "tests" / "_artifacts" / f"pdf_processing_capability_{stamp}.json"


def _list_pdfs() -> list[Path]:
    return sorted((BACKEND_DIR / "knowledge").rglob("*.pdf"))


def _pick_sample(spec: SampleSpec, pdfs: list[Path]) -> Path:
    preferred: list[Path] = []
    fallback: list[Path] = []
    for path in pdfs:
        rel = path.relative_to(BACKEND_DIR).as_posix()
        if spec.folder_hint and spec.folder_hint not in rel:
            continue
        lowered = rel.lower()
        if all(token.lower() in lowered for token in spec.preferred_tokens):
            preferred.append(path)
        elif any(token.lower() in lowered for token in spec.preferred_tokens):
            fallback.append(path)

    if preferred:
        return sorted(preferred, key=lambda item: item.stat().st_size)[0]
    if fallback:
        return sorted(fallback, key=lambda item: item.stat().st_size)[0]

    candidates = [
        path
        for path in pdfs
        if spec.folder_hint in path.relative_to(BACKEND_DIR).as_posix()
    ]
    if not candidates:
        raise FileNotFoundError(f"No PDF sample found for {spec.key}.")
    return sorted(candidates, key=lambda item: item.stat().st_size)[0]


def _time_call(fn, *args, **kwargs) -> tuple[Any, float]:
    started = time.perf_counter()
    value = fn(*args, **kwargs)
    elapsed = time.perf_counter() - started
    return value, round(elapsed, 3)


def _page_sequence(segments: list[PdfSegment]) -> list[int]:
    return [segment.page for segment in segments if segment.page is not None]


def _probe_parser(parser: PdfTextParser, path: Path) -> tuple[dict[str, Any], list[PdfSegment]]:
    remote, remote_seconds = _time_call(parser._load_remote_result, path)  # noqa: SLF001
    pages, pages_seconds = _time_call(parser.extract_pages, path)
    segments, segments_seconds = _time_call(parser.extract_segments, path)

    page_sequence = _page_sequence(segments)
    modality_counts = Counter(segment.modality for segment in segments)
    parser_names = Counter(str(segment.metadata.get("parser", "unknown")) for segment in segments)

    result = {
        "remote_available": remote is not None,
        "remote_source": (remote.metadata if remote else {}).get("source"),
        "remote_markdown_len": len(remote.markdown) if remote else 0,
        "remote_block_count": len(remote.blocks) if remote else 0,
        "page_count": len(pages),
        "segment_count": len(segments),
        "section_count": sum(1 for segment in segments if segment.section),
        "nonempty_text_pages": sum(1 for _, text in pages if text.strip()),
        "modality_counts": dict(modality_counts),
        "segment_parser_counts": dict(parser_names),
        "page_span": [
            min(page_sequence) if page_sequence else None,
            max(page_sequence) if page_sequence else None,
        ],
        "segment_page_head": page_sequence[:12],
        "segment_page_tail": page_sequence[-12:],
        "segment_order_is_monotonic": page_sequence == sorted(page_sequence),
        "timings_seconds": {
            "remote": remote_seconds,
            "extract_pages": pages_seconds,
            "extract_segments": segments_seconds,
        },
    }
    return result, segments


def _probe_engine(engine: PdfAnalysisEngine, spec: SampleSpec, path: Path) -> dict[str, Any]:
    browse_output, browse_seconds = _time_call(
        engine.execute,
        query=spec.browse_query,
        file_path=path,
        mode="browse",
    )
    deep_output, deep_seconds = _time_call(
        engine.execute,
        query=spec.deep_query,
        file_path=path,
        mode="deep_read",
    )
    page_output_cn, page_seconds_cn = _time_call(
        engine.execute,
        query=f"请阅读第{spec.page_target}页",
        file_path=path,
        mode="page_read",
    )
    page_output_en, page_seconds_en = _time_call(
        engine.execute,
        query=f"What does page {spec.page_target} say?",
        file_path=path,
        mode="page_read",
    )

    def summarize_output(text: str) -> dict[str, Any]:
        lowered = text.lower()
        return {
            "ok": "failed:" not in lowered,
            "contains_summary": "summary:" in lowered,
            "contains_evidence": "evidence snippets:" in lowered,
            "contains_relevant_pages": "relevant pages:" in lowered,
            "contains_target_page": f"target page: p{spec.page_target}".lower() in lowered,
            "preview": text[:500],
            "length": len(text),
        }

    return {
        "browse": {
            **summarize_output(browse_output),
            "timing_seconds": browse_seconds,
        },
        "deep_read": {
            **summarize_output(deep_output),
            "timing_seconds": deep_seconds,
        },
        "page_read_cn": {
            **summarize_output(page_output_cn),
            "timing_seconds": page_seconds_cn,
        },
        "page_read_en": {
            **summarize_output(page_output_en),
            "timing_seconds": page_seconds_en,
        },
    }


def _probe_rag(
    adapter: MultimodalParserAdapter,
    parser_segments: list[PdfSegment],
    path: Path,
) -> dict[str, Any]:
    chunks, parse_seconds = _time_call(adapter.parse_file, path)
    limited_segments = adapter._limit_pdf_segments(parser_segments)  # noqa: SLF001
    chunk_pages = [chunk.page for chunk in chunks if chunk.page is not None]
    parser_pages = _page_sequence(parser_segments)
    parser_unique_pages = sorted(set(parser_pages))
    chunk_unique_pages = sorted(set(chunk_pages))
    expected_chunk_pages: list[int] = []
    for page in sorted({segment.page for segment in limited_segments if segment.page is not None}):
        page_segments = [segment for segment in limited_segments if segment.page == page]
        if any(
            adapter._clean_text(
                segment.text,
                modality=segment.modality,
                section=segment.section,
            ).strip()
            for segment in page_segments
        ):
            expected_chunk_pages.append(page)

    return {
        "chunk_count": len(chunks),
        "unique_pages": chunk_unique_pages,
        "unique_page_count": len(chunk_unique_pages),
        "page_span": [
            min(chunk_unique_pages) if chunk_unique_pages else None,
            max(chunk_unique_pages) if chunk_unique_pages else None,
        ],
        "page_metadata_coverage_ratio": round(
            len(chunk_pages) / len(chunks),
            3,
        ) if chunks else 0.0,
        "page_window_coverage_ratio": round(
            len(chunk_unique_pages) / max(len(parser_unique_pages), 1),
            3,
        ),
        "modality_counts": dict(Counter(chunk.modality for chunk in chunks)),
        "parser_counts": dict(Counter(str(chunk.metadata.get("parser", "unknown")) for chunk in chunks)),
        "section_count": sum(1 for chunk in chunks if chunk.section),
        "expected_window_pages": expected_chunk_pages,
        "missing_pages_after_cleaning": [page for page in expected_chunk_pages if page not in chunk_unique_pages],
        "first_pages_match_expected_window": chunk_unique_pages == expected_chunk_pages,
        "preview_pages": chunk_pages[:12],
        "timing_seconds": parse_seconds,
    }


def _derive_findings(
    spec: SampleSpec,
    parser_result: dict[str, Any],
    engine_result: dict[str, Any],
    rag_result: dict[str, Any],
) -> tuple[list[str], list[str]]:
    findings: list[str] = []
    limitations: list[str] = []

    if parser_result["page_count"] > 0 and parser_result["segment_count"] > 0:
        findings.append("Parser extracted stable page and segment text.")
    if parser_result["remote_available"]:
        findings.append("MinerU cloud parsing succeeded and remote structure was available.")
    if parser_result["segment_order_is_monotonic"]:
        findings.append("Segment order is monotonic, so downstream RAG can ingest pages in reading order.")
    if engine_result["browse"]["ok"] and engine_result["deep_read"]["ok"]:
        findings.append("Browse and deep-read modes both returned structured outputs with summaries.")
    if engine_result["page_read_cn"]["ok"] and engine_result["page_read_en"]["ok"]:
        findings.append("Page targeting works for both Chinese and English page queries.")
    if rag_result["chunk_count"] > 0 and rag_result["first_pages_match_expected_window"]:
        findings.append("RAG ingestion preserves the leading page window instead of sampling arbitrary later pages.")

    if spec.key == "finance_report" and rag_result["modality_counts"].get("table", 0) == 0:
        limitations.append("Financial-report parsing still surfaces text-only chunks; table modality promotion is not landing yet.")
    if parser_result["section_count"] == 0 and rag_result["section_count"] == 0:
        limitations.append("Section and heading structure is mostly absent in current parsed output.")
    if parser_result["timings_seconds"]["remote"] >= 60:
        limitations.append("Remote MinerU parsing latency is high on real documents and should be treated as an asynchronous or cached step.")
    if rag_result["missing_pages_after_cleaning"]:
        limitations.append("RAG ingestion did not keep the full expected leading page window.")

    return findings, limitations


def adapter_page_limit() -> int:
    return MultimodalParserAdapter(repo_root=PROJECT_ROOT).max_pdf_pages


def _run_document(
    parser: PdfTextParser,
    engine: PdfAnalysisEngine,
    adapter: MultimodalParserAdapter,
    spec: SampleSpec,
    path: Path,
) -> DocumentCapabilityResult:
    parser_result, segments = _probe_parser(parser, path)
    _assert(parser_result["page_count"] > 0, f"{path.name} produced no readable pages")
    _assert(parser_result["segment_count"] > 0, f"{path.name} produced no readable segments")

    engine_result = _probe_engine(engine, spec, path)
    rag_result = _probe_rag(adapter, segments, path)
    findings, limitations = _derive_findings(spec, parser_result, engine_result, rag_result)

    return DocumentCapabilityResult(
        key=spec.key,
        label=spec.label,
        relative_path=path.relative_to(BACKEND_DIR).as_posix(),
        size_bytes=path.stat().st_size,
        parser=parser_result,
        engine=engine_result,
        rag=rag_result,
        findings=findings,
        limitations=limitations,
    )


def _aggregate(results: list[DocumentCapabilityResult]) -> dict[str, Any]:
    remote_latencies = [item.parser["timings_seconds"]["remote"] for item in results]
    page_counts = [item.parser["page_count"] for item in results]
    segment_counts = [item.parser["segment_count"] for item in results]
    chunk_counts = [item.rag["chunk_count"] for item in results]
    table_docs = sum(1 for item in results if item.rag["modality_counts"].get("table", 0) > 0)

    strengths: list[str] = []
    weaknesses: list[str] = []

    if all(item.parser["remote_available"] for item in results):
        strengths.append("Official MinerU cloud parsing succeeded across all sampled PDFs.")
    if all(item.engine["page_read_cn"]["ok"] and item.engine["page_read_en"]["ok"] for item in results):
        strengths.append("The PDF analysis engine supports stable bilingual page targeting.")
    if all(item.rag["chunk_count"] > 0 for item in results):
        strengths.append("All sampled PDFs can be converted into RAG-ready chunks with page metadata.")
    if all(item.rag["first_pages_match_expected_window"] for item in results):
        strengths.append("The RAG adapter now preserves the first-page window instead of ingesting reversed tail pages.")

    if table_docs == 0:
        weaknesses.append("Chunk modality promotion is still weak: tested PDFs surfaced as text-only even when tables are visually present.")
    if any(item.parser["section_count"] == 0 for item in results):
        weaknesses.append("Structured headings/sections are still sparse, so navigation mostly relies on page text rather than document hierarchy.")
    if remote_latencies and max(remote_latencies) >= 60:
        weaknesses.append("Cloud parsing latency is significant on real PDFs and should be amortized through caching, async preprocessing, or persisted parse artifacts.")

    return {
        "document_count": len(results),
        "page_count_total": sum(page_counts),
        "segment_count_total": sum(segment_counts),
        "chunk_count_total": sum(chunk_counts),
        "remote_latency_seconds": {
            "min": min(remote_latencies) if remote_latencies else 0.0,
            "max": max(remote_latencies) if remote_latencies else 0.0,
            "median": round(statistics.median(remote_latencies), 3) if remote_latencies else 0.0,
        },
        "strengths": strengths,
        "weaknesses": weaknesses,
    }


def main() -> None:
    parser_cli = argparse.ArgumentParser()
    parser_cli.add_argument("--output", type=str, default="", help="Optional artifact output path")
    args = parser_cli.parse_args()

    pdfs = _list_pdfs()
    selected = [(spec, _pick_sample(spec, pdfs)) for spec in SAMPLE_SPECS]

    parser = PdfTextParser(root_dir=BACKEND_DIR)
    engine = PdfAnalysisEngine(root_dir=BACKEND_DIR, parser=parser)
    adapter = MultimodalParserAdapter(repo_root=PROJECT_ROOT)
    adapter._pdf_parser = parser

    results = [
        _run_document(parser, engine, adapter, spec, path)
        for spec, path in selected
    ]

    payload = {
        "ok": True,
        "artifact_date": date.today().isoformat(),
        "samples": [asdict(item) for item in results],
        "aggregate": _aggregate(results),
    }

    artifact = _artifact_path(args.output or None)
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"artifact={artifact}")


if __name__ == "__main__":
    main()
