from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from pdf_agent import PDFCanonicalEvidence, PDFCanonicalResult
from query.context_models import MainContextState
from query.evidence_orchestrator import EvidenceOrchestrator
from query.pdf_worker import PDFWorker
from query.worker_models import WorkerExecutionPlan, WorkerRequest
from query.worker_projection import WorkerProjectionAdapter


class _PDFRuntimeStub:
    def __init__(self, result: PDFCanonicalResult) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    def run(self, *, request, file_path):
        self.calls.append({"request": request, "file_path": file_path})
        return self.result


class _RetrievalWorkerStub:
    def run(self, _request):
        raise AssertionError("pdf worker route must not call retrieval worker")


class _OutputPolicyStub:
    def rag_evidence_pack_can_finalize(self, _pack):
        return False

    async def rewrite_rag_answer_with_model(self, *, evidence_pack):
        return ""


def test_pdf_worker_ok_result_projects_pdf_binding_pages_and_mode() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        pdf_path = root / "knowledge" / "reports" / "test.pdf"
        pdf_path.parent.mkdir(parents=True)
        pdf_path.write_bytes(b"%PDF-1.4\n")
        runtime = _PDFRuntimeStub(
            PDFCanonicalResult(
                status="ok",
                source="test.pdf",
                requested_mode="page",
                effective_mode="page",
                summary="已读取 P2。页面要点：这里讨论库存风险。",
                pages=[2],
                evidence=[PDFCanonicalEvidence(page_number=2, score=1.0, snippet="库存风险")],
            )
        )

        worker = PDFWorker(root_dir=root, runtime=runtime)
        result = asyncio.run(
            worker.run(
                WorkerRequest(
                    request_id="worker:pdf:test",
                    query="第二页讲了什么",
                    worker_route="pdf",
                    bindings={"active_pdf": "knowledge/reports/test.pdf"},
                    constraints={"mode": "page"},
                )
            )
        )
        projection = WorkerProjectionAdapter().project_done_event(
            query="第二页讲了什么",
            canonical_result=result.canonical_result,
            worker_result=result,
            previous_main_context=MainContextState(active_goal="读 PDF"),
        )

        assert result.status == "ok"
        assert result.canonical_result.ok is True
        assert result.canonical_result.bindings["active_pdf"] == "knowledge/reports/test.pdf"
        assert result.canonical_result.bindings["active_pdf_pages"] == [2]
        assert result.canonical_result.bindings["active_pdf_mode"] == "page"
        assert result.evidence_envelope is not None
        assert result.evidence_envelope.source_worker == "pdf"
        assert result.evidence_envelope.source_objects[0].object_type == "pdf"
        assert result.evidence_envelope.derived_artifacts[0].artifact_type == "pdf_page"
        assert result.evidence_envelope.derived_artifacts[0].content_ref == "knowledge/reports/test.pdf#page=2"
        assert result.evidence_envelope.document_candidates[0].path == "knowledge/reports/test.pdf"
        assert projection.main_context.active_constraints["active_pdf"] == "knowledge/reports/test.pdf"
        assert projection.main_context.active_constraints["active_pdf_pages"] == [2]
        assert projection.main_context.active_constraints["active_pdf_mode"] == "page"
        assert projection.task_summary_refs[0].task_kind == "pdf"
        assert "pdf_pages=2" in projection.task_summary_refs[0].key_points


def test_pdf_worker_degraded_result_does_not_project_stable_summary() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        pdf_path = root / "knowledge" / "reports" / "thin.pdf"
        pdf_path.parent.mkdir(parents=True)
        pdf_path.write_bytes(b"%PDF-1.4\n")
        runtime = _PDFRuntimeStub(
            PDFCanonicalResult(
                status="degraded",
                source="thin.pdf",
                requested_mode="page",
                effective_mode="page",
                summary="",
                degraded_reason="target_page_text_quality_low",
                pages=[3],
            )
        )

        worker = PDFWorker(root_dir=root, runtime=runtime)
        result = asyncio.run(
            worker.run(
                WorkerRequest(
                    request_id="worker:pdf:thin",
                    query="第三页讲了什么",
                    worker_route="pdf",
                    bindings={"active_pdf": "knowledge/reports/thin.pdf"},
                    constraints={"mode": "page"},
                )
            )
        )
        projection = WorkerProjectionAdapter().project_done_event(
            query="第三页讲了什么",
            canonical_result=result.canonical_result,
            worker_result=result,
            previous_main_context=MainContextState(active_goal="读 PDF"),
        )

        assert result.status == "degraded"
        assert result.canonical_result.ok is False
        assert result.canonical_result.projection_policy == "do_not_persist"
        assert "target_page_text_quality_low" in result.canonical_result.answer
        assert projection.memory_policy == "do_not_persist"
        assert projection.task_summary_refs == []
        assert projection.main_context.active_constraints["active_pdf"] == "knowledge/reports/thin.pdf"


def test_pdf_worker_section_result_projects_section_binding_and_handle() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        pdf_path = root / "knowledge" / "reports" / "section.pdf"
        pdf_path.parent.mkdir(parents=True)
        pdf_path.write_bytes(b"%PDF-1.4\n")
        runtime = _PDFRuntimeStub(
            PDFCanonicalResult(
                status="ok",
                source="section.pdf",
                requested_mode="section",
                effective_mode="section",
                summary="已定位第二部分。章节要点：先立规则，再补审计。",
                pages=[2, 3],
                evidence=[
                    PDFCanonicalEvidence(page_number=2, score=1.0, snippet="第二部分 约束条件"),
                    PDFCanonicalEvidence(page_number=3, score=0.9, snippet="继续说明审计归口"),
                ],
                metadata={"target_section": "第二部分", "target_section_key": "第二部分"},
            )
        )

        worker = PDFWorker(root_dir=root, runtime=runtime)
        result = asyncio.run(
            worker.run(
                WorkerRequest(
                    request_id="worker:pdf:section",
                    query="第二部分强调的约束是什么？",
                    worker_route="pdf",
                    bindings={"active_pdf": "knowledge/reports/section.pdf"},
                    constraints={"mode": "section", "pdf_section": "第二部分", "pdf_section_key": "第二部分"},
                )
            )
        )
        projection = WorkerProjectionAdapter().project_done_event(
            query="第二部分强调的约束是什么？",
            canonical_result=result.canonical_result,
            worker_result=result,
            previous_main_context=MainContextState(active_goal="读 PDF"),
        )

        assert result.canonical_result.bindings["active_pdf_section"] == "第二部分"
        assert result.canonical_result.bindings["active_pdf_section_key"] == "第二部分"
        assert result.canonical_result.primary_result_handle_id.endswith(":第二部分")
        assert result.emitted_result_handles[0]["result_kind"] == "pdf_section_summary"
        assert result.emitted_result_handles[0]["target_section_key"] == "第二部分"
        assert projection.main_context.active_constraints["active_pdf_mode"] == "section"
        assert projection.main_context.active_constraints["active_pdf_section"] == "第二部分"
        assert "pdf_section=第二部分" in projection.task_summary_refs[0].key_points


def test_evidence_orchestrator_routes_pdf_worker_to_done_event() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        pdf_path = root / "knowledge" / "reports" / "orchestrated.pdf"
        pdf_path.parent.mkdir(parents=True)
        pdf_path.write_bytes(b"%PDF-1.4\n")
        runtime = _PDFRuntimeStub(
            PDFCanonicalResult(
                status="ok",
                source="orchestrated.pdf",
                requested_mode="document",
                effective_mode="document",
                summary="文档要点：库存治理需要明确责任边界。",
                pages=[1, 2],
            )
        )
        orchestrator = EvidenceOrchestrator(
            retrieval_worker=_RetrievalWorkerStub(),
            pdf_worker=PDFWorker(root_dir=root, runtime=runtime),
            output_policy=_OutputPolicyStub(),
        )

        async def _run() -> list[dict[str, object]]:
            events: list[dict[str, object]] = []
            async for event in orchestrator.stream_execution(
                session_id="pdf-worker-session",
                execution=None,
                worker_plan=WorkerExecutionPlan(
                    worker_route="pdf",
                    request=WorkerRequest(
                        request_id="worker:pdf:orchestrated",
                        query="总结这份 PDF",
                        worker_route="pdf",
                        bindings={"active_pdf": "knowledge/reports/orchestrated.pdf"},
                    ),
                    expected_result="canonical",
                ),
                main_context=MainContextState(active_goal="总结这份 PDF"),
            ):
                events.append(event)
            return events

        events = asyncio.run(_run())
        done = next(event for event in reversed(events) if event.get("type") == "done")
        artifacts = next(event for event in events if event.get("type") == "worker_artifacts")

        assert [event.get("type") for event in events] == [
            "worker_start",
            "worker_evidence",
            "worker_artifacts",
            "worker_end",
            "done",
        ]
        assert artifacts["graph_delta"]["source_objects"][0]["object_type"] == "pdf"
        assert artifacts["graph_delta"]["artifacts"] == []
        assert done["answer_source"] == "pdf_worker"
        assert done["committed_bindings"]["active_pdf"] == "knowledge/reports/orchestrated.pdf"
        assert done["main_context"]["active_constraints"]["active_pdf_pages"] == [1, 2]
        assert done["memory_policy"] == "session_context_only"


def main() -> None:
    test_pdf_worker_ok_result_projects_pdf_binding_pages_and_mode()
    test_pdf_worker_degraded_result_does_not_project_stable_summary()
    test_pdf_worker_section_result_projects_section_binding_and_handle()
    test_evidence_orchestrator_routes_pdf_worker_to_done_event()
    print("ALL PASSED (pdf worker projection)")


if __name__ == "__main__":
    main()
