from __future__ import annotations

import asyncio
from typing import Any

from query.worker_models import CanonicalResult, WorkerRequest, WorkerResult


class StructuredDataWorker:
    def __init__(self, *, tool_runtime) -> None:
        self.tool_runtime = tool_runtime

    async def run(self, request: WorkerRequest) -> WorkerResult:
        dataset_path = str(request.bindings.get("active_dataset", "") or "").strip()
        if not dataset_path:
            return WorkerResult(
                worker_name="structured_data",
                status="clarify",
                canonical_result=CanonicalResult(
                    result_kind="structured_answer",
                    ok=False,
                    answer="需要先确认要分析的数据表。",
                    degraded_reason="missing_dataset_binding",
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
            canonical_result=CanonicalResult(
                result_kind="structured_answer",
                ok=ok,
                answer=answer or "结构化数据分析未形成可展示结果。",
                bindings={"active_dataset": dataset_path},
                projection_policy="persist_canonical" if ok else "do_not_persist",
                degraded_reason="" if ok else "structured_analysis_missing_answer",
                diagnostics={"tool": "structured_data_analysis", "answer_source": "structured_data_worker"},
            ),
            diagnostics={"tool_input": tool_input},
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
