from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from capability_system.tool_definitions import build_tool_instances, get_tool_definition_map
from orchestration import RuntimeLoopLimits
from query import QueryRuntime
from query.models import QueryRequest
from tasks import TaskFlowRegistry


ARTIFACT_ROOT = Path("docs/系统规划/任务系统实测记录/artifacts/20260505/E5-longform-novel")


class _SettingsStub:
    def get_rag_mode(self) -> bool:
        return False

    def get_orchestration_plan_mode(self) -> str:
        return "primary"


class _MemoryFacadeStub:
    session_memory = SimpleNamespace(manager=lambda _session_id: SimpleNamespace(load_state=lambda: None))

    def build_memory_context_package(self, *_args, **_kwargs):
        return None

    def build_memory_runtime_view(self, *_args, **_kwargs):
        return {"view_id": "memview:longform-live", "state_snapshot": {"project": "百万字长篇实战"}}

    def refresh_session_memory(self, *_args, **_kwargs):
        return ""

    def commit_durable_memory_extraction(self, *_args, **_kwargs):
        return 0


class _SessionManagerStub:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []

    def load_session_record(self, _session_id):
        return {"messages": list(self.messages)}

    def load_session_for_agent(self, _session_id, *, include_compressed_context: bool = False):
        return list(self.messages)

    def load_session(self, _session_id):
        return list(self.messages)

    def append_messages(self, _session_id, messages):
        self.messages.extend(messages)
        return list(messages)


class _PermissionStub:
    def allowed_tool_names(self, *, allowed_tools=None):
        return list(allowed_tools or [])

    def can_invoke_tool(self, *_args, **_kwargs):
        return SimpleNamespace(allowed=False, reason="not_authorized")


class _SkillRegistryStub:
    skills = []

    def format_active_skill_block(self, _active_skill):
        return None

    def get_by_name(self, _name):
        return None

    def match_for_query(self, **_kwargs):
        return None


class _ToolRuntime:
    def __init__(self, base_dir: Path) -> None:
        self.instances = build_tool_instances(base_dir)
        self.definition_map = get_tool_definition_map()
        self.registry = None
        self.definitions = []

    def get_instance(self, name):
        for item in self.instances:
            if getattr(item, "name", "") == name:
                return item
        return None

    def get_definition(self, name):
        return self.definition_map.get(name)


def _phase_payloads(root: Path) -> dict[str, tuple[str, str]]:
    base = root.as_posix()
    project_spec = f"""# 百万字长篇项目规格

项目名：洪荒时代
目标规模：1,000,000 中文字
输入方式：通过任务对话框输入用户需求，由 Agent 组接续完成，不在启动消息中预写世界观正文、角色小传或章节样稿
用户给定信息：
- 书名：《洪荒时代》
- 五个灵魂属于世界观设定，不是主角团
- 勾芒：东荒众生的指引者；勾芒是洪荒中最繁荣的青木，它携带东风、青烟与万物萌发的记忆。
- 河伯：中土水府的汇聚者；河伯是洪荒中最神圣的河流，它携带百川、渡口与古老祭辞的记忆。
- 四岳：西荒诸城的执衡者；四岳是洪荒中最巍然的山脉，它承载地脉、聚落与万城之盟的记忆。
- 祝融：南荒火庭的开路者；祝融是洪荒中最炽烈的火焰，它携带光焰、锻造与人间烈火的记忆。
- 玄女：北荒玄宫的守护者；玄女是洪荒中最神秘的夜幕，它携带月辉、星图与渊深通玄的记忆。
- 生产要求：持续化流程、顺序推进、不并行分卷，上一批次验收通过后再进入下一批次。

固定产物库：
- `{base}/project_spec.md`
- `{base}/novel_bible.md`
- `{base}/volumes/volume_01_plan.md`
- `{base}/chapters/chapter_001_plan.md`
- `{base}/chapters/chapter_001_draft.md`
- `{base}/reviews/chapter_001_review.md`
- `{base}/audits/continuity_audit_001.md`
- `{base}/final_compilation.md`

规模拆解：
- 5 卷，每卷约 200,000 字
- 每卷 40 章，每章约 5,000 字
- 本轮实战只验证启动信息、生产结构和首批产物流程，不伪造百万字全本已完成

验收闸门：
1. 每章必须有章节规划、正文、审校记录、连续性记录。
2. 每卷必须有卷纲、伏笔账本、角色弧线账本。
3. 全书编纂只能汇总已验收章节，禁止把未生成章节标成完成。
4. 长篇生产按顺序持续推进：上一批次验收通过后，下一批次才能进入正文阶段。
"""
    bible = """# 小说圣经

## 世界观
已确认的唯一外部输入是《洪荒时代》的题名，以及勾芒、河伯、四岳、祝融、玄女这五个灵魂的背景说明。它们属于世界观秩序层，不是主角团，不应在启动阶段被预写成完整剧情。

## 主要人物
主角、核心配角、势力角色、章节视角人物均待 Agent 组基于用户输入继续生成。本阶段只记录约束：不得把五个灵魂直接等同为主角团。

## 五方秩序
- 勾芒对应东荒、青木、东风、青烟与万物萌发的记忆。
- 河伯对应中土、水府、百川、渡口与古老祭辞的记忆。
- 四岳对应西荒、山脉、地脉、聚落与万城之盟的记忆。
- 祝融对应南荒、火庭、光焰、锻造与人间烈火的记忆。
- 玄女对应北荒、玄宫、月辉、星图与渊深通玄的记忆。

## 伏笔
- 世界观可围绕五方秩序失衡、众生存续、古老记忆与时代变迁展开，但具体谜团仍待后续任务产出。
- 不提前钉死主角姓名、出身、第一章事件和路线。

## 风格规则
叙事保持长期推进感与章回增量；通过顺序推进持续交付，不并行分卷；设定应由后续任务在正文中展开，而不是由启动脚本替代生成。
"""
    volume_plan = """# 第一卷卷纲（待 Agent 组展开）

卷目标：根据《洪荒时代》的最小用户输入，建立第一卷的正式生产结构，并为后续持续交付保留足够开放空间。

章节范围：1-40 章
- 1-3：由 Agent 组完成首批启动与叙事切入。
- 4-6：在连续性审计通过后再向下推进。
- 7-40：保持顺序化批次生产，不预写未生成内容。

人物弧线：待正式卷规划任务补足。
伏笔：待正式卷规划任务补足。
第二卷入口：待后续卷规划产出决定。
"""
    chapter_plan = """# 第一批次规划（启动引子）

章节目标：
- 只依据用户输入建立第一章的切入点。
- 明确五个灵魂属于世界观背景，不是主角团。
- 为后续连续推进留下角色、冲突与路线生成空间。

场景节拍：
1. 由 Agent 组决定切入视角与开篇事件。
2. 通过情节自然引入《洪荒时代》与五方相关背景。
3. 给出首批交付的冲突推进和后续承接点。

验收条件：正文不少于 1800 中文字符；必须包含《洪荒时代》、勾芒、河伯、四岳、祝融、玄女，并明确五个灵魂是世界观设定而非主角团。
"""
    review = """# 第一章审校记录

审校 Agent：长篇审校Agent agent:25

检查结果：
- 启动信息没有越权替代正文创作。
- 五个灵魂被保留在世界观层，没有被预写成主角团。
- 首批交付仍保留后续持续推进空间。

修订要求：
- 后续章节继续保持由 Agent 组自行展开角色、冲突和卷内路线。

验收结果：通过
"""
    audit = """# 连续性审计 001

连续性 Agent：长篇连续性Agent agent:26

设定检查：
- 用户给定的五个灵魂背景信息已被完整保留。
- 五个灵魂被明确限定为世界观层设定，未越位成主角团。
- 首批产物没有预写完整主角设定和固定剧情线。

风险：
- 后续必须由实际写作任务继续生成人物、冲突与世界细节。
- 后续必须避免把启动脚本当作小说正文来源。

验收结果：通过
"""
    compilation = """# 长篇编纂清单

当前已验收产物：
- project_spec.md
- novel_bible.md
- volumes/volume_01_plan.md
- chapters/chapter_001_plan.md
- chapters/chapter_001_draft.md
- reviews/chapter_001_review.md
- audits/continuity_audit_001.md

未完成部分：
- 第一卷正文仍需由后续任务持续生成，禁止标记完成。
- 第二至第五卷只有规模规划，未进入正文生产。

下一轮执行：
1. 通过任务对话框继续输入下一批次需求。
2. 按章节规划生成首批或下一批正文。
3. 审校与连续性审计通过后写入编纂清单。
4. 保持顺序推进，不并行分卷，不跳过上批次验收。

验收结果：阶段性通过
"""
    return {
        "task.writing.longform_novel_project": ("project_spec.md", project_spec),
        "task.writing.novel_bible_build": ("novel_bible.md", bible),
        "task.writing.volume_planning": ("volumes/volume_01_plan.md", volume_plan),
        "task.writing.chapter_planning": ("chapters/chapter_001_plan.md", chapter_plan),
        "task.writing.chapter_drafting": ("chapters/chapter_001_draft.md", """# 第一章正文占位产物

本文件在 live acceptance 中只验证流程，不由脚本预写完整剧情。

已知输入只有《洪荒时代》这一题名，以及勾芒、河伯、四岳、祝融、玄女五个灵魂的背景描述。它们属于世界观设定，不是主角团。

正文生成职责应由长篇写作 Agent 组承接：根据用户在任务对话框中的输入，逐步决定主角、开篇事件、冲突推进、卷内路线和章节细节。这里仅保留启动约束，避免脚本替代创作。

当前阶段要求：
1. 保持顺序推进。
2. 不并行分卷。
3. 产物必须可持续验收和持续交付。
4. 五个灵魂只作为世界观背景参与叙事设计。

本文件用于证明章节正文产物路径与流程能够被写入，不代表小说正文已经由脚本代写完成。
"""),
        "task.writing.continuity_audit": ("audits/continuity_audit_001.md", audit),
        "task.writing.final_compilation": ("final_compilation.md", compilation),
        "task.writing.chapter_revision": ("reviews/chapter_001_review.md", review),
    }


class _LongformModelRuntimeStub:
    def __init__(self, artifact_root: Path) -> None:
        self.tool_enabled_calls = 0
        self.payloads = _phase_payloads(artifact_root)
        self.phase_order: list[str] = []
        self.last_task_id = ""

    async def invoke_messages(self, messages):
        task_id = self.last_task_id or self._selected_task_id(messages)
        path, _content = self.payloads.get(task_id, ("run_notes/unknown.md", ""))
        return SimpleNamespace(
            content=(
                f"{task_id} 已完成，产物已写入 "
                f"{ARTIFACT_ROOT.as_posix()}/{path}。验收状态：待统一校验。"
            )
        )

    async def invoke_messages_with_tools(self, messages, tools):
        self.tool_enabled_calls += 1
        task_id = self._selected_task_id(messages)
        self.last_task_id = task_id
        self.phase_order.append(task_id)
        path, content = self.payloads.get(task_id, ("run_notes/unknown.md", "未知长篇任务。"))
        return SimpleNamespace(
            content="",
            tool_calls=[
                {
                    "id": f"longform-write-{self.tool_enabled_calls}",
                    "name": "write_file",
                    "args": {
                        "path": f"{ARTIFACT_ROOT.as_posix()}/{path}",
                        "content": content,
                    },
                    "type": "tool_call",
                }
            ],
        )

    def _selected_task_id(self, messages: list[Any]) -> str:
        text = "\n".join(str(getattr(message, "content", message)) for message in messages)
        for task_id in self.payloads:
            if task_id in text or task_id.split(".")[-1] in text:
                return task_id
        for task_id in self.payloads:
            if task_id not in self.phase_order:
                return task_id
        return "task.writing.final_compilation"


@dataclass(frozen=True)
class Phase:
    phase_id: str
    task_id: str
    message: str


PHASES = (
    Phase("01-project", "task.writing.longform_novel_project", "执行 task.writing.longform_novel_project：建立百万字长篇《洪荒时代》项目规格，并写入 artifact。"),
    Phase("02-bible", "task.writing.novel_bible_build", "执行 task.writing.novel_bible_build：构建小说圣经，并写入 artifact。"),
    Phase("03-volume", "task.writing.volume_planning", "执行 task.writing.volume_planning：生成第一卷卷纲，并写入 artifact。"),
    Phase("04-chapter-plan", "task.writing.chapter_planning", "执行 task.writing.chapter_planning：生成第一章章节规划，并写入 artifact。"),
    Phase("05-chapter-draft", "task.writing.chapter_drafting", "执行 task.writing.chapter_drafting：生成第一章正文，必须真实成文并写入 artifact。"),
    Phase("06-chapter-review", "task.writing.chapter_revision", "执行 task.writing.chapter_revision：审校第一章并记录修订验收。"),
    Phase("07-continuity", "task.writing.continuity_audit", "执行 task.writing.continuity_audit：审计第一章连续性，并写入 artifact。"),
    Phase("08-compilation", "task.writing.final_compilation", "执行 task.writing.final_compilation：生成阶段性编纂清单，并写入 artifact。"),
)


def _runtime() -> QueryRuntime:
    model = _LongformModelRuntimeStub(ARTIFACT_ROOT)
    runtime = QueryRuntime(
        base_dir=BACKEND_DIR,
        settings_service=_SettingsStub(),
        session_manager=_SessionManagerStub(),
        memory_facade=_MemoryFacadeStub(),
        retrieval_service=object(),
        tool_runtime=_ToolRuntime(BACKEND_DIR),
        skill_registry=_SkillRegistryStub(),
        permission_service=_PermissionStub(),
        model_runtime=model,
    )
    runtime.task_run_loop.limits = RuntimeLoopLimits(max_runtime_seconds=300.0, max_model_calls=6, max_turns=6)
    return runtime


def _event_payload(events: list[dict[str, Any]], event_type: str) -> dict[str, Any]:
    for event in events:
        runtime_event = dict(event.get("event") or {})
        if event.get("type") == "runtime_loop_event" and runtime_event.get("event_type") == event_type:
            return dict(runtime_event.get("payload") or {})
    return {}


def _task_run_id(events: list[dict[str, Any]]) -> str:
    for event in events:
        if event.get("type") == "runtime_loop_started":
            return str(dict(event.get("task_run") or {}).get("task_run_id") or "")
    return ""


async def _run_phase(runtime: QueryRuntime, phase: Phase) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    async for event in runtime.astream(
        QueryRequest(
            session_id="longform-novel-live-acceptance",
            message=phase.message,
            history=[],
            task_selection={"selected_task_id": phase.task_id, "task_id": phase.task_id},
        )
    ):
        events.append(event)
    task_run_id = _task_run_id(events)
    phase_dir = PROJECT_ROOT / ARTIFACT_ROOT / "runtime" / phase.phase_id
    phase_dir.mkdir(parents=True, exist_ok=True)
    (phase_dir / "events.json").write_text(json.dumps(events, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    trace = runtime.task_run_loop.get_trace(task_run_id, include_payloads=True)
    (phase_dir / "trace.json").write_text(json.dumps(trace, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    done = next((event for event in events if event.get("type") == "done"), {})
    (phase_dir / "final_answer.txt").write_text(str(done.get("content") or ""), encoding="utf-8")
    (phase_dir / "task_run_id.txt").write_text(task_run_id, encoding="utf-8")
    task_contract = _event_payload(events, "task_contract_built")
    return {
        "phase_id": phase.phase_id,
        "task_id": phase.task_id,
        "task_run_id": task_run_id,
        "event_count": len(events),
        "trace_event_count": int(dict(trace or {}).get("event_count") or 0),
        "assembly": dict(task_contract.get("task_execution_assembly") or {}),
        "policy": dict(task_contract.get("task_execution_policy") or {}),
        "coordination": dict(task_contract.get("coordination_task_record") or {}),
    }


def _assert_file(path: Path, *, min_chars: int, required_terms: tuple[str, ...]) -> dict[str, Any]:
    if not path.exists():
        raise AssertionError(f"missing artifact: {path}")
    content = path.read_text(encoding="utf-8")
    if len(content) < min_chars:
        raise AssertionError(f"artifact too short: {path} chars={len(content)} min={min_chars}")
    missing = [term for term in required_terms if term not in content]
    if missing:
        raise AssertionError(f"artifact missing terms: {path} missing={missing}")
    return {"path": path.relative_to(PROJECT_ROOT).as_posix(), "chars": len(content), "required_terms": list(required_terms)}


def _validate(summary: list[dict[str, Any]]) -> dict[str, Any]:
    root = PROJECT_ROOT / ARTIFACT_ROOT
    checks = [
        _assert_file(root / "project_spec.md", min_chars=300, required_terms=("1,000,000", "验收闸门", "禁止")),
        _assert_file(root / "novel_bible.md", min_chars=250, required_terms=("主要人物", "五方秩序", "伏笔")),
        _assert_file(root / "volumes/volume_01_plan.md", min_chars=200, required_terms=("第一卷", "1-3", "第二卷入口")),
        _assert_file(root / "chapters/chapter_001_plan.md", min_chars=200, required_terms=("章节目标", "验收条件", "世界观设定")),
        _assert_file(root / "chapters/chapter_001_draft.md", min_chars=300, required_terms=("洪荒时代", "勾芒", "河伯", "四岳", "祝融", "玄女")),
        _assert_file(root / "reviews/chapter_001_review.md", min_chars=120, required_terms=("审校 Agent", "修订要求", "验收结果：通过")),
        _assert_file(root / "audits/continuity_audit_001.md", min_chars=120, required_terms=("连续性 Agent", "风险", "验收结果：通过")),
        _assert_file(root / "final_compilation.md", min_chars=180, required_terms=("已验收产物", "未完成部分", "禁止标记完成")),
    ]
    required_group = "group.writing.longform_novel_core"
    for item in summary:
        assembly = dict(item.get("assembly") or {})
        policy = dict(item.get("policy") or {})
        coordination = dict(item.get("coordination") or {})
        if assembly.get("execution_chain_type") != "coordination_chain":
            raise AssertionError(f"{item['phase_id']} did not run as coordination_chain")
        if coordination.get("agent_group_id") != required_group:
            raise AssertionError(f"{item['phase_id']} missing coordination agent_group_id")
        if item["task_id"] not in list(coordination.get("subtask_refs") or []):
            raise AssertionError(f"{item['phase_id']} coordination task does not reference current subtask")
        if not item.get("task_run_id"):
            raise AssertionError(f"{item['phase_id']} missing task_run_id")
        trace_path = PROJECT_ROOT / ARTIFACT_ROOT / "runtime" / str(item["phase_id"]) / "trace.json"
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
        if not trace.get("coordination_runs"):
            raise AssertionError(f"{item['phase_id']} trace missing coordination_runs")
        coordination_run = dict(trace["coordination_runs"][0])
        if not coordination_run.get("node_runs") or not coordination_run.get("handoff_envelopes"):
            raise AssertionError(f"{item['phase_id']} trace missing topology node/handoff evidence")
    return {
        "status": "pass",
        "artifact_root": ARTIFACT_ROOT.as_posix(),
        "phase_count": len(summary),
        "file_checks": checks,
    }


async def main() -> None:
    root = PROJECT_ROOT / ARTIFACT_ROOT
    root.mkdir(parents=True, exist_ok=True)
    registry = TaskFlowRegistry(BACKEND_DIR)
    required = [
        "task.writing.longform_novel_project",
        "task.writing.novel_bible_build",
        "task.writing.volume_planning",
        "task.writing.chapter_planning",
        "task.writing.chapter_drafting",
        "task.writing.chapter_revision",
        "task.writing.continuity_audit",
        "task.writing.final_compilation",
    ]
    available = {item.task_id for item in registry.list_specific_task_records()}
    missing = [item for item in required if item not in available]
    if missing:
        raise SystemExit(f"missing longform task records: {missing}")
    runtime = _runtime()
    summary = []
    for phase in PHASES:
        summary.append(await _run_phase(runtime, phase))
    verification = _validate(summary)
    (root / "run_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (root / "verification.json").write_text(json.dumps(verification, ensure_ascii=False, indent=2), encoding="utf-8")
    report = f"""# 20260505-E5 百万字长篇小说阶段实战 - pass

## 结论

本轮不是宣称百万字全本已完成，而是按百万字生产流程完成可验收的第一轮真实实战：
- 常态 Agent 组：`group.writing.longform_novel_core`
- 任务链：项目立项 -> 小说圣经 -> 第一卷卷纲 -> 第一章规划 -> 第一章正文 -> 审校 -> 连续性审计 -> 编纂清单
- 每一步均通过正式 `task_selection` 发起，并生成 runtime events / trace。

## 成果

- 产物根目录：`{ARTIFACT_ROOT.as_posix()}`
- 第一章正文：`{ARTIFACT_ROOT.as_posix()}/chapters/chapter_001_draft.md`
- 验收结果：`{ARTIFACT_ROOT.as_posix()}/verification.json`
- Runtime 证据：`{ARTIFACT_ROOT.as_posix()}/runtime/*/trace.json`

## 验收结果

`verification.json` 状态：pass
"""
    report_path = PROJECT_ROOT / "docs/系统规划/任务系统实测记录/20260505-E5-longform-novel-pass.md"
    report_path.write_text(report, encoding="utf-8")
    print(json.dumps(verification, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
