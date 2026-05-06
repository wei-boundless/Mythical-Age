from __future__ import annotations

import asyncio
import json
import shutil
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from bootstrap.app_runtime import AppRuntime
from orchestration import AgentGroupRegistry
from project_layout import ensure_project_storage
from query.models import QueryRequest


ARTIFACT_ROOT = Path("docs/系统规划/任务系统实测记录/artifacts/20260506/E5-longform-novel-langgraph-real")
RECORD_PATH = Path("docs/系统规划/任务系统实测记录/20260506-E5-longform-novel-langgraph-real-pass.md")
GROUP_ID = "group.writing.longform_novel_core"
CHAPTER_BATCH_START = 1
CHAPTER_BATCH_END = 5
CHAPTER_BATCH_SIZE = 5
CHAPTER_BATCH_TARGET_CHARS = 10000
CHAPTER_BATCH_MIN_CHARS = 9000
CHAPTER_BATCH_RANGE_LABEL = f"{CHAPTER_BATCH_START:03d}_{CHAPTER_BATCH_END:03d}"
CHAPTER_BATCH_PATH_LABEL = f"第{CHAPTER_BATCH_START:03d}章到第{CHAPTER_BATCH_END:03d}章"
CHAPTER_BATCH_INLINE_LABEL = f"{CHAPTER_BATCH_START}-{CHAPTER_BATCH_END}章"
CHAPTER_BATCH_FILE_LABEL = f"第{CHAPTER_BATCH_START:03d}章-第{CHAPTER_BATCH_END:03d}章"


REQUIRED_TERM_ALIASES: dict[str, tuple[str, ...]] = {
    "1000000": ("1000000", "1,000,000", "100万", "一百万", "百万字"),
    "5卷": ("5卷", "5 卷", "五卷", "5 个卷", "五个卷"),
}


@dataclass(frozen=True)
class Phase:
    phase_id: str
    task_id: str
    output_path: str
    min_chars: int
    required_terms: tuple[str, ...]
    message: str


class PhaseValidationError(AssertionError):
    def __init__(self, phase_id: str, message: str) -> None:
        super().__init__(message)
        self.phase_id = phase_id
        self.detail = message


PHASES = (
    Phase(
        "01-project",
        "task.writing.longform_novel_project",
        "project_spec.md",
        500,
        ("1000000", "5卷", "验收", "禁止"),
        "把自己当作用户通过对话框启动正式长篇小说项目：只使用用户给定信息启动《洪荒时代》百万字项目，不要预写主角、完整世界观或章节正文。必须调用 write_file 写入 {output_path}，内容包含项目目标、百万字拆解、5卷结构、持续化产物目录、验收闸门、禁止伪造全本完成声明。",
    ),
    Phase(
        "02-bible",
        "task.writing.novel_bible_build",
        "novel_bible.md",
        700,
        ("世界观", "主要人物", "五方秩序", "伏笔", "风格规则"),
        "读取上一阶段目标，按正式长篇小说设定总纲构建任务生成《洪荒时代》设定总纲。必须调用 write_file 写入 {output_path}，内容包含世界观、主要人物待生成策略、五方秩序、主线谜团待生成策略、时间线、伏笔账本、风格规则，并明确勾芒、河伯、四岳、祝融、玄女是世界观秩序层设定，不是主角团。不要编入固定主角姓名或固定第一章事件。",
    ),
    Phase(
        "03-volume",
        "task.writing.volume_planning",
        "volumes/volume_01_plan.md",
        900,
        ("第一卷", "40章", "1-5章", "6-10章", "人物弧线", "伏笔", "第二卷"),
        "按正式卷规划任务生成第一卷卷纲。必须调用 write_file 写入 {output_path}，内容包含第一卷目标、40章段落拆解，并明确按1-5章、6-10章等顺序小批次持续推进，包含人物弧线、事件链、伏笔投放回收、第二卷入口。允许 Agent 组生成必要内容，但不得声称这些内容来自启动脚本预设。",
    ),
    Phase(
        "04-batch-plan",
        "task.writing.chapter_planning",
        f"batches/batch_{CHAPTER_BATCH_RANGE_LABEL}_plan.md",
        700,
        ("第001章", "第005章", "5章", "批次目标", "章节节拍", "冲突推进", "验收条件"),
        f"按正式章节规划任务生成{CHAPTER_BATCH_PATH_LABEL}的批次规划。必须调用 write_file 写入 {{output_path}}，内容需要覆盖5章，逐章给出章节目标、场景节拍、冲突推进、关键意象与验收条件。",
    ),
    Phase(
        "05-batch-draft",
        "task.writing.chapter_drafting",
        f"batches/batch_{CHAPTER_BATCH_RANGE_LABEL}_draft.md",
        CHAPTER_BATCH_MIN_CHARS,
        ("第001章", "第005章", "勾芒", "河伯", "四岳", "祝融", "玄女", "五方秩序"),
        f"按正式章节正文任务生成{CHAPTER_BATCH_PATH_LABEL}的短批次正文。必须调用 write_file 写入 {{output_path}}，正文必须按5个章节展开、可直接阅读，总字数不少于{CHAPTER_BATCH_MIN_CHARS}个中文字符，目标约{CHAPTER_BATCH_TARGET_CHARS}字，不得只写摘要、大纲或说明。每章都必须形成完整场景，建议每章平均约2000个中文字符，避免极短章节凑数。",
    ),
    Phase(
        "06-batch-review",
        "task.writing.chapter_revision",
        f"reviews/batch_{CHAPTER_BATCH_RANGE_LABEL}_review.md",
        700,
        ("抽审", "优先问题", "修订建议", "通过范围", "剩余风险", "验收结果"),
        f"按正式章节修订/审校任务对{CHAPTER_BATCH_PATH_LABEL}做批量抽审。必须调用 write_file 写入 {{output_path}}，内容只要求覆盖抽审范围、优先问题、修订建议、通过范围、剩余风险和验收结果，不要求逐章细审；如需修订，最多只允许两轮。",
    ),
    Phase(
        "07-batch-continuity",
        "task.writing.continuity_audit",
        f"audits/batch_{CHAPTER_BATCH_RANGE_LABEL}_continuity.md",
        700,
        ("连续性", "设定总纲", "时间线", "批次风险", "快审结论", "验收结果"),
        f"按正式连续性审计任务对{CHAPTER_BATCH_PATH_LABEL}做连续性快审。必须调用 write_file 写入 {{output_path}}，内容包含设定总纲一致性、时间线、伏笔债务、批次风险、快审结论和验收结果，不要求逐章穷尽审计；审校只做关键阻断项，不做循环返工。",
    ),
    Phase(
        "08-compilation",
        "task.writing.final_compilation",
        "final_compilation.md",
        500,
        ("已验收产物", CHAPTER_BATCH_FILE_LABEL, "未完成", "禁止", "下一轮"),
        f"按正式全书编纂任务生成阶段性编纂清单。必须调用 write_file 写入 {{output_path}}，只汇总已真实完成并验收的产物，明确{CHAPTER_BATCH_PATH_LABEL}已完成的批次成果与仍未完成章节，禁止标记百万字全本完成。",
    ),
)

NOVEL_CANON = {
    "title": "洪荒时代",
    "world_souls": "勾芒、河伯、四岳、祝融、玄女",
    "core_order": "五方秩序",
    "volume_target": "5卷",
    "word_target": "1000000字",
    "soul_seed": (
        "勾芒：东荒众生的指引者；勾芒是洪荒中最繁荣的青木，它携带东风、青烟与万物萌发的记忆。\n"
        "河伯：中土水府的汇聚者；河伯是洪荒中最神圣的河流，它携带百川、渡口与古老祭辞的记忆。\n"
        "四岳：西荒诸城的执衡者；四岳是洪荒中最巍然的山脉，它承载地脉、聚落与万城之盟的记忆。\n"
        "祝融：南荒火庭的开路者；祝融是洪荒中最炽烈的火焰，它携带光焰、锻造与人间烈火的记忆。\n"
        "玄女：北荒玄宫的守护者；玄女是洪荒中最神秘的夜幕，它携带月辉、星图与渊深通玄的记忆。"
    ),
}


def _run_token() -> str:
    return f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"


def _session_id_for_phase(*, run_token: str, phase: Phase, attempt: int) -> str:
    compact_token = run_token.replace("-", "")
    phase_key = phase.phase_id.replace("-", "_")
    return f"lnlg_{compact_token}_{phase_key}_a{attempt}"[:80]


def _clean_run_root() -> Path:
    root = PROJECT_ROOT / ARTIFACT_ROOT
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _prepare_run_root(*, resume_existing: bool = False) -> Path:
    if resume_existing:
        root = PROJECT_ROOT / ARTIFACT_ROOT
        root.mkdir(parents=True, exist_ok=True)
        return root
    return _clean_run_root()


async def _run_phase(
    runtime: AppRuntime,
    phase: Phase,
    *,
    run_token: str,
    attempt: int = 1,
    repair_hint: str = "",
) -> dict[str, Any]:
    assert runtime.query_runtime is not None
    output_path = ARTIFACT_ROOT / phase.output_path
    message = (
        f"这是写作域的真实执行任务，不是文档阅读、文件解读、PDF分析，也不是资料总结。"
        f"你必须作为写作任务执行器，完成指定写作产物并写入目标文件 {output_path.as_posix()}。\n\n"
    )
    message += phase.message.format(output_path=output_path.as_posix())
    message += _phase_acceptance_constraints(phase)
    message += (
        "\n\n硬性要求：必须使用 write_file 工具写入目标文件。"
        "最终回答只允许报告写入路径、任务阶段、验收状态和下一步，不得替代文件产物。"
    )
    if attempt > 1:
        message += (
            f"\n\n当前是第{attempt}次修复复测。上一轮未通过，"
            "必须直接覆盖写入同一目标文件，不能只补说明，不能只补结论，不能把未达标内容继续当作通过。"
        )
    if repair_hint:
        message += f"\n\n复测修复指令：\n{repair_hint}"
    session_id = _session_id_for_phase(run_token=run_token, phase=phase, attempt=attempt)
    events: list[dict[str, Any]] = []
    async for event in runtime.query_runtime.astream(
        QueryRequest(
            session_id=session_id,
            message=message,
            history=[],
            task_selection={
                "selected_task_id": phase.task_id,
                "task_id": phase.task_id,
                "agent_group_id": GROUP_ID,
                "runtime_limits": {
                    "limit_mode": "unlimited",
                    "max_turns": 24,
                    "max_model_calls": 24,
                    "max_runtime_seconds": None,
                    "max_events": 1200,
                },
            },
        )
    ):
        events.append(event)

    task_run_id = _task_run_id(events)
    phase_dir = PROJECT_ROOT / ARTIFACT_ROOT / "runtime" / phase.phase_id
    phase_dir.mkdir(parents=True, exist_ok=True)
    attempt_suffix = "" if attempt == 1 else f".attempt_{attempt}"
    (phase_dir / f"events{attempt_suffix}.json").write_text(json.dumps(events, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (phase_dir / f"task_run_id{attempt_suffix}.txt").write_text(task_run_id, encoding="utf-8")
    done = next((item for item in events if item.get("type") == "done"), {})
    (phase_dir / f"final_answer{attempt_suffix}.txt").write_text(str(done.get("content") or ""), encoding="utf-8")
    trace = runtime.query_runtime.task_run_loop.get_trace(task_run_id, include_payloads=True) if task_run_id else None
    (phase_dir / f"trace{attempt_suffix}.json").write_text(json.dumps(trace, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    if attempt == 1:
        (phase_dir / "events.json").write_text(json.dumps(events, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        (phase_dir / "task_run_id.txt").write_text(task_run_id, encoding="utf-8")
        (phase_dir / "final_answer.txt").write_text(str(done.get("content") or ""), encoding="utf-8")
        (phase_dir / "trace.json").write_text(json.dumps(trace, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    else:
        (phase_dir / "events.json").write_text(json.dumps(events, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        (phase_dir / "task_run_id.txt").write_text(task_run_id, encoding="utf-8")
        (phase_dir / "final_answer.txt").write_text(str(done.get("content") or ""), encoding="utf-8")
        (phase_dir / "trace.json").write_text(json.dumps(trace, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return {
        "phase_id": phase.phase_id,
        "task_id": phase.task_id,
        "output_path": output_path.as_posix(),
        "task_run_id": task_run_id,
        "session_id": session_id,
        "attempt": attempt,
        "event_count": len(events),
        "trace_event_count": int(dict(trace or {}).get("event_count") or 0),
        "tool_write_count": _tool_write_count(events),
        "trace": trace or {},
    }


def _task_run_id(events: list[dict[str, Any]]) -> str:
    for event in events:
        if event.get("type") == "runtime_loop_started":
            return str(dict(event.get("task_run") or {}).get("task_run_id") or "")
    return ""


def _tool_write_count(events: list[dict[str, Any]]) -> int:
    count = 0
    for event in events:
        if event.get("type") != "runtime_loop_event":
            continue
        runtime_event = dict(event.get("event") or {})
        if runtime_event.get("event_type") != "tool_result_received":
            continue
        observation = dict(dict(runtime_event.get("payload") or {}).get("observation") or {})
        payload = dict(observation.get("payload") or {})
        if payload.get("tool_name") == "write_file" and "Write succeeded:" in str(payload.get("result") or ""):
            count += 1
    return count


def _validate(summary: list[dict[str, Any]]) -> dict[str, Any]:
    group = AgentGroupRegistry(BACKEND_DIR).get_group(GROUP_ID)
    if group is None:
        raise AssertionError(f"missing agent group: {GROUP_ID}")
    if set(group.member_agent_ids) != {"agent:20", "agent:21", "agent:22", "agent:23", "agent:24", "agent:25", "agent:26"}:
        raise AssertionError("longform agent group members are not complete")

    checks: list[dict[str, Any]] = []
    for phase, item in zip(PHASES, summary):
        checks.append(_validate_phase(phase, item))
    return {
        "status": "pass",
        "prebaked_payload": False,
        "agent_group_id": GROUP_ID,
        "artifact_root": ARTIFACT_ROOT.as_posix(),
        "phase_count": len(summary),
        "checks": checks,
    }


def _validate_phase(phase: Phase, item: dict[str, Any]) -> dict[str, Any]:
    path = PROJECT_ROOT / ARTIFACT_ROOT / phase.output_path
    if not path.exists():
        raise PhaseValidationError(phase.phase_id, f"{phase.phase_id} missing artifact: {path}")
    content = path.read_text(encoding="utf-8")
    normalized = content.replace(",", "")
    if len(content) < phase.min_chars:
        raise PhaseValidationError(phase.phase_id, f"{phase.phase_id} artifact too short: {len(content)} < {phase.min_chars}")
    missing = [
        term
        for term in phase.required_terms
        if not _contains_required_term(content, normalized=normalized, term=term)
    ]
    if missing:
        raise PhaseValidationError(phase.phase_id, f"{phase.phase_id} missing terms: {missing}")
    if phase.phase_id in {"04-batch-plan", "05-batch-draft"}:
        missing_chapter_labels = _missing_batch_chapter_labels(content)
        if missing_chapter_labels:
            raise PhaseValidationError(phase.phase_id, f"{phase.phase_id} missing chapter labels: {missing_chapter_labels}")
    if int(item.get("tool_write_count") or 0) < 1:
        raise PhaseValidationError(phase.phase_id, f"{phase.phase_id} did not use write_file successfully")
    trace = dict(item.get("trace") or {})
    task_run = dict(trace.get("task_run") or {})
    if task_run.get("status") != "completed":
        raise PhaseValidationError(phase.phase_id, f"{phase.phase_id} task run not completed: {task_run.get('status') or 'missing'}")
    effective_loop_limits = _effective_loop_limits(trace)
    if effective_loop_limits.get("max_runtime_seconds", "missing") is not None:
        raise PhaseValidationError(phase.phase_id, f"{phase.phase_id} is not using unlimited task runtime limits")
    if not trace.get("coordination_runs"):
        raise PhaseValidationError(phase.phase_id, f"{phase.phase_id} trace missing CoordinationRun")
    coordination_run = dict(trace["coordination_runs"][0])
    if coordination_run.get("status") != "completed":
        raise PhaseValidationError(phase.phase_id, f"{phase.phase_id} coordination run not completed")
    coordination_diagnostics = dict(coordination_run.get("diagnostics") or {})
    if coordination_diagnostics.get("coordination_engine") != "langgraph":
        raise PhaseValidationError(phase.phase_id, f"{phase.phase_id} coordination engine is not LangGraph")
    langgraph_diagnostics = dict(coordination_diagnostics.get("langgraph_diagnostics") or {})
    if langgraph_diagnostics.get("compiled") is not True:
        raise PhaseValidationError(phase.phase_id, f"{phase.phase_id} LangGraph graph did not compile")
    graph_spec = dict(coordination_diagnostics.get("coordination_graph_spec") or {})
    if not graph_spec.get("valid", False):
        raise PhaseValidationError(phase.phase_id, f"{phase.phase_id} coordination graph spec is invalid")
    if not coordination_run.get("node_runs"):
        raise PhaseValidationError(phase.phase_id, f"{phase.phase_id} trace missing CoordinationNodeRun")
    if not all(dict(dict(node).get("diagnostics") or {}).get("coordination_engine") == "langgraph" for node in coordination_run.get("node_runs") or []):
        raise PhaseValidationError(phase.phase_id, f"{phase.phase_id} node runs are not all produced by LangGraph")
    if not coordination_run.get("handoff_envelopes"):
        raise PhaseValidationError(phase.phase_id, f"{phase.phase_id} trace missing AgentHandoffEnvelope")
    if not all(dict(dict(handoff).get("diagnostics") or {}).get("coordination_engine") == "langgraph" for handoff in coordination_run.get("handoff_envelopes") or []):
        raise PhaseValidationError(phase.phase_id, f"{phase.phase_id} handoff envelopes are not all produced by LangGraph")
    if not coordination_run.get("latest_merge_result"):
        raise PhaseValidationError(phase.phase_id, f"{phase.phase_id} trace missing CoordinationMergeResult")
    return {
        "phase_id": phase.phase_id,
        "artifact": path.relative_to(PROJECT_ROOT).as_posix(),
        "chars": len(content),
        "tool_write_count": item.get("tool_write_count"),
        "task_run_id": item.get("task_run_id"),
        "attempt": int(item.get("attempt") or 1),
        "effective_loop_limits": effective_loop_limits,
        "coordination_engine": coordination_diagnostics.get("coordination_engine"),
        "langgraph_diagnostics": langgraph_diagnostics,
        "coordination_node_count": len(coordination_run.get("node_runs") or []),
        "handoff_count": len(coordination_run.get("handoff_envelopes") or []),
    }


def _contains_required_term(content: str, *, normalized: str, term: str) -> bool:
    variants = REQUIRED_TERM_ALIASES.get(term, (term,))
    return any(variant in content or variant in normalized for variant in variants)


def _missing_batch_chapter_labels(content: str) -> list[str]:
    missing: list[str] = []
    for index in range(CHAPTER_BATCH_START, CHAPTER_BATCH_END + 1):
        padded = f"第{index:03d}章"
        plain = f"第{index}章"
        if padded not in content and plain not in content:
            missing.append(padded)
    return missing


def _phase_acceptance_constraints(phase: Phase) -> str:
    required_terms = "、".join(phase.required_terms)
    canon_lines = [
        f"长篇项目固定输入：标题《{NOVEL_CANON['title']}》。主角、首卷起点、第一章事件都由 Agent 组后续生成，启动消息不得预写。",
        f"用户给定的世界观背景：\n{NOVEL_CANON['soul_seed']}",
        f"世界观层设定：{NOVEL_CANON['world_souls']}属于{NOVEL_CANON['core_order']}背景，不是主角团，也不替主角解决剧情。",
        f"固定规模：{NOVEL_CANON['word_target']}，{NOVEL_CANON['volume_target']}；生产方式为顺序持续推进，上一批次验收通过后再进入下一批次。",
        f"本阶段文件必须显式包含这些验收关键词：{required_terms}。",
    ]
    if phase.phase_id == "05-batch-draft":
        canon_lines.append(
            f"正文批次必须显式覆盖{CHAPTER_BATCH_PATH_LABEL}，并让五个灵魂背景以世界观方式进入可直接阅读的情节，禁止把五魂写成主角团或只在说明段提及。"
        )
        canon_lines.append(
        f"持续策略：单次正文目标约{CHAPTER_BATCH_TARGET_CHARS}字、{CHAPTER_BATCH_SIZE}章；后续批次按验收顺序继续推进，不并行分卷，不跳过连续性审计。"
    )
    if phase.phase_id == "04-batch-plan":
        canon_lines.append(f"批次规划必须逐章列出{CHAPTER_BATCH_PATH_LABEL}，不允许只给一个总摘要。")
    if phase.phase_id in {"06-batch-review", "07-batch-continuity", "08-compilation"}:
        canon_lines.append(
            "审查或汇总时必须沿用同一套固定设定，不得切换为其他角色名或新的线索物。"
        )
    return "\n\n验收约束：\n- " + "\n- ".join(canon_lines)


def _effective_loop_limits(trace: dict[str, Any]) -> dict[str, Any]:
    task_run = dict(trace.get("task_run") or {})
    diagnostics = dict(task_run.get("diagnostics") or {})
    effective = diagnostics.get("effective_loop_limits")
    if isinstance(effective, dict):
        return dict(effective)
    for event in trace.get("events") or ():
        event_payload = dict(dict(event).get("payload") or {})
        event_diagnostics = dict(event_payload.get("diagnostics") or {})
        effective = event_diagnostics.get("effective_loop_limits")
        if isinstance(effective, dict):
            return dict(effective)
    return {}


def _phase_max_attempts(phase: Phase) -> int:
    if phase.phase_id == "05-batch-draft":
        return 2
    return 1


def _build_repair_hint(phase: Phase, detail: str) -> str:
    base = [f"上一轮失败原因：{detail}。"]
    if phase.phase_id == "05-batch-draft":
        base.extend(
            [
                f"你必须重写完整的{CHAPTER_BATCH_PATH_LABEL}正文文件，不允许只补几章，也不允许只追加说明。",
                "每一章都必须是可直接阅读的连续小说场景，避免极短章节；建议每章至少1800个中文字符。",
                f"写入完成前请自查目标文件正文总长度，必须不少于{phase.min_chars}个中文字符，目标约{CHAPTER_BATCH_TARGET_CHARS}字。",
                "最终回答不得口头宣称通过，只有当实际文件长度达标时才可报告通过。",
            ]
        )
    elif phase.phase_id == "04-batch-plan":
        base.extend(
            [
                f"必须逐章列出{CHAPTER_BATCH_PATH_LABEL}，不能只给总纲。",
                "每章都要有章节目标、场景节拍、冲突推进、关键意象与验收条件。",
            ]
        )
    else:
        base.append("请直接修复未达标产物并覆盖目标文件，禁止只输出说明。")
    return "\n".join(f"- {line}" for line in base)


async def _run_phase_with_retries(runtime: AppRuntime, phase: Phase, *, run_token: str) -> dict[str, Any]:
    last_error: Exception | None = None
    repair_hint = ""
    for attempt in range(1, _phase_max_attempts(phase) + 1):
        phase_summary = await _run_phase(runtime, phase, run_token=run_token, attempt=attempt, repair_hint=repair_hint)
        try:
            _validate_phase(phase, phase_summary)
            return phase_summary
        except PhaseValidationError as exc:
            last_error = exc
            repair_hint = _build_repair_hint(phase, exc.detail)
            continue
    assert last_error is not None
    raise last_error


def _load_existing_phase_summary(runtime: AppRuntime, phase: Phase) -> dict[str, Any] | None:
    phase_dir = PROJECT_ROOT / ARTIFACT_ROOT / "runtime" / phase.phase_id
    events_path = phase_dir / "events.json"
    task_run_path = phase_dir / "task_run_id.txt"
    trace_path = phase_dir / "trace.json"
    if not events_path.exists() or not task_run_path.exists() or not trace_path.exists():
        return None
    try:
        events = json.loads(events_path.read_text(encoding="utf-8"))
        task_run_id = task_run_path.read_text(encoding="utf-8").strip()
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(events, list) or not isinstance(trace, dict):
        return None
    return {
        "phase_id": phase.phase_id,
        "task_id": phase.task_id,
        "output_path": (ARTIFACT_ROOT / phase.output_path).as_posix(),
        "task_run_id": task_run_id,
        "session_id": str(dict(trace.get("task_run") or {}).get("session_id") or ""),
        "attempt": int(_latest_existing_attempt(phase_dir)),
        "event_count": len(events),
        "trace_event_count": int(dict(trace or {}).get("event_count") or 0),
        "tool_write_count": _tool_write_count(events),
        "trace": trace,
        "resumed_from_existing_artifact": True,
    }


def _latest_existing_attempt(phase_dir: Path) -> int:
    attempts = [1]
    for path in phase_dir.glob("events.attempt_*.json"):
        try:
            attempts.append(int(path.stem.rsplit("_", 1)[-1]))
        except ValueError:
            continue
    return max(attempts)


async def main() -> None:
    ensure_project_storage(BACKEND_DIR)
    resume_existing = "--resume-existing" in sys.argv
    root = _prepare_run_root(resume_existing=resume_existing)
    run_token = _run_token()
    runtime = AppRuntime()
    runtime.initialize(BACKEND_DIR)
    assert runtime.query_runtime is not None

    summary: list[dict[str, Any]] = []
    try:
        for phase in PHASES:
            if resume_existing:
                existing = _load_existing_phase_summary(runtime, phase)
                if existing is not None:
                    try:
                        _validate_phase(phase, existing)
                        summary.append(existing)
                        continue
                    except PhaseValidationError:
                        pass
            phase_summary = await _run_phase_with_retries(runtime, phase, run_token=run_token)
            summary.append(phase_summary)
        verification = _validate(summary)
        status = "pass"
    except Exception as exc:
        verification = {
            "status": "fail",
            "prebaked_payload": False,
            "error": str(exc),
            "artifact_root": ARTIFACT_ROOT.as_posix(),
            "completed_phase_count": len(summary),
            "run_token": run_token,
        }
        status = "fail"

    (root / "run_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (root / "verification.json").write_text(json.dumps(verification, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    record_name = f"20260506-E5-longform-novel-langgraph-real-{status}.md"
    record_path = PROJECT_ROOT / "docs/系统规划/任务系统实测记录" / record_name
    record_path.write_text(_render_record(verification, status=status), encoding="utf-8")
    print(json.dumps(verification, ensure_ascii=False, indent=2, default=str))
    if status != "pass":
        raise SystemExit(1)


def _render_record(verification: dict[str, Any], *, status: str) -> str:
    title_status = "通过" if status == "pass" else "失败"
    return f"""# 20260506 E5 百万字长篇小说 LangGraph 真实实战记录

状态：{title_status}

## 前置条件

- Agent 组：`{GROUP_ID}`
- 正式任务链：项目立项 -> 设定总纲 -> 第一卷卷纲 -> {CHAPTER_BATCH_INLINE_LABEL}顺序批次规划 -> {CHAPTER_BATCH_INLINE_LABEL}顺序批次正文 -> 抽审 -> 连续性快审 -> 编纂清单
- 产物目录：`{ARTIFACT_ROOT.as_posix()}`
- 生产粒度：每批 `{CHAPTER_BATCH_SIZE}` 章，正文目标约 `{CHAPTER_BATCH_TARGET_CHARS}` 字；后续长篇推进采用顺序小批次持续交付，而不是并行分卷或单次 20 章长输出。
- 真实性规则：`prebaked_payload=false`，必须由正式 runtime 调用模型和 `write_file` 工具产生产物。
- 协调任务规则：每一阶段必须进入 LangGraph 协调 runner，并在 trace 中留下 `CoordinationRun / CoordinationNodeRun / AgentHandoffEnvelope / CoordinationMergeResult`。

## 验收结果

```json
{json.dumps(verification, ensure_ascii=False, indent=2, default=str)}
```

## 结论

{title_status}。
"""


if __name__ == "__main__":
    asyncio.run(main())
