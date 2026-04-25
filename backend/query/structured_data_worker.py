from __future__ import annotations

import asyncio
import hashlib
from typing import Any

from query.evidence_models import EvidenceArtifact, EvidenceEnvelope, EvidenceItem, SourceObjectRef
from query.worker_models import CanonicalResult, WorkerRequest, WorkerResult


class StructuredDataWorker:
    def __init__(self, *, tool_runtime) -> None:
        self.tool_runtime = tool_runtime

    async def run(self, request: WorkerRequest) -> WorkerResult:
        dataset_path = str(request.bindings.get("active_dataset", "") or "").strip()
        active_table = str(request.bindings.get("active_table", "") or "").strip()
        if not dataset_path:
            return WorkerResult(
                worker_name="structured_data",
                status="clarify",
                canonical_result=CanonicalResult(
                    result_kind="structured_answer",
                    ok=False,
                    answer=(
                        "已确认表格候选，但它还没有可直接分析的数据文件。需要先把该表格抽取或物化为结构化数据。"
                        if active_table
                        else "需要先确认要分析的数据表。"
                    ),
                    bindings={"active_table": active_table} if active_table else {},
                    projection_policy="do_not_persist",
                    degraded_reason="missing_dataset_binding",
                    diagnostics={"answer_source": "structured_data_worker"},
                ),
            )
        tool = self.tool_runtime.get_instance("structured_data_analysis")
        if tool is None:
            return WorkerResult(
                worker_name="structured_data",
                status="error",
                canonical_result=CanonicalResult(
                    result_kind="structured_answer",
                    ok=False,
                    answer="结构化数据分析能力当前不可用。",
                    degraded_reason="structured_tool_unavailable",
                ),
            )

        tool_input = {
            "query": str(request.query or "").strip(),
            "path": dataset_path,
        }
        raw_output = await asyncio.to_thread(tool.invoke, tool_input)
        answer = _visible_answer(raw_output)
        ok = bool(answer) and not answer.startswith("结构化分析失败")
        return WorkerResult(
            worker_name="structured_data",
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
                answer=answer or "结构化数据分析未形成可展示结果。",
                bindings={
                    **({"active_dataset": dataset_path} if dataset_path else {}),
                    **({"active_table": active_table} if active_table else {}),
                },
                projection_policy="persist_canonical" if ok else "do_not_persist",
                degraded_reason="" if ok else "structured_analysis_missing_answer",
                diagnostics={"tool": "structured_data_analysis", "answer_source": "structured_data_worker"},
            ),
            diagnostics={"tool_input": tool_input},
        )

    def _to_evidence_envelope(
        self,
        *,
        request: WorkerRequest,
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
            source_worker="structured_data",
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


def _stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha1(str(value or "").encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"
