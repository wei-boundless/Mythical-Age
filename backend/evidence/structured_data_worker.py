from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Any

from evidence.models import EvidenceArtifact, EvidenceEnvelope, EvidenceItem, SourceObjectRef
from .mcp_models import CanonicalResult, MCPRequest, MCPResult
from capability_system.capabilities.structured_data import (
    StructuredDataArtifactBuilder,
    StructuredDataCatalog,
    StructuredDataEngine,
    StructuredDataPlanner,
)
from capability_system.capabilities.structured_data.subset_selection import extract_structured_subset_selection


class StructuredDataWorker:
    def __init__(self, *, root_dir: Path | str) -> None:
        self.root_dir = Path(root_dir).resolve()
        self.planner = StructuredDataPlanner()
        self.engine = StructuredDataEngine()
        self.artifact_builder = StructuredDataArtifactBuilder(root_dir=self.root_dir)

    async def run(self, request: MCPRequest) -> MCPResult:
        dataset_path = str(request.bindings.get("active_dataset", "") or "").strip()
        active_table = str(request.bindings.get("active_table", "") or "").strip()
        if not dataset_path:
            return MCPResult(
                mcp_name="structured_data",
                status="clarify",
                canonical_result=CanonicalResult(
                    result_kind="structured_answer",
                    ok=False,
                    answer="",
                    bindings={"active_table": active_table} if active_table else {},
                    projection_policy="do_not_persist",
                    degraded_reason="missing_dataset_binding",
                    diagnostics={"answer_source": "structured_data_worker"},
                    degraded_reason_typed="missing_object_handle",
                ),
            )
        tool_input = {
            "query": str(request.query or "").strip(),
            "path": dataset_path,
            "semantic_hints": _semantic_hints_from_request(request),
        }
        answer = await asyncio.to_thread(
            self._run_structured_analysis,
            query=tool_input["query"],
            path=dataset_path,
            semantic_hints=tool_input["semantic_hints"],
        )
        if not answer:
            return MCPResult(
                mcp_name="structured_data",
                status="error",
                canonical_result=CanonicalResult(
                    result_kind="structured_answer",
                    ok=False,
                    answer="",
                    degraded_reason="structured_mcp_unavailable",
                    degraded_reason_typed="contract_blocked",
                ),
            )

        ok = bool(answer) and not answer.startswith("结构化分析失败")
        source_object_id = _stable_id("source:dataset", dataset_path)
        result_handle_ids = [f"result:structured_answer:{source_object_id.split(':')[-1]}:primary"] if dataset_path else []
        subset_selection = extract_structured_subset_selection(answer)
        subset_labels = list(subset_selection.labels)
        subset_handle_id = f"subset:selection:{source_object_id.split(':')[-1]}:primary" if subset_labels else ""
        return MCPResult(
            mcp_name="structured_data",
            status="ok" if ok else "degraded",
            evidence_envelope=self._to_evidence_envelope(
                request=request,
                dataset_path=dataset_path,
                answer=answer,
                ok=ok,
            ),
            canonical_result=CanonicalResult(
                result_kind="structured_answer",
                ok=ok,
                answer=answer if ok else "",
                bindings={
                    **({"active_dataset": dataset_path} if dataset_path else {}),
                    **({"active_table": active_table} if active_table else {}),
                },
                projection_policy="persist_canonical" if ok else "do_not_persist",
                degraded_reason="" if ok else "structured_analysis_missing_answer",
                diagnostics={"mcp": "structured_data", "answer_source": "structured_data_worker"},
                object_handle_ids=[source_object_id] if dataset_path else [],
                result_handle_ids=result_handle_ids,
                primary_result_handle_id=result_handle_ids[0] if result_handle_ids else "",
                degraded_reason_typed="" if ok else _typed_structured_degraded_reason(answer),
                presentation_hints={
                    "subset_handle_id": subset_handle_id,
                    "subset_labels": subset_labels,
                    "subset_filter_column": str(subset_selection.filter_column or ""),
                },
            ),
            emitted_object_handles=[
                {
                    "handle_id": source_object_id,
                    "handle_kind": "source_object",
                    "object_type": "dataset",
                    "uri": dataset_path,
                }
            ] if dataset_path else [],
            emitted_result_handles=[
                {
                    "handle_id": result_handle_ids[0],
                    "handle_kind": "result",
                    "result_kind": "structured_answer",
                    "object_handle_id": source_object_id,
                }
            ]
            + (
                [
                    {
                        "handle_id": subset_handle_id,
                        "handle_kind": "subset",
                        "subset_kind": "selection",
                        "result_handle_id": result_handle_ids[0] if result_handle_ids else "",
                        "labels": subset_labels,
                        "filter_column": str(subset_selection.filter_column or ""),
                    }
                ]
                if subset_handle_id
                else []
            ),
            diagnostics={"tool_input": tool_input},
            binding_owner_task_id=str(request.owner_task_id or "").strip(),
        )

    def _run_structured_analysis(
        self,
        *,
        query: str,
        path: str,
        semantic_hints: dict[str, Any],
    ) -> str:
        try:
            file_path = self._resolve_explicit_path(path)
        except ValueError as exc:
            code = str(exc)
            if code == "file_does_not_exist":
                return "结构化分析失败：文件不存在。"
            if code == "path_is_directory":
                return "结构化分析失败：给定路径是目录。"
            return f"结构化分析失败：{exc}"
        try:
            df = _load_dataframe(file_path)
        except Exception as exc:
            return f"结构化分析失败：无法读取文件。{exc}"
        df = self.planner.normalize_columns(df)
        rel_path = StructuredDataCatalog.relative_path(self.root_dir, file_path)
        self.artifact_builder.save_profile(rel_path, df)
        plan = self.planner.build_plan(
            query=query,
            df=df,
            dataset_rel_path=rel_path,
            requested_analysis_type=str(semantic_hints.get("analysis_type_hint", "") or "auto"),
            sheet_name=str(semantic_hints.get("sheet_name", "") or ""),
            limit=_safe_limit(semantic_hints.get("limit")),
            semantic_hints=semantic_hints,
        )
        return self.engine.execute(plan=plan, df=df, file_path=file_path).strip()

    def _resolve_explicit_path(self, path: str) -> Path:
        normalized = str(path or "").strip()
        if not normalized:
            raise ValueError("missing_explicit_dataset_path")
        candidates = StructuredDataCatalog.list_dataset_paths(self.root_dir)
        matched = StructuredDataCatalog._match_filename(self.root_dir, candidates, normalized)
        if matched is not None:
            return matched
        resolved = StructuredDataCatalog.resolve_dataset_path(self.root_dir, normalized, normalized)
        if not resolved.exists():
            raise ValueError("file_does_not_exist")
        if resolved.is_dir():
            raise ValueError("path_is_directory")
        return resolved

    def _to_evidence_envelope(
        self,
        *,
        request: MCPRequest,
        dataset_path: str,
        answer: str,
        ok: bool,
    ) -> EvidenceEnvelope:
        source_object_id = _stable_id("source:dataset", dataset_path)
        artifact_id = _stable_id("artifact:dataset_analysis", f"{dataset_path}:{request.query}:{answer[:160]}")
        preview = " ".join(str(answer or "").split())[:220]
        source_object = SourceObjectRef(
            object_id=source_object_id,
            object_type="dataset",
            uri=dataset_path,
            locator={"path": dataset_path},
            metadata={"worker": "structured_data"},
        )
        artifact = EvidenceArtifact(
            artifact_id=artifact_id,
            artifact_type="dataset_analysis",
            source_object_id=source_object_id,
            content_ref=f"{dataset_path}#analysis",
            canonical_preview=preview,
            visibility="model_visible" if ok else "debug_only",
            consumable_by=["answer_finalizer"],
            metadata={
                "active_dataset": dataset_path,
                "active_table": str(request.bindings.get("active_table", "") or "").strip(),
                "confidence": 1.0 if ok else 0.0,
            },
        )
        evidence_item = EvidenceItem(
            kind="dataset_analysis",
            source=dataset_path,
            text=preview,
            score=1.0 if ok else 0.0,
            metadata={
                "artifact_id": artifact_id,
                "source_object_id": source_object_id,
            },
            visibility="model_visible" if ok else "debug_only",
        )
        return EvidenceEnvelope(
            query=str(request.query or "").strip(),
            source_mcp="structured_data",
            evidence_items=[evidence_item] if preview else [],
            source_objects=[source_object],
            derived_artifacts=[artifact],
            diagnostics={
                "dataset_path": dataset_path,
                "analysis_ok": ok,
                "evidence_count": 1 if preview else 0,
            },
        )


def _visible_answer(output: Any) -> str:
    if isinstance(output, str):
        return output.strip()
    if isinstance(output, dict):
        for key in ("answer", "summary", "result", "output", "text", "content"):
            value = output.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return str(output or "").strip()


def _load_dataframe(file_path: Path):
    import pandas as pd

    suffix = file_path.suffix.lower()
    if suffix == ".xlsx":
        return pd.read_excel(file_path, sheet_name=0)
    if suffix == ".csv":
        return pd.read_csv(file_path)
    if suffix == ".json":
        try:
            return pd.read_json(file_path)
        except ValueError:
            return pd.read_json(file_path, lines=True)
    raise ValueError("目前仅支持 xlsx/csv/json 结构化分析。")


def _safe_limit(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 10
    return max(1, min(parsed, 50))


def _stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha1(str(value or "").encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"


def _typed_structured_degraded_reason(answer: str) -> str:
    normalized = str(answer or "")
    if "没有匹配记录" in normalized:
        return "empty_filtered_result"
    return "evidence_insufficient_for_synthesis"


def _semantic_hints_from_request(request: MCPRequest) -> dict[str, Any]:
    constraints = dict(request.constraints or {})
    semantic_hints = dict(constraints.get("semantic_hints") or {})
    for key in ("analysis_type_hint", "state_kind", "group_hint", "metric_hint", "query_mode_hint"):
        value = constraints.get(key)
        if value not in ("", None) and key not in semantic_hints:
            semantic_hints[key] = value
    subset_filter_column = str(constraints.get("subset_filter_column", "") or "").strip()
    subset_labels = [
        str(item or "").strip()
        for item in list(constraints.get("subset_labels", []) or [])
        if str(item or "").strip()
    ]
    if subset_filter_column and subset_labels:
        semantic_hints["subset_filter_column"] = subset_filter_column
        semantic_hints["subset_allowed_values"] = subset_labels
    return semantic_hints


