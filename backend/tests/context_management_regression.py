from __future__ import annotations

import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from memory import MemoryFacade
from query.prompt_builder import build_system_prompt
from runtime.session_store import SessionManager
from structured_memory import ContextCompactor, Message, SessionMemoryManager


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _session_manager_with_summary(tmp: Path) -> tuple[SessionManager, str]:
    manager = SessionManager(tmp)
    session = manager.create_session("test")
    session_id = str(session["id"])
    manager.save_message(session_id, "user", "Original early user question")
    manager.save_message(session_id, "assistant", "Original early answer")
    manager.compress_history(session_id, "Archived summary of early turns", 2)
    manager.save_message(session_id, "user", "New question")
    manager.save_message(session_id, "assistant", "New answer")
    return manager, session_id


def test_session_manager_keeps_archival_summary_out_of_runtime_history() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        manager, session_id = _session_manager_with_summary(Path(tmp))
        runtime_history = manager.load_session_for_agent(session_id, include_compressed_context=False)
        with_summary = manager.load_session_for_agent(session_id, include_compressed_context=True)

        _assert(
            all("Archived summary" not in item["content"] for item in runtime_history),
            "runtime history should not inject compressed archival summary",
        )
        _assert(
            any("Archived summary" in item["content"] for item in with_summary),
            "archival summary should remain available when explicitly requested",
        )


def test_microcompact_reduces_bulk_outputs_without_losing_recent_turns() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        session_memory = SessionMemoryManager(Path(tmp))
        transcript = [
            Message(role="user", content="Help me analyze the inventory problem."),
            Message(role="assistant", content="I will retrieve the supporting data first."),
            Message(role="assistant", content="[RAG retrieved context]\n" + ("Source: x\nRows: 1-20\n" * 120)),
            Message(role="user", content="Continue and inspect warehouse conditions."),
            Message(
                role="assistant",
                content="Data source: inventory.xlsx\nTotal items: 200\n" + ("Top 10 rows | Beijing | 123 |\n" * 80),
            ),
            Message(role="user", content="Finally tell me the conclusion."),
            Message(role="assistant", content="Conclusion: Beijing and Shanghai are the most well-stocked warehouses."),
        ]
        session_memory.update_from_messages(transcript)
        compactor = ContextCompactor(
            session_memory,
            effective_history_token_budget=1_200,
            warning_ratio=0.3,
            microcompact_ratio=0.45,
            full_compact_ratio=0.95,
            keep_recent_messages=3,
            full_compact_recent_messages=2,
            bulky_message_token_threshold=80,
            max_messages=20,
        )

        result = compactor.maybe_compact(transcript)

        _assert(result.did_microcompact is True, "microcompact should trigger for bulky old assistant outputs")
        _assert(result.did_full_compact is False, "microcompact case should not escalate to full compact")
        _assert(result.replaced_message_count >= 1, "bulky historical outputs should be replaced")
        _assert(any("microcompacted" in item.content for item in result.messages), "microcompact should leave explicit placeholders")
        _assert(
            result.messages[-1].content == "Conclusion: Beijing and Shanghai are the most well-stocked warehouses.",
            "latest assistant conclusion should stay intact",
        )
        _assert(result.messages[-2].content == "Finally tell me the conclusion.", "latest user turn should stay intact")


def test_full_compact_uses_session_memory_as_operational_restore_layer() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        session_memory = SessionMemoryManager(Path(tmp))
        transcript = [
            Message(role="user", content="We are continuing to optimize session memory so it behaves like working memory."),
            Message(
                role="assistant",
                content="Conclusion: session memory should keep the current task state instead of becoming a transcript archive.",
            ),
            Message(role="user", content="Also add token-aware compact and microcompact."),
            Message(role="assistant", content="Design completed: warning first, then microcompact, then full compact."),
            Message(role="user", content="Do not forget safety. Important state must not be lost."),
            Message(
                role="assistant",
                content="Critical-state retention rules were added, and compact should restore from session-memory summary first.",
            ),
            Message(role="assistant", content="[RAG retrieved context]\n" + ("Source: memory\n" * 180)),
            Message(
                role="assistant",
                content="Data source: inventory.xlsx\nTotal items: 200\n" + ("Top 10 rows | Beijing | 123 |\n" * 120),
            ),
        ]
        session_memory.update_from_messages(transcript)
        compactor = ContextCompactor(
            session_memory,
            effective_history_token_budget=900,
            warning_ratio=0.3,
            microcompact_ratio=0.45,
            full_compact_ratio=0.55,
            keep_recent_messages=4,
            full_compact_recent_messages=3,
            bulky_message_token_threshold=60,
            max_messages=6,
        )

        result = compactor.maybe_compact(transcript)

        _assert(result.did_full_compact is True, "full compact should trigger under severe pressure")
        _assert(result.summary_message is not None, "full compact should synthesize a summary message")
        _assert(result.messages[0].role == "system", "full compact should prepend a system summary message")
        _assert("# Active Goal" in result.messages[0].content, "full compact summary should be driven by session-memory sections")
        _assert(
            "Current Task State" in result.messages[0].content,
            "session-memory working state should be preserved in the compact summary",
        )
        _assert(
            any("Critical-state retention rules" in item.content for item in result.messages[1:]),
            "recent safety-relevant assistant state should remain after full compact",
        )
        _assert(result.estimated_tokens_after < result.estimated_tokens_before, "full compact should reduce token usage")


def test_memory_facade_exposes_context_management_trace() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        facade = MemoryFacade(root)
        history = [
            {"role": "user", "content": "Continue optimizing the memory system."},
            {"role": "assistant", "content": "[RAG retrieved context]\n" + ("Source: durable\n" * 120)},
            {"role": "assistant", "content": "Conclusion: implement token-aware compact first, then microcompact."},
            {"role": "user", "content": "Do not forget that session memory is the working memory layer."},
        ]
        compacted_history, context_management = facade.compact_history_for_query("session-1", history)
        trace = facade.inspect_query_context(
            "session-1",
            history=history,
            pending_user_message="Continue advancing context management.",
            context_compaction=context_management,
        )

        _assert(compacted_history, "bridge should still return runtime history after compaction")
        _assert(
            trace["context_management"]["pressure_level"] in {"normal", "warning", "microcompact", "full_compact"},
            "bridge trace should expose context pressure",
        )
        _assert("estimated_tokens_before" in trace["context_management"], "bridge trace should expose token estimates")
        _assert(
            trace["session_memory"]["storage"]["primary_state_path"].endswith("process_state.json"),
            "bridge trace should expose process_state.json as the runtime authority path",
        )
        _assert(
            trace["session_memory"]["storage"]["primary_view_path"].endswith("views\\agent_view.md")
            or trace["session_memory"]["storage"]["primary_view_path"].endswith("views/agent_view.md"),
            "bridge trace should expose the primary rendered agent view path",
        )
        _assert(
            trace["session_memory"]["storage"]["primary_compaction_view_path"].endswith("views\\compaction_view.md")
            or trace["session_memory"]["storage"]["primary_compaction_view_path"].endswith("views/compaction_view.md"),
            "bridge trace should expose the primary rendered compaction view path",
        )
        _assert(
            "budget" in trace["context_management"],
            "context trace should expose budget allocation from the context controller",
        )
        _assert(
            "active_process_context" in trace["context_management"]["selected_sections"],
            "context controller should keep active-process context as a selected section",
        )
        _assert(
            "active_process_tokens" in trace["context_management"]["token_accounting"],
            "context trace should expose token accounting for active-process context",
        )


def test_session_memory_preview_does_not_persist_before_turn_commit() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        facade = MemoryFacade(root)
        session_id = "session-preview"
        committed_history = [
            {"role": "user", "content": "Keep improving the memory system."},
            {"role": "assistant", "content": "Committed state: session memory is the working layer."},
        ]
        facade.refresh_session_memory(session_id, committed_history)

        summary_path = root / "session-memory" / session_id / "summary.md"
        committed_summary = summary_path.read_text(encoding="utf-8")

        preview_block = facade.build_session_memory_block(
            session_id,
            history=committed_history,
            pending_user_message="Preview only: split durable memory away from session memory.",
        )

        persisted_summary = summary_path.read_text(encoding="utf-8")
        _assert(
            committed_summary == persisted_summary,
            "previewing session memory should not mutate the persisted summary on disk",
        )
        _assert(
            "Preview only: split durable memory away from session memory." in preview_block,
            "preview block should still reflect the pending user message",
        )
        _assert(
            "Preview only: split durable memory away from session memory." not in persisted_summary,
            "pending preview content should stay out of the committed session summary",
        )


def test_session_memory_block_renders_context_package_sections_and_warm_snapshots() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        facade = MemoryFacade(root)
        session_id = "session-package"
        committed_history = [
            {"role": "user", "content": "Help me analyze the conclusion on page 3 of report.pdf."},
            {"role": "assistant", "content": "Conclusion: page 3 mainly discusses supply-chain risk."},
            {"role": "user", "content": "Switch topics and check the gold price."},
            {"role": "assistant", "content": "Result: the current international gold spot price is about 1034 per gram."},
        ]
        facade.refresh_session_memory(session_id, committed_history)

        block = facade.build_session_memory_block(
            session_id,
            history=committed_history,
            pending_user_message="Continue the earlier document analysis.",
            retrieval_results=[
                {
                    "source": "durable_memory/project-focus.md",
                    "collection": "durable_memory",
                    "text": "The project's current main thread is still memory and RAG.",
                }
            ],
        )

        _assert("# Active Goal" in block, "context-package-based session block should preserve active process headers")
        _assert("## Hot Truth Window" in block, "session block should render context-package hot-truth section")
        _assert("## Retrieval Evidence" in block, "session block should render retrieval evidence from the context package")
        _assert("## Warm Flow Snapshots" in block, "session block should render warm flow snapshots when prior flows exist")
        _assert("report.pdf" in block, "warm flow snapshot rendering should preserve prior flow resume context")
        _assert(
            block.index("## Retrieval Evidence") < block.index("## Warm Flow Snapshots"),
            "prompt-facing session block should order retrieval evidence ahead of warm snapshots",
        )


def test_retrieval_evidence_enters_prompt_package_without_duplication_in_runtime_messages() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        facade = MemoryFacade(root)
        session_id = "session-retrieval"
        history = [
            {"role": "user", "content": "Keep focusing on the battery topic."},
        ]
        facade.refresh_session_memory(session_id, history)

        package = facade.build_context_package(
            session_id,
            history=history,
            pending_user_message="What do the retrieved docs say about batteries?",
            retrieval_results=[
                {
                    "source": "knowledge/battery.md",
                    "collection": "knowledge",
                    "text": "Battery chemistry affects energy density and charging behavior.",
                }
            ],
        )
        session_block = facade.build_session_memory_block(
            session_id,
            history=history,
            pending_user_message="What do the retrieved docs say about batteries?",
            retrieval_results=[
                {
                    "source": "knowledge/battery.md",
                    "collection": "knowledge",
                    "text": "Battery chemistry affects energy density and charging behavior.",
                }
            ],
            include_durable_context=False,
        )
        system_prompt = build_system_prompt(
            root,
            rag_mode=True,
            persistent_memory="",
            context_package=package,
        )
        runtime_messages = history + [
            {"role": "user", "content": "What do the retrieved docs say about batteries?"},
        ]

        _assert(
            "## Retrieval Evidence" in system_prompt,
            "retrieval evidence should be injected through the prompt-facing context package",
        )
        _assert(
            "Battery chemistry affects energy density" in system_prompt,
            "system prompt should include the retrieved evidence content",
        )
        _assert(
            "<!-- Context Management -->" not in system_prompt,
            "system prompt should keep context-management notes out of the model-visible prompt",
        )
        _assert(
            "Selected Sections:" not in system_prompt and "Dropped Sections:" not in system_prompt,
            "prompt should not expose section-selection metadata",
        )
        _assert(
            session_block.count("Battery chemistry affects energy density") == 1,
            "retrieval evidence should appear only once in the session-memory package",
        )
        _assert(
            all("[RAG retrieved context]" not in str(item.get("content", "")) for item in runtime_messages),
            "retrieval evidence should no longer be duplicated into runtime message history",
        )
        _assert(
            all("Battery chemistry affects energy density" not in str(item.get("content", "")) for item in runtime_messages),
            "retrieved evidence content should live in the prompt package, not a synthetic assistant history turn",
        )


def main() -> None:
    tests = [
        test_session_manager_keeps_archival_summary_out_of_runtime_history,
        test_microcompact_reduces_bulk_outputs_without_losing_recent_turns,
        test_full_compact_uses_session_memory_as_operational_restore_layer,
        test_memory_facade_exposes_context_management_trace,
        test_session_memory_preview_does_not_persist_before_turn_commit,
        test_session_memory_block_renders_context_package_sections_and_warm_snapshots,
        test_retrieval_evidence_enters_prompt_package_without_duplication_in_runtime_messages,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"ALL PASSED ({len(tests)} tests)")


if __name__ == "__main__":
    main()
