from __future__ import annotations

import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from memory import DurableAdmissionPolicy, DurableMutationPlanner, DurableStoreWriter
from memory.manifest_scan import scan_memory_headers
from memory.write_agent import DurableWriteExtractorAgent
from memory.write_models import DurableExtractionBundle
from structured_memory import MemoryManager


def test_write_agent_projection_extracts_stable_preference_but_not_task_local_request() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        manager = MemoryManager(Path(tmp) / "durable_memory")
        agent = DurableWriteExtractorAgent()

        stable_bundle = DurableExtractionBundle(
            session_id="s1",
            turn_id="t1",
            message_slice=[],
            main_context={"active_goal": "以后默认先给结论，再展开解释。"},
            task_summaries=[],
            corrections=[],
            session_projection={},
            manifest_headers=[],
        )
        task_local_bundle = DurableExtractionBundle(
            session_id="s1",
            turn_id="t2",
            message_slice=[],
            main_context={"active_goal": "回到 inventory.xlsx，给我最缺货的前三个仓库。"},
            task_summaries=[],
            corrections=[],
            session_projection={},
            manifest_headers=[],
        )

        stable_drafts = __import__("asyncio").run(agent.extract(stable_bundle))
        task_drafts = __import__("asyncio").run(agent.extract(task_local_bundle))

        assert stable_drafts
        assert any(draft.memory_class == "preference" for draft in stable_drafts)
        assert task_drafts == []


def test_admission_policy_rejects_task_local_and_accepts_stable_feedback() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        manager = MemoryManager(Path(tmp) / "durable_memory")
        agent = DurableWriteExtractorAgent()
        policy = DurableAdmissionPolicy()

        feedback_bundle = DurableExtractionBundle(
            session_id="s2",
            turn_id="t1",
            message_slice=[{"role": "user", "content": "下次请先给结论，不要在结尾重复总结，我会自己看 diff。"}],
            main_context={},
            task_summaries=[],
            corrections=[],
            session_projection={},
            manifest_headers=[],
        )
        drafts = __import__("asyncio").run(agent.extract(feedback_bundle))
        decisions = policy.evaluate_many(drafts, scan_memory_headers(manager.root_dir))

        assert decisions
        assert any(item.decision == "accept" for item in decisions)
        assert all(item.reason != "task_local_or_runtime_state" for item in decisions)


def test_mutation_plan_and_store_writer_persist_admitted_note() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        manager = MemoryManager(Path(tmp) / "durable_memory")
        agent = DurableWriteExtractorAgent()
        policy = DurableAdmissionPolicy()
        planner = DurableMutationPlanner()
        writer = DurableStoreWriter(manager)

        bundle = DurableExtractionBundle(
            session_id="s3",
            turn_id="t1",
            message_slice=[],
            main_context={"active_goal": "以后默认先给结论，再展开解释。"},
            task_summaries=[],
            corrections=[],
            session_projection={},
            manifest_headers=[],
        )

        drafts = __import__("asyncio").run(agent.extract(bundle))
        decisions = policy.evaluate_many(drafts, scan_memory_headers(manager.root_dir))
        plan = planner.build_plan(decisions)
        result = writer.apply(plan)

        assert result["count"] == 1
        headers = scan_memory_headers(manager.root_dir)
        assert len(headers) == 1
        assert headers[0].memory_class == "preference"
        assert headers[0].title
