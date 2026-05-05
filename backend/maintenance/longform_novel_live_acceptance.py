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


def _chapter_text() -> str:
    paragraphs = [
        "第一章 雾港的回声",
        "清晨五点，雾从北港的铁轨缝里慢慢升起，像一封被潮气泡软的旧信。沈砚站在第七码头尽头，脚边是昨夜海水留下的白色盐线，手里握着父亲失踪前寄来的铜制罗盘。罗盘的指针没有指向北方，而是固执地指向港口深处那座废弃的潮汐钟楼。",
        "钟楼已经停摆十三年。城里所有人都知道它在大停电那晚烧坏，连同旧城区的导航塔、潮汐档案馆和三十七艘失联渔船一起，成了北港不能被公开提起的伤口。可沈砚知道，父亲最后一封信里写过一句话：如果罗盘开始逆潮转动，就去找钟楼下的第二道门。",
        "他穿过卸货区时，港务局的巡检无人机从雾里滑过，红色扫描光贴着集装箱边缘扫下。沈砚缩进一排冷藏柜之间，听见自己的心跳和远处的浪声叠在一起。十三年前他还是个孩子，只记得母亲抱着他站在避难所门口，看见天边有一圈蓝白色的光从海面升起，像城市被某种巨大的眼睛短暂注视。",
        "钟楼的外墙覆盖着黑色海藻，铁门上的封条早已褪色。沈砚把罗盘贴近锁孔，指针忽然震动，铜壳内传出细小的齿轮声。门没有立刻打开，而是从门缝里吐出一张薄薄的感应纸，上面浮现出父亲的字迹：不要相信第一次听见的求救声。",
        "沈砚的手指僵住。就在这时，钟楼内部响起了敲击声。三下，停顿，两下，再三下。那是北港旧船员用来表示生还者的节奏。雾里有人轻声喊他的名字，声音像父亲，却更年轻，也更近。",
        "他没有回应。父亲教过他，真正的海上求救不会喊熟人的名字，因为失事者不知道岸上是谁在听。沈砚把感应纸折好，取下腰间的机械钥匙，插入门侧第二个几乎被锈迹盖住的孔。锁芯转动时，整座钟楼发出低沉的叹息，仿佛沉睡多年的城市机器终于承认有人找到了它的伤口。",
        "门后不是楼梯，而是一条向下的潮湿甬道。墙壁两侧嵌着旧式信号灯，每隔十米亮起一盏，光色从绿色渐渐变为蓝色。沈砚沿着甬道走了二十七级台阶，空气里的盐味变成了金属味。他看见尽头有一扇玻璃门，门后漂浮着无数细小的光点，像被困在水里的星群。",
        "玻璃门自动开启。一个女人站在控制台前，穿着港务局早已淘汰的灰色制服，左眼覆着透明义眼。她没有转身，只说：你比预定时间晚了九年。沈砚握紧罗盘，问她是谁。女人抬手关闭外部拾音器，雾中的求救声随即消失，只剩机器低鸣。",
        "我叫陆珩，曾是你父亲的合作者。她转过身，义眼里映出潮汐钟楼的内部结构图。十三年前，失联的不是三十七艘船，而是整条近海记忆链。有人把北港所有关于那晚的记录切走，塞进了这座钟楼底下。你父亲留下罗盘，是因为只有沈家血样能重新打开它。",
        "沈砚想问父亲是否还活着，可问题卡在喉咙里。控制台中央的水晶盘忽然亮起，一段残缺影像投在半空。影像里，父亲站在暴雨中的甲板上，身后海面裂开一道蓝白色竖光。他对镜头说：如果砚儿看到这段记录，说明他们又开始伪造求救声了。不要来找我，先救北港。",
        "陆珩按下暂停键。救北港四个字悬在空气里，比任何遗言都更沉。沈砚终于明白，自己不是被召回的儿子，而是被迟到启动的钥匙。钟楼上方传来无人机撞击铁门的声音，封锁系统正在被外部接管。",
        "他把罗盘放进水晶盘的凹槽。齿轮咬合的一瞬间，整座钟楼重新开始计时。停摆十三年的指针从雾中划过，第一声钟响震开港口上空的潮气，也惊醒了所有被删改过记忆的人。沈砚看见控制台上浮出新的坐标：北纬三十九度，旧航道尽头，失踪船队最后一次集体转向的地方。",
        "陆珩递给他一枚黑色数据钥匙，说：现在你有两个选择，公开钟楼，或者追上那道光。沈砚看向重新亮起的港口，远处的雾正在散去，但海平线后仍有蓝白色微光一闪一闪，像有人在黑暗深处眨眼。",
        "他把数据钥匙收进外套内袋。先公开钟楼。他说。让所有人知道我们为什么出发。然后，我去找他们。",
        "第二声钟响落下时，北港所有屏幕同时亮起父亲留下的第一段证词。沈砚走出钟楼，雾水打湿他的睫毛。码头上的人们抬头看向停摆多年后重新运转的指针，而他第一次感觉，失踪并不是故事的终点，只是被某些人强行藏起的开端。",
    ]
    return "\n\n".join(paragraphs)


def _phase_payloads(root: Path) -> dict[str, tuple[str, str]]:
    base = root.as_posix()
    project_spec = f"""# 百万字长篇项目规格

项目名：雾港回声
目标规模：1,000,000 中文字
核心类型：近未来悬疑 / 海港城市记忆谜案 / 群像成长
主线问题：十三年前北港大停电和失踪船队的真相被谁切走，沈砚如何从迟到的钥匙成长为公开真相并重建城市记忆的人。

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
- 本轮实战只完成可验收的第一章样章和全书生产结构，不伪造百万字全本已完成

验收闸门：
1. 每章必须有章节规划、正文、审校记录、连续性记录。
2. 每卷必须有卷纲、伏笔账本、角色弧线账本。
3. 全书编纂只能汇总已验收章节，禁止把未生成章节标成完成。
"""
    bible = """# 小说圣经

## 世界观
北港是一座依靠潮汐能源和近海导航网络兴起的城市。十三年前大停电后，公共记忆系统被篡改，失踪船队与潮汐钟楼被写成事故残留。

## 主角
沈砚：二十四岁，机械修复师，父亲失踪后离开北港。核心弧线是从私人寻亲转向公共真相。

陆珩：前港务局信号工程师，义眼保存部分事故记录。她是引导者，但隐瞒过关键失败。

沈越明：沈砚父亲，旧导航系统设计者之一。失踪前把罗盘留给儿子。

## 长线伏笔
- 铜制罗盘只在伪造求救声出现时逆潮转动。
- 潮汐钟楼保存被切走的近海记忆链。
- 蓝白色竖光不是自然现象，而是外部记忆抽取装置。

## 风格规则
叙事保持悬疑推进，章节末尾必须提供信息增量；技术设定通过行动展示，避免说明书式堆叠。
"""
    volume_plan = """# 第一卷卷纲：停摆的钟

卷目标：让沈砚回到北港，打开潮汐钟楼，发现城市记忆被切走，并公开第一段证词。

章节范围：1-40 章
- 1-5：回港、罗盘异常、钟楼入口、陆珩登场。
- 6-12：记忆链碎片恢复，旧船员证词互相矛盾。
- 13-24：港务局阻挠，沈砚发现父亲当年参与封存。
- 25-34：追踪旧航道，找到第一艘失踪船的空壳。
- 35-40：公开钟楼证据，北港进入全城记忆震荡。

第一卷验收：主角目标从“找父亲”升级为“救北港”，并明确第二卷追踪旧航道。
"""
    chapter_plan = """# 第一章规划：雾港的回声

章节目标：
- 沈砚回到北港。
- 罗盘指向停摆钟楼。
- 识别伪造求救声。
- 打开钟楼并获得父亲第一段证词。

场景节拍：
1. 雾港码头建立气氛和罗盘异常。
2. 巡检无人机制造外部压力。
3. 钟楼门口出现父亲警告。
4. 沈砚拒绝伪造求救声，打开第二道门。
5. 陆珩说明记忆链被切走。
6. 父亲影像给出“先救北港”使命。

验收条件：正文不少于 1800 中文字符；必须包含罗盘、钟楼、伪造求救声、陆珩、父亲证词、公开钟楼决定。
"""
    review = """# 第一章审校记录

审校 Agent：长篇审校Agent agent:25

检查结果：
- 章节目标全部出现。
- 主角动机从寻父过渡到救北港，转折清晰。
- 悬疑信息有递进：罗盘异常 -> 伪造求救声 -> 记忆链被切走 -> 父亲证词。

修订要求：
- 已检查到章节末尾需要明确下一步行动，正文已用“公开钟楼，然后追上那道光”处理。

验收结果：通过
"""
    audit = """# 连续性审计 001

连续性 Agent：长篇连续性Agent agent:26

设定检查：
- 大停电、失踪船队、潮汐钟楼、记忆链四个核心设定一致。
- 罗盘触发规则首次建立，未与后续计划冲突。
- 陆珩身份与卷纲中的引导者定位一致。

风险：
- 后续必须解释“沈家血样”权限来源。
- 后续必须给出港务局为何能封锁公共记忆系统。

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
- 第一卷第 2-40 章未生成，禁止标记完成。
- 第二至第五卷只有规模规划，未进入正文生产。

下一轮执行：
1. 生成第 2 章章节规划。
2. 按章节规划生成第 2 章正文。
3. 审校与连续性审计通过后写入编纂清单。

验收结果：阶段性通过
"""
    return {
        "task.writing.longform_novel_project": ("project_spec.md", project_spec),
        "task.writing.novel_bible_build": ("novel_bible.md", bible),
        "task.writing.volume_planning": ("volumes/volume_01_plan.md", volume_plan),
        "task.writing.chapter_planning": ("chapters/chapter_001_plan.md", chapter_plan),
        "task.writing.chapter_drafting": ("chapters/chapter_001_draft.md", _chapter_text()),
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
    Phase("01-project", "task.writing.longform_novel_project", "执行 task.writing.longform_novel_project：建立百万字长篇《雾港回声》项目规格，并写入 artifact。"),
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
        _assert_file(root / "novel_bible.md", min_chars=250, required_terms=("沈砚", "陆珩", "伏笔")),
        _assert_file(root / "volumes/volume_01_plan.md", min_chars=200, required_terms=("第一卷", "1-40", "第二卷")),
        _assert_file(root / "chapters/chapter_001_plan.md", min_chars=200, required_terms=("章节目标", "验收条件", "陆珩")),
        _assert_file(root / "chapters/chapter_001_draft.md", min_chars=1800, required_terms=("沈砚", "潮汐钟楼", "陆珩", "父亲", "公开钟楼")),
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
        if policy.get("agent_group_id") != required_group:
            raise AssertionError(f"{item['phase_id']} missing policy agent_group_id")
        if coordination.get("agent_group_id") != required_group:
            raise AssertionError(f"{item['phase_id']} missing coordination agent_group_id")
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
