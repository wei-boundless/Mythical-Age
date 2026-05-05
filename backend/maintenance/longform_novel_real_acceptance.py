from __future__ import annotations

import asyncio
import json
import shutil
import sys
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


ARTIFACT_ROOT = Path("docs/系统规划/任务系统实测记录/artifacts/20260505/E5-longform-novel-real")
RECORD_PATH = Path("docs/系统规划/任务系统实测记录/20260505-E5-longform-novel-real-pass.md")
GROUP_ID = "group.writing.longform_novel_core"


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


PHASES = (
    Phase(
        "01-project",
        "task.writing.longform_novel_project",
        "project_spec.md",
        500,
        ("1000000", "5卷", "验收", "禁止"),
        "按正式长篇小说项目立项任务启动《雾港回声》百万字项目。必须调用 write_file 写入 {output_path}，内容包含项目目标、百万字拆解、5卷结构、产物目录、验收闸门、禁止伪造全本完成声明。",
    ),
    Phase(
        "02-bible",
        "task.writing.novel_bible_build",
        "novel_bible.md",
        700,
        ("世界观", "主要人物", "时间线", "伏笔", "风格规则"),
        "读取上一阶段目标，按正式小说圣经构建任务生成《雾港回声》小说圣经。必须调用 write_file 写入 {output_path}，内容包含世界观、主要人物、主线谜团、时间线、伏笔账本、风格规则。",
    ),
    Phase(
        "03-volume",
        "task.writing.volume_planning",
        "volumes/volume_01_plan.md",
        600,
        ("第一卷", "40章", "人物弧线", "伏笔", "第二卷"),
        "按正式卷规划任务生成第一卷卷纲。必须调用 write_file 写入 {output_path}，内容包含第一卷目标、40章段落拆解、人物弧线、事件链、伏笔投放回收、第二卷入口。",
    ),
    Phase(
        "04-chapter-plan",
        "task.writing.chapter_planning",
        "chapters/chapter_001_plan.md",
        500,
        ("第一章", "场景", "验收条件", "冲突", "意象"),
        "按正式章节规划任务生成第一章规划。必须调用 write_file 写入 {output_path}，内容包含章节目标、场景节拍、冲突推进、必备意象、验收条件。",
    ),
    Phase(
        "05-chapter-draft",
        "task.writing.chapter_drafting",
        "chapters/chapter_001_draft.md",
        2200,
        ("林深", "雾", "父亲", "老邱", "录音带"),
        "按正式章节正文任务生成第一章完整正文。必须调用 write_file 写入 {output_path}，正文不少于2200个中文字符，必须可直接阅读，不得只写摘要、大纲或说明。",
    ),
    Phase(
        "06-chapter-review",
        "task.writing.chapter_revision",
        "reviews/chapter_001_review.md",
        500,
        ("审校", "问题", "修订", "验收结果"),
        "按正式章节修订/审校任务审查第一章正文。必须调用 write_file 写入 {output_path}，内容包含审校结论、发现的问题、修订意见、是否通过验收。",
    ),
    Phase(
        "07-continuity",
        "task.writing.continuity_audit",
        "audits/continuity_audit_001.md",
        500,
        ("连续性", "设定", "时间线", "风险", "验收结果"),
        "按正式连续性审计任务检查第一章与小说圣经、卷纲的一致性。必须调用 write_file 写入 {output_path}，内容包含设定连续性、时间线、伏笔债务、风险和验收结果。",
    ),
    Phase(
        "08-compilation",
        "task.writing.final_compilation",
        "final_compilation.md",
        500,
        ("已验收产物", "未完成", "禁止", "下一轮"),
        "按正式全书编纂任务生成阶段性编纂清单。必须调用 write_file 写入 {output_path}，只汇总已真实完成并验收的产物，明确未完成章节，禁止标记百万字全本完成。",
    ),
)

NOVEL_CANON = {
    "title": "雾港回声",
    "protagonist": "林深",
    "father": "林深的父亲",
    "mentor": "老邱",
    "clue_object": "录音带",
    "setting": "雾港",
    "volume_target": "5卷",
    "word_target": "1000000字",
}


def _clean_run_root() -> Path:
    root = PROJECT_ROOT / ARTIFACT_ROOT
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    return root


async def _run_phase(runtime: AppRuntime, phase: Phase) -> dict[str, Any]:
    assert runtime.query_runtime is not None
    output_path = ARTIFACT_ROOT / phase.output_path
    message = phase.message.format(output_path=output_path.as_posix())
    message += _phase_acceptance_constraints(phase)
    message += (
        "\n\n硬性要求：必须使用 write_file 工具写入目标文件。"
        "最终回答只允许报告写入路径、任务阶段、验收状态和下一步，不得替代文件产物。"
    )
    events: list[dict[str, Any]] = []
    async for event in runtime.query_runtime.astream(
        QueryRequest(
            session_id="longform-novel-real-acceptance",
            message=message,
            history=[],
            task_selection={
                "selected_task_id": phase.task_id,
                "task_id": phase.task_id,
                "agent_group_id": GROUP_ID,
            },
        )
    ):
        events.append(event)

    task_run_id = _task_run_id(events)
    phase_dir = PROJECT_ROOT / ARTIFACT_ROOT / "runtime" / phase.phase_id
    phase_dir.mkdir(parents=True, exist_ok=True)
    (phase_dir / "events.json").write_text(json.dumps(events, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (phase_dir / "task_run_id.txt").write_text(task_run_id, encoding="utf-8")
    done = next((item for item in events if item.get("type") == "done"), {})
    (phase_dir / "final_answer.txt").write_text(str(done.get("content") or ""), encoding="utf-8")
    trace = runtime.query_runtime.task_run_loop.get_trace(task_run_id, include_payloads=True) if task_run_id else None
    (phase_dir / "trace.json").write_text(json.dumps(trace, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return {
        "phase_id": phase.phase_id,
        "task_id": phase.task_id,
        "output_path": output_path.as_posix(),
        "task_run_id": task_run_id,
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
        path = PROJECT_ROOT / ARTIFACT_ROOT / phase.output_path
        if not path.exists():
            raise AssertionError(f"{phase.phase_id} missing artifact: {path}")
        content = path.read_text(encoding="utf-8")
        normalized = content.replace(",", "")
        if len(content) < phase.min_chars:
            raise AssertionError(f"{phase.phase_id} artifact too short: {len(content)} < {phase.min_chars}")
        missing = [
            term
            for term in phase.required_terms
            if not _contains_required_term(content, normalized=normalized, term=term)
        ]
        if missing:
            raise AssertionError(f"{phase.phase_id} missing terms: {missing}")
        if int(item.get("tool_write_count") or 0) < 1:
            raise AssertionError(f"{phase.phase_id} did not use write_file successfully")
        trace = dict(item.get("trace") or {})
        effective_loop_limits = _effective_loop_limits(trace)
        if effective_loop_limits.get("max_runtime_seconds", "missing") is not None:
            raise AssertionError(f"{phase.phase_id} is not using unlimited task runtime limits")
        if not trace.get("coordination_runs"):
            raise AssertionError(f"{phase.phase_id} trace missing CoordinationRun")
        coordination_run = dict(trace["coordination_runs"][0])
        if coordination_run.get("status") != "completed":
            raise AssertionError(f"{phase.phase_id} coordination run not completed")
        if not coordination_run.get("node_runs"):
            raise AssertionError(f"{phase.phase_id} trace missing CoordinationNodeRun")
        if not coordination_run.get("handoff_envelopes"):
            raise AssertionError(f"{phase.phase_id} trace missing AgentHandoffEnvelope")
        if not coordination_run.get("latest_merge_result"):
            raise AssertionError(f"{phase.phase_id} trace missing CoordinationMergeResult")
        checks.append(
            {
                "phase_id": phase.phase_id,
                "artifact": path.relative_to(PROJECT_ROOT).as_posix(),
                "chars": len(content),
                "tool_write_count": item.get("tool_write_count"),
                "task_run_id": item.get("task_run_id"),
                "effective_loop_limits": effective_loop_limits,
            }
        )
    return {
        "status": "pass",
        "prebaked_payload": False,
        "agent_group_id": GROUP_ID,
        "artifact_root": ARTIFACT_ROOT.as_posix(),
        "phase_count": len(summary),
        "checks": checks,
    }


def _contains_required_term(content: str, *, normalized: str, term: str) -> bool:
    variants = REQUIRED_TERM_ALIASES.get(term, (term,))
    return any(variant in content or variant in normalized for variant in variants)


def _phase_acceptance_constraints(phase: Phase) -> str:
    required_terms = "、".join(phase.required_terms)
    canon_lines = [
        f"长篇项目固定设定：标题《{NOVEL_CANON['title']}》，主角={NOVEL_CANON['protagonist']}，关键亲属={NOVEL_CANON['father']}，关键协作者={NOVEL_CANON['mentor']}，关键线索物={NOVEL_CANON['clue_object']}。",
        f"固定规模：{NOVEL_CANON['word_target']}，{NOVEL_CANON['volume_target']}，场景基底={NOVEL_CANON['setting']}。",
        f"本阶段文件必须显式包含这些验收关键词：{required_terms}。",
    ]
    if phase.phase_id == "05-chapter-draft":
        canon_lines.append(
            "章节正文必须让林深、父亲、老邱、录音带全部在可直接阅读的情节中出现，禁止改名、替换同义角色或只在说明段提及。"
        )
    if phase.phase_id in {"06-chapter-review", "07-continuity", "08-compilation"}:
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


async def main() -> None:
    ensure_project_storage(BACKEND_DIR)
    root = _clean_run_root()
    runtime = AppRuntime()
    runtime.initialize(BACKEND_DIR)
    assert runtime.query_runtime is not None

    summary: list[dict[str, Any]] = []
    try:
        for phase in PHASES:
            summary.append(await _run_phase(runtime, phase))
        verification = _validate(summary)
        status = "pass"
    except Exception as exc:
        verification = {
            "status": "fail",
            "prebaked_payload": False,
            "error": str(exc),
            "artifact_root": ARTIFACT_ROOT.as_posix(),
            "completed_phase_count": len(summary),
        }
        status = "fail"

    (root / "run_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (root / "verification.json").write_text(json.dumps(verification, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    record_name = f"20260505-E5-longform-novel-real-{status}.md"
    record_path = PROJECT_ROOT / "docs/系统规划/任务系统实测记录" / record_name
    record_path.write_text(_render_record(verification, status=status), encoding="utf-8")
    print(json.dumps(verification, ensure_ascii=False, indent=2, default=str))
    if status != "pass":
        raise SystemExit(1)


def _render_record(verification: dict[str, Any], *, status: str) -> str:
    title_status = "通过" if status == "pass" else "失败"
    return f"""# 20260505 E5 百万字长篇小说真实实战记录

状态：{title_status}

## 前置条件

- Agent 组：`{GROUP_ID}`
- 正式任务链：项目立项 -> 小说圣经 -> 第一卷卷纲 -> 第一章规划 -> 第一章正文 -> 审校 -> 连续性审计 -> 编纂清单
- 产物目录：`{ARTIFACT_ROOT.as_posix()}`
- 真实性规则：`prebaked_payload=false`，必须由正式 runtime 调用模型和 `write_file` 工具产生产物。

## 验收结果

```json
{json.dumps(verification, ensure_ascii=False, indent=2, default=str)}
```

## 结论

{title_status}。
"""


if __name__ == "__main__":
    asyncio.run(main())
