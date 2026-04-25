from __future__ import annotations

import hashlib
import re
from pathlib import PurePosixPath
from typing import Any

from query.evidence_models import (
    DatasetCandidate,
    DocumentCandidate,
    EvidenceArtifact,
    EvidenceEnvelope,
    EvidenceItem,
    SourceObjectRef,
    TableCandidate,
)


DATASET_EXTENSIONS = {".xlsx", ".xls", ".csv", ".json", ".parquet"}
DOCUMENT_EXTENSIONS = {".pdf"}
TABLE_BLOCK_TYPES = {"table", "pdf_table", "spreadsheet", "csv_table", "html_table"}
PATH_PATTERN = re.compile(r"([^\s,，;；:：\"'“”‘’]+?\.(?:xlsx|xls|csv|json|parquet|pdf))", re.IGNORECASE)


def build_evidence_envelope_from_retrieval(
    *,
    query: str,
    retrieval_results: list[dict[str, Any]] | None,
    source_worker: str = "retrieval",
) -> EvidenceEnvelope:
    evidence_items: list[EvidenceItem] = []
    source_objects_by_id: dict[str, SourceObjectRef] = {}
    artifacts_by_id: dict[str, EvidenceArtifact] = {}
    dataset_candidates_by_key: dict[str, DatasetCandidate] = {}
    document_candidates_by_key: dict[str, DocumentCandidate] = {}
    table_candidates_by_key: dict[str, TableCandidate] = {}

    for rank, result in enumerate(list(retrieval_results or []), start=1):
        metadata = dict(result.get("metadata", {}) or {})
        source = _source_from_result(result)
        text = str(result.get("text", "") or "").strip()
        score = _float_score(result.get("score", result.get("retrieval_score", 0.0)))
        object_type = _object_type_from_source(source, metadata)
        source_object = _source_object_from_result(source=source, metadata=metadata, object_type=object_type)
        source_objects_by_id[source_object.object_id] = source_object

        artifact = _artifact_from_result(
            result=result,
            source_object=source_object,
            metadata=metadata,
            rank=rank,
        )
        artifacts_by_id[artifact.artifact_id] = artifact

        evidence_items.append(
            EvidenceItem(
                kind=artifact.artifact_type,
                source=source,
                text=text,
                score=score,
                metadata={
                    **metadata,
                    "artifact_id": artifact.artifact_id,
                    "source_object_id": source_object.object_id,
                    "candidate_rank": rank,
                },
                visibility="model_visible",
            )
        )

        for path in _candidate_paths(source, metadata, text):
            suffix = PurePosixPath(path.replace("\\", "/")).suffix.lower()
            if suffix in DATASET_EXTENSIONS:
                key = _normalize_identity(path)
                dataset_candidates_by_key.setdefault(
                    key,
                        DatasetCandidate(
                            path=path,
                            target_object=_basename(path),
                        evidence_source=source,
                        confidence=max(score, 0.6),
                        reason="retrieval_source_dataset",
                        artifact_id=artifact.artifact_id,
                        source_object_id=source_object.object_id,
                    ),
                )
            elif suffix in DOCUMENT_EXTENSIONS:
                key = _normalize_identity(path)
                document_candidates_by_key.setdefault(
                    key,
                    DocumentCandidate(
                        path=path,
                        document_type="pdf",
                        page=_int_or_none(result.get("page") or metadata.get("page")),
                        confidence=max(score, 0.6),
                        reason="retrieval_source_document",
                        artifact_id=artifact.artifact_id,
                        source_object_id=source_object.object_id,
                    ),
                )

        if artifact.artifact_type in {"table_object", "pdf_table", "dataset_schema"}:
            table_candidates_by_key.setdefault(
                artifact.artifact_id,
                TableCandidate(
                    artifact_id=artifact.artifact_id,
                    source_object_id=source_object.object_id,
                    source_kind="pdf_table" if object_type == "pdf" else "spreadsheet",
                    locator={
                        "source": source,
                        "page": _int_or_none(result.get("page") or metadata.get("page")),
                        "block_id": metadata.get("block_id"),
                    },
                    schema_preview=_schema_preview(metadata),
                    confidence=max(score, 0.55),
                    reason="retrieval_table_artifact",
                ),
            )

    return EvidenceEnvelope(
        query=str(query or "").strip(),
        source_worker=source_worker,
        evidence_items=evidence_items,
        source_objects=list(source_objects_by_id.values()),
        derived_artifacts=list(artifacts_by_id.values()),
        document_candidates=list(document_candidates_by_key.values()),
        dataset_candidates=list(dataset_candidates_by_key.values()),
        table_candidates=list(table_candidates_by_key.values()),
        diagnostics={
            "retrieval_result_count": len(list(retrieval_results or [])),
            "dataset_candidate_count": len(dataset_candidates_by_key),
            "document_candidate_count": len(document_candidates_by_key),
            "table_candidate_count": len(table_candidates_by_key),
        },
    )


def _source_from_result(result: dict[str, Any]) -> str:
    source = str(result.get("source", "") or "").strip()
    if source:
        return source
    metadata = dict(result.get("metadata", {}) or {})
    return str(metadata.get("source", "") or metadata.get("file_path", "") or metadata.get("path", "") or "").strip()


def _source_object_from_result(*, source: str, metadata: dict[str, Any], object_type: str) -> SourceObjectRef:
    object_ref_id = str(metadata.get("object_ref_id", "") or "").strip()
    object_id = object_ref_id or _stable_id("source", source or repr(sorted(metadata.items())))
    return SourceObjectRef(
        object_id=object_id,
        object_type=object_type,
        uri=source,
        locator={
            "source": source,
            "page": _int_or_none(metadata.get("page")),
            "doc_id": metadata.get("doc_id"),
        },
        index_refs=[str(item) for item in (metadata.get("retrieval_modes", []) or [])],
        metadata=dict(metadata),
    )


def _artifact_from_result(
    *,
    result: dict[str, Any],
    source_object: SourceObjectRef,
    metadata: dict[str, Any],
    rank: int,
) -> EvidenceArtifact:
    block_id = str(metadata.get("block_id", "") or "").strip()
    artifact_id = block_id or _stable_id("artifact", f"{source_object.object_id}:{rank}:{result.get('text', '')}")
    artifact_type = _artifact_type_from_result(result, metadata)
    text = str(result.get("text", "") or "").strip()
    return EvidenceArtifact(
        artifact_id=artifact_id,
        artifact_type=artifact_type,
        source_object_id=source_object.object_id,
        content_ref=str(metadata.get("content_ref", "") or metadata.get("block_id", "") or source_object.uri),
        canonical_preview=_canonical_preview(text, artifact_type=artifact_type),
        visibility="model_visible",
        consumable_by=_consumable_by(artifact_type),
        metadata={
            **metadata,
            "source": source_object.uri,
            "rank": rank,
        },
    )


def _artifact_type_from_result(result: dict[str, Any], metadata: dict[str, Any]) -> str:
    block_type = str(metadata.get("block_type", "") or result.get("block_type", "") or "").strip().lower()
    granularity = str(result.get("result_granularity", "") or metadata.get("result_granularity", "") or "").strip().lower()
    modality = str(result.get("modality", "") or metadata.get("modality", "") or "").strip().lower()
    source = _source_from_result(result).lower()
    if block_type in TABLE_BLOCK_TYPES or modality == "table":
        return "pdf_table" if source.endswith(".pdf") else "table_object"
    if source.endswith(".pdf") and (result.get("page") or metadata.get("page") or granularity == "page"):
        return "pdf_page"
    if PurePosixPath(source.replace("\\", "/")).suffix.lower() in DATASET_EXTENSIONS:
        return "dataset_summary" if block_type != "schema" else "dataset_schema"
    return "text_chunk"


def _object_type_from_source(source: str, metadata: dict[str, Any]) -> str:
    suffix = PurePosixPath(source.replace("\\", "/")).suffix.lower()
    if suffix == ".pdf":
        return "pdf"
    if suffix in DATASET_EXTENSIONS:
        return "dataset"
    modality = str(metadata.get("modality", "") or "").strip().lower()
    if modality == "table":
        return "table"
    return "text_chunk"


def _candidate_paths(source: str, metadata: dict[str, Any], text: str) -> list[str]:
    candidates: list[str] = []
    for value in (
        source,
        metadata.get("source"),
        metadata.get("file_path"),
        metadata.get("path"),
        metadata.get("doc_id"),
    ):
        candidate = str(value or "").strip()
        if candidate and PurePosixPath(candidate.replace("\\", "/")).suffix.lower() in DATASET_EXTENSIONS | DOCUMENT_EXTENSIONS:
            candidates.append(candidate)
    candidates.extend(match.group(1).strip() for match in PATH_PATTERN.finditer(text or ""))
    deduped: list[str] = []
    seen: set[str] = set()
    seen_names: set[str] = set()
    for candidate in candidates:
        key = _normalize_identity(candidate)
        basename = _basename(candidate).strip().lower()
        if (
            not key
            or key in seen
            or (basename and basename in seen_names)
            or any(_same_or_suffix_path(existing, key) for existing in seen)
        ):
            continue
        seen.add(key)
        if basename:
            seen_names.add(basename)
        deduped.append(candidate)
    return deduped


def _consumable_by(artifact_type: str) -> list[str]:
    if artifact_type in {"table_object", "pdf_table", "dataset_schema", "dataset_summary"}:
        return ["structured_data"]
    if artifact_type in {"pdf_page"}:
        return ["pdf", "answer_finalizer"]
    return ["answer_finalizer"]


def _canonical_preview(text: str, *, artifact_type: str) -> str:
    raw = str(text or "").strip()
    if artifact_type in {"pdf_table", "table_object"}:
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in raw.splitlines()]
        return "\n".join(line for line in lines if line)[:2000]
    return " ".join(raw.split())[:220]


def _schema_preview(metadata: dict[str, Any]) -> list[str]:
    for key in ("schema", "columns", "headers"):
        value = metadata.get(key)
        if isinstance(value, (list, tuple)):
            return [str(item) for item in value[:10] if str(item).strip()]
    return []


def _float_score(value: Any) -> float:
    try:
        return float(value or 0.0)
    except Exception:
        return 0.0


def _int_or_none(value: Any) -> int | None:
    try:
        parsed = int(value)
    except Exception:
        return None
    return parsed if parsed > 0 else None


def _stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha1(str(value or "").encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"


def _normalize_identity(value: str) -> str:
    return str(value or "").replace("\\", "/").strip().lower()


def _basename(value: str) -> str:
    return PurePosixPath(str(value or "").replace("\\", "/")).name


def _same_or_suffix_path(left: str, right: str) -> bool:
    if not left or not right:
        return False
    return left == right or left.endswith(right) or right.endswith(left)
