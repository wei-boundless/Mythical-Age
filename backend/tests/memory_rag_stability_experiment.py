from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from config import get_settings, runtime_config
from memory import MemoryFacade
from query.prompt_builder import build_system_prompt
from RAG.router import RAGQueryRouter
from runtime import AppRuntime
from structured_memory import ContextCompactor, Message, SessionMemoryManager


@dataclass(slots=True)
class AgentTurnProbe:
    user_message: str
    answer: str
    retrieval_results: list[dict[str, Any]] = field(default_factory=list)
    context_management: dict[str, Any] | None = None
    memory_context: dict[str, Any] | None = None
    durable_saved_count: int = 0
    raw_events: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ScenarioRunResult:
    name: str
    category: str
    mode: str
    iteration: int
    passed: bool
    summary: str
    details: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass(slots=True)
class ScenarioAggregate:
    name: str
    category: str
    mode: str
    repeats: int
    pass_count: int
    pass_rate: float
    stability: str
    runs: list[ScenarioRunResult] = field(default_factory=list)


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _prepare_temp_backend_layout(*, copy_workspace: bool = True) -> Path:
    temp_root = Path(tempfile.mkdtemp(prefix="memory-rag-stability-"))
    backend = temp_root / "backend"
    for relative in (
        "durable_memory",
        "session-memory",
        "sessions",
        "skills",
        "knowledge",
        "storage",
        "workspace",
        "context_profile/constitution",
        "context_profile/profile",
    ):
        (backend / relative).mkdir(parents=True, exist_ok=True)
    _write(backend / "durable_memory" / "MEMORY.md", "# Memory Index\n\n")
    _write(backend / "SKILLS_SNAPSHOT.md", "# Skills Snapshot\n\n- stability-test\n")
    _write(backend / "context_profile" / "constitution" / "SOUL.md", "# Soul\n\nCalm and direct.")
    _write(backend / "context_profile" / "constitution" / "IDENTITY.md", "# Identity\n\nLocal-first agent.")
    _write(backend / "context_profile" / "profile" / "USER.md", "# User\n\nPrefer concise grounded answers.")
    _write(backend / "context_profile" / "profile" / "AGENTS.md", "# Agents\n\nPrefer transparent execution.")
    if copy_workspace:
        source_workspace = BACKEND_DIR / "workspace"
        if source_workspace.exists():
            shutil.copytree(source_workspace, backend / "workspace", dirs_exist_ok=True)
    return backend


def _disable_embeddings_on_router(router: RAGQueryRouter) -> None:
    for indexer in router.registry.indexers.values():
        indexer._supports_embeddings = lambda: False  # type: ignore[method-assign]


def _seed_rag_corpus(base_dir: Path) -> None:
    _write(
        base_dir / "knowledge" / "battery.md",
        "# Battery Notes\n\nBattery chemistry affects energy density and charging behavior.\n"
        "Lithium iron phosphate cells trade some energy density for safety.\n",
    )
    _write(
        base_dir / "knowledge" / "warehouse.md",
        "# Warehouse Notes\n\nWarehouse temperature policy affects battery storage quality.\n"
        "Emergency shutdown belongs to the warehouse safety SOP.\n",
    )
    _write(
        base_dir / "knowledge" / "finance.md",
        "# Finance Notes\n\nGold prices are tracked separately from warehouse operations.\n",
    )


def _seed_durable_note(base_dir: Path) -> None:
    _write(
        base_dir / "durable_memory" / "powershell-rule.md",
        "---\n"
        "schema_version: durable-memory.v2\n"
        "title: Prefer PowerShell Commands\n"
        "memory_type: workflow\n"
        "memory_class: work\n"
        "confidence: high\n"
        "created_by: test-suite\n"
        "tags:\n"
        "  - powershell\n"
        "  - workflow\n"
        "retrieval_hints:\n"
        "  - PowerShell\n"
        "  - terminal commands\n"
        "---\n\n"
        "## Canonical Memory\n"
        "Prefer PowerShell for terminal commands in this project.\n",
    )
    _write(
        base_dir / "durable_memory" / "MEMORY.md",
        "# Memory Index\n\n"
        "- [Prefer PowerShell Commands](powershell-rule.md) - Prefer PowerShell for terminal commands in this project.\n",
    )


def _new_session(manager: AppRuntime, title: str) -> str:
    session_manager = manager.session_manager
    if session_manager is None:
        raise RuntimeError("session manager not initialized")
    record = session_manager.create_session(title)
    return str(record["id"])


def _disable_tools(manager: AppRuntime) -> None:
    tool_runtime = manager.tool_runtime
    if tool_runtime is None:
        raise RuntimeError("tool runtime not initialized")
    tool_runtime._instances = []  # noqa: SLF001
    tool_runtime._by_name = {}  # noqa: SLF001


def _override_compactor(
    facade: MemoryFacade,
    *,
    session_id: str,
    effective_history_token_budget: int,
    warning_ratio: float,
    microcompact_ratio: float,
    full_compact_ratio: float,
    keep_recent_messages: int,
    full_compact_recent_messages: int,
    bulky_message_token_threshold: int,
    max_messages: int,
):
    original_compact = facade.compact_history_for_query

    def forced_compact(target_session_id: str, history: list[dict[str, Any]]):
        if target_session_id != session_id:
            return original_compact(target_session_id, history)
        py_history = facade.adapter.to_messages(history, session_id=target_session_id)
        controller = facade.session_memory.context_controller(target_session_id)
        controller.compactor = ContextCompactor(
            facade.session_memory.manager(target_session_id),
            effective_history_token_budget=effective_history_token_budget,
            warning_ratio=warning_ratio,
            microcompact_ratio=microcompact_ratio,
            full_compact_ratio=full_compact_ratio,
            keep_recent_messages=keep_recent_messages,
            full_compact_recent_messages=full_compact_recent_messages,
            bulky_message_token_threshold=bulky_message_token_threshold,
            max_messages=max_messages,
        )
        result = controller.compact_history(py_history)
        compacted = [
            {"role": message.role, "content": message.content}
            for message in result.messages
        ]
        return compacted, facade.context_memory._compact_trace(result)  # noqa: SLF001

    facade.compact_history_for_query = forced_compact  # type: ignore[method-assign]
    return original_compact


async def _run_agent_turn(
    manager: AppRuntime,
    session_id: str,
    user_message: str,
) -> AgentTurnProbe:
    session_manager = manager.session_manager
    query_runtime = manager.query_runtime
    if session_manager is None or query_runtime is None:
        raise RuntimeError("runtime not initialized")

    history = session_manager.load_session_for_agent(session_id, include_compressed_context=False)
    final_answer = ""
    retrieval_results: list[dict[str, Any]] = []
    context_management: dict[str, Any] | None = None
    memory_context: dict[str, Any] | None = None
    raw_events: list[str] = []

    async for event in query_runtime._execution_events(session_id, user_message, history):
        event_type = str(event.get("type", "") or "")
        raw_events.append(event_type)
        if event_type == "retrieval":
            retrieval_results = list(event.get("results", []) or [])
        elif event_type == "context_management":
            context_management = dict(event.get("context", {}) or {})
        elif event_type == "memory_context":
            memory_context = dict(event.get("memory", {}) or {})
        elif event_type == "done":
            final_answer = str(event.get("content", "") or "")

    session_manager.save_message(session_id, "user", user_message)
    session_manager.save_message(session_id, "assistant", final_answer)
    query_runtime.refresh_session_memory(session_id)
    durable_saved_count = query_runtime.commit_durable_memory_extraction(session_id)

    return AgentTurnProbe(
        user_message=user_message,
        answer=final_answer,
        retrieval_results=retrieval_results,
        context_management=context_management,
        memory_context=memory_context,
        durable_saved_count=durable_saved_count,
        raw_events=raw_events,
    )


def _scenario_summary(name: str) -> str:
    summaries = {
        "deterministic_memory_switch_and_resume": "memory task switching preserves warm snapshots and allows resuming prior work",
        "deterministic_memory_correction_recovery": "correction flow clears stale state and preserves corrected facts",
        "deterministic_memory_compaction_restore": "compaction preserves active task state under heavy history pressure",
        "deterministic_rag_keyword_precision": "keyword-only retrieval stays stable under noisy knowledge documents",
        "deterministic_rag_memory_routing": "memory-oriented retrieval routes to durable memory without leaking session memory",
        "deterministic_prompt_package_dedup": "retrieval evidence enters the prompt package without runtime-message duplication",
        "live_memory_writeback_and_recall": "real model can write durable conventions and recall them consistently",
        "live_rag_grounded_answer": "real model can answer from retrieved evidence with stable grounding",
    }
    return summaries.get(name, name)


def _stability_label(mode: str, pass_count: int, repeats: int) -> str:
    if pass_count == repeats:
        return "stable"
    if mode == "live" and repeats >= 3 and pass_count >= repeats - 1:
        return "mostly_stable"
    return "unstable"


def _is_acceptable_stability(mode: str, stability: str) -> bool:
    if mode == "live":
        return stability in {"stable", "mostly_stable"}
    return stability == "stable"


def deterministic_memory_switch_and_resume(iteration: int) -> dict[str, Any]:
    root = _prepare_temp_backend_layout(copy_workspace=False)
    facade = MemoryFacade(root)
    session_id = f"memory-switch-{iteration}"

    first_phase = [
        {"role": "user", "content": "Help me analyze the conclusion on page 3 of report.pdf."},
        {"role": "assistant", "content": "Conclusion: page 3 mainly discusses supply-chain risk."},
    ]
    second_phase = first_phase + [
        {"role": "user", "content": "Switch topics and check the gold price."},
        {"role": "assistant", "content": "Result: the current international gold spot price is about 1034 per gram."},
    ]
    facade.refresh_session_memory(session_id, first_phase)
    facade.refresh_session_memory(session_id, second_phase)
    snapshots = facade.session_memory.manager(session_id).load_flow_snapshots()
    block = facade.build_session_memory_block(
        session_id,
        history=second_phase,
        pending_user_message="Continue the earlier document analysis.",
    )

    _assert(snapshots, "warm flow snapshots should exist after an explicit task switch")
    _assert(any("report.pdf" in snapshot.goal for snapshot in snapshots), "prior PDF task should be resumable from warm snapshots")
    _assert("## Warm Flow Snapshots" in block, "prompt-facing block should render warm snapshots")
    _assert("report.pdf" in block, "resumed context should reference the earlier PDF task")
    return {
        "session_block": block,
        "snapshots": [snapshot.to_dict() for snapshot in snapshots],
    }


def deterministic_memory_correction_recovery(iteration: int) -> dict[str, Any]:
    root = _prepare_temp_backend_layout(copy_workspace=False)
    manager = SessionMemoryManager(root / "session-memory" / f"repair-{iteration}")
    manager.update_from_messages(
        [
            Message(role="user", content="Please analyze the conclusion on page 3 of report.pdf."),
            Message(role="assistant", content="Conclusion: page 3 says market share keeps rising."),
            Message(role="user", content="That is wrong."),
            Message(role="assistant", content="Correction: after checking again, page 3 is about cost pressure and margin compression."),
        ]
    )

    state = manager.load_state()
    summary = manager.load()
    _assert("report.pdf" in state.active_goal, "correction should preserve the underlying PDF task")
    _assert(state.context_slots.active_pdf == "report.pdf", "corrected state should rebuild the PDF slot")
    _assert(any("cost pressure" in item.lower() for item in state.key_results), "corrected fact should survive into key results")
    _assert(
        all("market share keeps rising" not in item.lower() for item in state.key_results),
        "contradicted fact should stay blocked after correction",
    )
    _assert("cost pressure" in summary.lower(), "summary view should expose the corrected result")
    return {
        "active_goal": state.active_goal,
        "key_results": list(state.key_results),
        "summary": summary,
    }


def deterministic_memory_compaction_restore(iteration: int) -> dict[str, Any]:
    root = _prepare_temp_backend_layout(copy_workspace=False)
    facade = MemoryFacade(root)
    session_id = f"compaction-{iteration}"
    history = [
        {"role": "user", "content": "We are optimizing session memory as working memory."},
        {"role": "assistant", "content": "Conclusion: session memory should preserve current task state."},
        {"role": "assistant", "content": "[RAG retrieved context]\n" + ("Source: memory\nRows: 1-20\n" * 180)},
        {"role": "assistant", "content": "Data source: inventory.xlsx\n" + ("Top 10 rows | Beijing | 123 |\n" * 120)},
        {"role": "user", "content": "Do not lose the safety rule."},
        {"role": "assistant", "content": "Critical-state retention rules were added."},
    ]
    original_compact = _override_compactor(
        facade,
        session_id=session_id,
        effective_history_token_budget=1_100,
        warning_ratio=0.3,
        microcompact_ratio=0.45,
        full_compact_ratio=0.6,
        keep_recent_messages=4,
        full_compact_recent_messages=3,
        bulky_message_token_threshold=80,
        max_messages=8,
    )
    try:
        compacted, trace = facade.compact_history_for_query(session_id, history)
    finally:
        facade.compact_history_for_query = original_compact  # type: ignore[method-assign]
    _assert(trace["pressure_level"] in {"microcompact", "full_compact"}, "heavy history should trigger compact pressure")
    _assert(compacted, "compaction should still return runtime history")
    _assert(
        any("Critical-state retention rules" in item["content"] for item in compacted),
        "recent safety state should survive compaction",
    )
    return {
        "trace": trace,
        "compacted_history": compacted,
    }


def deterministic_rag_keyword_precision(iteration: int) -> dict[str, Any]:
    base_dir = _prepare_temp_backend_layout(copy_workspace=False)
    _seed_rag_corpus(base_dir)
    router = RAGQueryRouter(base_dir)
    _disable_embeddings_on_router(router)
    query = "According to the docs, what affects energy density and charging behavior?"
    plan = router.plan(query)
    top_sources: list[str] = []
    runs: list[list[dict[str, Any]]] = []
    for _ in range(3):
        results = router.retrieve(query, top_k=3)
        payload = [dict(item) for item in results]
        runs.append(payload)
        _assert(payload, "RAG retrieval should return at least one grounded hit")
        top_sources.append(str(payload[0]["source"]))
        _assert("knowledge/battery.md" in payload[0]["source"], "battery knowledge should rank first for the battery query")
    _assert(len(set(top_sources)) == 1, "top-1 retrieval source should stay stable across repeated runs")
    _assert(plan.selected_collections == ["knowledge"], "plain knowledge question should stay on the knowledge collection")
    return {
        "plan": asdict(plan),
        "top_sources": top_sources,
        "runs": runs,
    }


def deterministic_rag_memory_routing(iteration: int) -> dict[str, Any]:
    base_dir = _prepare_temp_backend_layout(copy_workspace=False)
    _seed_rag_corpus(base_dir)
    _seed_durable_note(base_dir)
    _write(
        base_dir / "session-memory" / "session-x" / "summary.md",
        "# Active Goal\n\nSession-only misleading text about fish shells.\n",
    )
    router = RAGQueryRouter(base_dir)
    _disable_embeddings_on_router(router)
    query = "From memory, what workflow should we use for terminal commands in this project?"
    plan = router.plan(query)
    results = router.retrieve(query, top_k=4)
    sources = [str(item["source"]) for item in results]
    _assert("durable_memory" in plan.selected_collections, "memory-oriented query should route to durable memory")
    _assert("session_memory" not in plan.selected_collections, "session memory should remain excluded from chat retrieval")
    _assert(any(source.startswith("durable_memory/") for source in sources), "durable memory should surface in routed results")
    _assert(all(not source.startswith("session-memory/") for source in sources), "session-memory views must not leak into retrieval results")
    return {
        "plan": asdict(plan),
        "results": results,
    }


def deterministic_prompt_package_dedup(iteration: int) -> dict[str, Any]:
    root = _prepare_temp_backend_layout(copy_workspace=False)
    facade = MemoryFacade(root)
    session_id = f"prompt-dedup-{iteration}"
    history = [{"role": "user", "content": "Keep focusing on the battery topic."}]
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
    prompt = build_system_prompt(
        root,
        rag_mode=True,
        persistent_memory="",
        context_package=package,
    )
    runtime_messages = history + [{"role": "user", "content": "What do the retrieved docs say about batteries?"}]
    _assert("## Retrieval Evidence" in prompt, "retrieval evidence should render into the prompt package")
    _assert(prompt.count("Battery chemistry affects energy density") == 1, "retrieval evidence should appear only once in the prompt")
    _assert(
        all("Battery chemistry affects energy density" not in item["content"] for item in runtime_messages),
        "retrieval evidence must stay out of runtime conversation history",
    )
    return {
        "prompt": prompt,
        "package": package.to_dict(),
    }


async def live_memory_writeback_and_recall(iteration: int) -> dict[str, Any]:
    base_dir = _prepare_temp_backend_layout(copy_workspace=True)
    manager = AppRuntime()
    manager.initialize(base_dir)
    _disable_tools(manager)
    session_id = _new_session(manager, f"live-memory-{iteration}")

    prompts = [
        "Remember that from now on we always prefer PowerShell for terminal commands.",
        "No need to expand yet. Continue.",
        "Remember that I prefer you to give the conclusion first and then explain.",
        "Continue and keep those conventions in memory.",
    ]
    turns = [await _run_agent_turn(manager, session_id, prompt) for prompt in prompts]
    recall_terminal = await _run_agent_turn(
        manager,
        session_id,
        "What terminal syntax should we use by default from now on? Answer with only the terminal type.",
    )
    recall_style = await _run_agent_turn(
        manager,
        session_id,
        "When you answer a complex question later, how should you structure the answer first?",
    )

    durable_root = base_dir / "durable_memory"
    note_files = sorted(path.name for path in durable_root.glob("*.md"))
    note_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(durable_root.glob("*.md"))
        if path.name.lower() != "memory.md"
    ).lower()
    terminal_answer = recall_terminal.answer.lower()
    style_answer = recall_style.answer.lower()

    _assert(any(turn.durable_saved_count > 0 for turn in turns), "durable memory should eventually be written after the scheduler gate")
    _assert("powershell" in note_text, "PowerShell convention should land in durable memory content")
    _assert(
        any(token in note_text for token in ("conclusion first", "then explain", "give the conclusion first")),
        "answer-style preference should land in durable memory content",
    )
    _assert("powershell" in terminal_answer, "terminal recall should answer with PowerShell")
    _assert(
        any(token in style_answer for token in ("conclusion", "first")) or "then explain" in style_answer,
        "style recall should preserve the conclusion-first convention",
    )
    _assert(
        (recall_terminal.memory_context or {}).get("durable_memory", {}).get("exact_matches"),
        "terminal recall turn should expose durable exact matches",
    )

    return {
        "base_dir": str(base_dir),
        "note_files": note_files,
        "turns": [asdict(turn) for turn in turns],
        "recall_terminal": asdict(recall_terminal),
        "recall_style": asdict(recall_style),
    }


async def live_rag_grounded_answer(iteration: int) -> dict[str, Any]:
    base_dir = _prepare_temp_backend_layout(copy_workspace=False)
    _seed_rag_corpus(base_dir)
    manager = AppRuntime()
    manager.initialize(base_dir)
    _disable_tools(manager)
    if manager.retrieval_service is not None:
        _disable_embeddings_on_router(manager.retrieval_service.router)
    session_id = _new_session(manager, f"live-rag-{iteration}")
    previous_rag_mode = runtime_config.get_rag_mode()
    runtime_config.set_rag_mode(True)
    try:
        turn_a = await _run_agent_turn(
            manager,
            session_id,
            "According to the docs, what affects energy density and charging behavior?",
        )
        turn_b = await _run_agent_turn(
            manager,
            session_id,
            "Keep it brief: what affects charging behavior in the docs?",
        )
    finally:
        runtime_config.set_rag_mode(previous_rag_mode)

    answer_a = turn_a.answer.lower()
    answer_b = turn_b.answer.lower()
    top_sources_a = [str(item.get("source", "")) for item in turn_a.retrieval_results]
    top_sources_b = [str(item.get("source", "")) for item in turn_b.retrieval_results]

    _assert(turn_a.retrieval_results, "live RAG turn should emit retrieval results")
    _assert(any("knowledge/battery.md" in source for source in top_sources_a), "battery doc should appear in the first retrieval set")
    _assert(any("knowledge/battery.md" in source for source in top_sources_b), "battery doc should appear in the follow-up retrieval set")
    _assert("battery" in answer_a and "chemistry" in answer_a, "first grounded answer should mention battery chemistry")
    _assert("battery" in answer_b, "follow-up grounded answer should stay on the battery topic")

    return {
        "base_dir": str(base_dir),
        "turn_a": asdict(turn_a),
        "turn_b": asdict(turn_b),
    }


def _scenario_matrix(include_live: bool) -> list[tuple[str, str, str, Callable[[int], Any]]]:
    scenarios: list[tuple[str, str, str, Callable[[int], Any]]] = [
        ("deterministic_memory_switch_and_resume", "memory", "deterministic", deterministic_memory_switch_and_resume),
        ("deterministic_memory_correction_recovery", "memory", "deterministic", deterministic_memory_correction_recovery),
        ("deterministic_memory_compaction_restore", "memory", "deterministic", deterministic_memory_compaction_restore),
        ("deterministic_rag_keyword_precision", "rag", "deterministic", deterministic_rag_keyword_precision),
        ("deterministic_rag_memory_routing", "rag", "deterministic", deterministic_rag_memory_routing),
        ("deterministic_prompt_package_dedup", "memory_rag", "deterministic", deterministic_prompt_package_dedup),
    ]
    if include_live:
        scenarios.extend(
            [
                ("live_memory_writeback_and_recall", "memory", "live", live_memory_writeback_and_recall),
                ("live_rag_grounded_answer", "rag", "live", live_rag_grounded_answer),
            ]
        )
    return scenarios


async def _run_one(
    name: str,
    category: str,
    mode: str,
    iteration: int,
    runner: Callable[[int], Any],
) -> ScenarioRunResult:
    try:
        payload = runner(iteration)
        if asyncio.iscoroutine(payload):
            payload = await payload
        return ScenarioRunResult(
            name=name,
            category=category,
            mode=mode,
            iteration=iteration,
            passed=True,
            summary=_scenario_summary(name),
            details=dict(payload or {}),
        )
    except Exception as exc:
        return ScenarioRunResult(
            name=name,
            category=category,
            mode=mode,
            iteration=iteration,
            passed=False,
            summary=f"{name} failed",
            details={},
            error=str(exc),
        )


async def run_suite(
    *,
    deterministic_repeats: int = 4,
    live_repeats: int = 3,
    include_live: bool = True,
) -> dict[str, Any]:
    settings = get_settings()
    live_allowed = include_live and bool(settings.llm_api_key)
    aggregates: list[ScenarioAggregate] = []
    for name, category, mode, runner in _scenario_matrix(live_allowed):
        repeats = deterministic_repeats if mode == "deterministic" else live_repeats
        runs: list[ScenarioRunResult] = []
        for iteration in range(1, repeats + 1):
            runs.append(await _run_one(name, category, mode, iteration, runner))
        pass_count = sum(1 for item in runs if item.passed)
        aggregates.append(
            ScenarioAggregate(
                name=name,
                category=category,
                mode=mode,
                repeats=repeats,
                pass_count=pass_count,
                pass_rate=round(pass_count / repeats, 3) if repeats else 0.0,
                stability=_stability_label(mode, pass_count, repeats),
                runs=runs,
            )
        )

    overall_ok = all(_is_acceptable_stability(item.mode, item.stability) for item in aggregates)
    return {
        "ok": overall_ok,
        "deterministic_repeats": deterministic_repeats,
        "live_repeats": live_repeats if live_allowed else 0,
        "live_enabled": live_allowed,
        "llm_provider": settings.llm_provider,
        "embedding_provider": settings.embedding_provider,
        "vector_backend": settings.vector_store_backend,
        "aggregates": [
            {
                **asdict(item),
                "acceptable": _is_acceptable_stability(item.mode, item.stability),
                "runs": [asdict(run) for run in item.runs],
            }
            for item in aggregates
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Deep stability experiments for memory and RAG.")
    parser.add_argument("--deterministic-repeats", type=int, default=4)
    parser.add_argument("--live-repeats", type=int, default=3)
    parser.add_argument("--skip-live", action="store_true")
    parser.add_argument("--output", type=str, default="")
    args = parser.parse_args()

    payload = asyncio.run(
        run_suite(
            deterministic_repeats=max(1, args.deterministic_repeats),
            live_repeats=max(1, args.live_repeats),
            include_live=not args.skip_live,
        )
    )
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    print(rendered)
    if not payload["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
