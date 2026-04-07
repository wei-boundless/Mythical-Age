from __future__ import annotations

import asyncio
import json
import shutil
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from config import runtime_config
from graph.agent import AgentManager
from structured_memory import ContextCompactor


@dataclass(slots=True)
class TurnResult:
    user_message: str
    answer: str
    context_management: dict[str, Any] | None = None
    memory_context: dict[str, Any] | None = None
    durable_saved_count: int = 0
    tool_events: list[dict[str, Any]] = field(default_factory=list)
    raw_events: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ExperimentResult:
    name: str
    passed: bool
    summary: str
    details: dict[str, Any] = field(default_factory=dict)


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _copy_workspace(temp_backend: Path) -> None:
    source_workspace = BACKEND_DIR / "workspace"
    if source_workspace.exists():
        shutil.copytree(source_workspace, temp_backend / "workspace", dirs_exist_ok=True)


def _prepare_temp_backend() -> Path:
    temp_backend = Path(tempfile.mkdtemp(prefix="memory-exp-"))
    (temp_backend / "durable_memory").mkdir(parents=True, exist_ok=True)
    (temp_backend / "session-memory").mkdir(parents=True, exist_ok=True)
    (temp_backend / "sessions").mkdir(parents=True, exist_ok=True)
    (temp_backend / "skills").mkdir(parents=True, exist_ok=True)
    (temp_backend / "durable_memory" / "MEMORY.md").write_text("# Memory Index\n\n", encoding="utf-8")
    _copy_workspace(temp_backend)
    return temp_backend


async def _run_turn(
    manager: AgentManager,
    session_id: str,
    user_message: str,
) -> TurnResult:
    session_manager = manager.session_manager
    if session_manager is None:
        raise RuntimeError("session manager not initialized")

    history = session_manager.load_session_for_agent(session_id, include_compressed_context=False)
    final_answer = ""
    context_management: dict[str, Any] | None = None
    memory_context: dict[str, Any] | None = None
    tool_events: list[dict[str, Any]] = []
    raw_events: list[str] = []

    async for event in manager.astream(session_id, user_message, history):
        raw_events.append(str(event.get("type", "")))
        event_type = event.get("type")
        if event_type == "context_management":
            context_management = dict(event.get("context", {}) or {})
        elif event_type == "memory_context":
            memory_context = dict(event.get("memory", {}) or {})
        elif event_type in {"tool_start", "tool_end"}:
            tool_events.append(dict(event))
        elif event_type == "done":
            final_answer = str(event.get("content", "") or "")

    session_manager.save_message(session_id, "user", user_message)
    session_manager.save_message(session_id, "assistant", final_answer)
    manager.refresh_session_memory(session_id)
    durable_saved_count = manager.extract_durable_memories(session_id)

    return TurnResult(
        user_message=user_message,
        answer=final_answer,
        context_management=context_management,
        memory_context=memory_context,
        durable_saved_count=durable_saved_count,
        tool_events=tool_events,
        raw_events=raw_events,
    )


def _new_session(manager: AgentManager, title: str) -> str:
    session_manager = manager.session_manager
    if session_manager is None:
        raise RuntimeError("session manager not initialized")
    record = session_manager.create_session(title)
    return str(record["id"])


async def experiment_context_pressure(manager: AgentManager) -> ExperimentResult:
    session_id = _new_session(manager, "context-pressure")
    session_manager = manager.session_manager
    if session_manager is None:
        raise RuntimeError("session manager not initialized")

    bulky_retrieval = "[RAG retrieved context]\n" + ("Source: durable_memory\nRows: 1-20 / 200\n" * 140)
    bulky_table = "数据源：inventory.xlsx\n总商品数：200\n" + ("前 10 项：北京仓 | 123 |\n" * 120)
    scripted_history = [
        ("user", "We are continuing to optimize session memory so it behaves like working memory."),
        ("assistant", "Conclusion: session memory should keep current task state instead of becoming a long transcript archive."),
        ("assistant", bulky_retrieval),
        ("assistant", "Recent decision: we need token-aware compact and microcompact."),
        ("assistant", bulky_table),
        ("user", "Do not forget the safety requirement: important state must not be lost."),
        ("assistant", "We added critical-state retention rules and compact should restore from session-memory summary first."),
    ]
    for role, content in scripted_history:
        session_manager.save_message(session_id, role, content)
    manager.refresh_session_memory(session_id)
    if manager.memory_bridge is not None:
        manager.memory_bridge._compactor = lambda sid: ContextCompactor(  # noqa: SLF001
            manager.memory_bridge._session_memory(sid),  # noqa: SLF001
            effective_history_token_budget=2_000,
            warning_ratio=0.45,
            microcompact_ratio=0.55,
            full_compact_ratio=0.7,
            bulky_message_token_threshold=120,
            max_messages=10,
        )

    turn = await _run_turn(
        manager,
        session_id,
        "What are we currently optimizing? Answer in one sentence.",
    )

    context = turn.context_management or {}
    answer = turn.answer
    _assert(context.get("pressure_level") in {"microcompact", "full_compact"}, "heavy history should trigger microcompact or full compact")
    _assert((turn.memory_context or {}).get("session_memory", {}).get("present") is True, "session memory should be present during pressured turn")
    _assert(
        any(keyword in answer.lower() for keyword in ("session memory", "working memory", "context", "memory", "compact", "token")),
        "agent should still answer the active optimization topic after compaction",
    )

    return ExperimentResult(
        name="context_pressure_and_restore",
        passed=True,
        summary="高压上下文下触发压缩，且 agent 仍能依赖 session-memory 回答当前任务。",
        details={
            "turn": asdict(turn),
        },
    )


async def experiment_durable_writeback_and_exact_recall(manager: AgentManager) -> ExperimentResult:
    session_id = _new_session(manager, "durable-memory")

    turns: list[TurnResult] = []
    prompts = [
        "Remember that from now on we always prefer PowerShell for terminal commands.",
        "No need to expand yet. Continue.",
        "Remember that I prefer you to give the conclusion first and then explain.",
        "Continue and keep those conventions in memory.",
    ]
    for prompt in prompts:
        turns.append(await _run_turn(manager, session_id, prompt))

    durable_root = manager.base_dir / "durable_memory" if manager.base_dir is not None else None
    note_files = sorted(path.name for path in durable_root.glob("*.md")) if durable_root is not None else []
    index_text = (durable_root / "MEMORY.md").read_text(encoding="utf-8") if durable_root is not None else ""
    note_text = ""
    if durable_root is not None:
        note_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(durable_root.glob("*.md"))
            if path.name.lower() != "memory.md"
        )
    combined_memory_text = f"{index_text}\n{note_text}".lower()

    recall_terminal = await _run_turn(
        manager,
        session_id,
        "What terminal syntax should we use by default from now on? Answer with only the terminal type.",
    )
    recall_style = await _run_turn(
        manager,
        session_id,
        "When you answer a complex question later, how should you structure the answer first?",
    )

    terminal_answer = recall_terminal.answer.lower()
    style_answer = recall_style.answer
    _assert(any(turn.durable_saved_count > 0 for turn in turns), "durable extraction should eventually save notes after scheduler gate")
    _assert("powershell" in combined_memory_text, "durable memory content should retain the PowerShell convention")
    _assert(
        any(token in combined_memory_text for token in ("conclusion first", "then explain", "give the conclusion first")),
        "durable memory content should retain the conclusion-first preference",
    )
    _assert("powershell" in terminal_answer, "exact durable recall should answer with PowerShell")
    _assert(
        any(token in style_answer.lower() for token in ("conclusion", "first"))
        or any(token in style_answer for token in ("先给出结论", "先讲结论", "结论")),
        "preference durable recall should surface the answer-style preference",
    )
    _assert(
        (recall_terminal.memory_context or {}).get("durable_memory", {}).get("exact_matches"),
        "terminal recall turn should expose durable exact matches",
    )

    return ExperimentResult(
        name="durable_writeback_and_exact_recall",
        passed=True,
        summary="durable memory 在调度门控后成功写入，并能通过 exact recall 返回工作约定和偏好。",
        details={
            "initial_turns": [asdict(turn) for turn in turns],
            "note_files": note_files,
            "recall_terminal": asdict(recall_terminal),
            "recall_style": asdict(recall_style),
        },
    )


async def experiment_durable_relevant_surfacing(manager: AgentManager) -> ExperimentResult:
    session_id = _new_session(manager, "durable-relevant")
    session_manager = manager.session_manager
    if session_manager is None:
        raise RuntimeError("session manager not initialized")

    # Seed a few messages so the writeback scheduler can be exercised again in this session.
    seed_prompts = [
        "Remember that our current project focus is optimizing Memory and RAG.",
        "Continue and keep that direction.",
        "Remember that multimodal data should be parsed, cleaned, and chunked before ingest.",
        "Okay, continue.",
    ]
    for prompt in seed_prompts:
        await _run_turn(manager, session_id, prompt)

    turn = await _run_turn(
        manager,
        session_id,
        "When we continue this project, what main track should we prioritize right now?",
    )

    memory_trace = turn.memory_context or {}
    relevant_notes = memory_trace.get("durable_memory", {}).get("relevant_notes", [])
    answer = turn.answer.lower()
    _assert(relevant_notes, "semantic project question should surface relevant durable notes")
    _assert(any(keyword in answer for keyword in ("memory", "rag")), "answer should reflect the surfaced project focus memory")

    return ExperimentResult(
        name="durable_relevant_surfacing",
        passed=True,
        summary="语义相近但非原句的项目主线问题，能够依赖 relevant durable memories 浮现出来。",
        details={
            "turn": asdict(turn),
        },
    )


async def run_all() -> dict[str, Any]:
    previous_rag_mode = runtime_config.get_rag_mode()
    runtime_config.set_rag_mode(False)
    temp_backend = _prepare_temp_backend()
    manager = AgentManager()
    try:
        manager.initialize(temp_backend)
        manager.tools = []
        results: list[ExperimentResult] = []
        for runner in (
            experiment_context_pressure,
            experiment_durable_writeback_and_exact_recall,
            experiment_durable_relevant_surfacing,
        ):
            results.append(await runner(manager))
        return {
            "ok": True,
            "temp_backend": str(temp_backend),
            "results": [asdict(item) for item in results],
        }
    finally:
        runtime_config.set_rag_mode(previous_rag_mode)


def main() -> None:
    payload = asyncio.run(run_all())
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
