# RunOutcome 统一收口设计书

日期：2026-05-24

## 1. 问题定义

当前项目已经具备长任务基本执行能力：主 Agent 能列 todo、调用工具、写入多文件产物、记录工具观察、生成阶段报告。但任务完成状态的对接方式仍不成熟。

这次 `professional-iterative-game-delivery` 长任务暴露出明确矛盾：

- `professional_runtime` 内部判定：
  - `professional_task_deliverable_validation_checked.passed = false`
  - `professional_task_completion_judged.completion_allowed = false`
  - `loop_terminal.status = failed`
  - `terminal_reason = partial_contract_failed`
- `long_runner` 外层判定：
  - `passed = true`

这说明系统里存在多套完成判定：

1. professional runtime 自己的 verification / completion judgment。
2. `TaskResult.status` / `terminal_reason`。
3. `done` payload 的最终文本。
4. `long_runner` 的 response / event / 文件存在检查。

这些判定没有统一的权威出口。外部系统仍在通过事件名、关键词、文件存在、工具出现与否来重新裁决成功。这种对接方法脆弱，容易产生假阳性。

正确目标不是给 `long_runner` 加更多事件字符串判断，而是建立一个正式的运行结果协议：`RunOutcome`。

## 2. 当前代码事实

### 2.1 已有可复用结构

当前代码中已有一些成熟部件，应该收敛而不是推倒重写。

- `backend/runtime/professional_runtime/completion_judgment.py`
  - `VerificationReview`
  - `CompletionJudgment`
  - `judge_completion`
- `backend/runtime/memory/tool_observation_ledger.py`
  - 工具观察账本
  - 写入、验证、委派、读文件等 evidence 分类
- `backend/runtime/professional_runtime/driver.py`
  - 构建 evidence packet
  - 运行 deliverable validation
  - 运行 obligation validation
  - 产出 `professional_task_completion_judged`
  - 设置 `outcome.terminal_reason`
- `backend/task_system/tasks/run_models.py`
  - `TaskRunLedger`
  - `TaskResult`
- `backend/runtime/unit_runtime/finalizer.py`
  - 负责最终 task result、agent run result、checkpoint、commit
- `backend/tests/system_eval/long_runner.py`
  - 外层长任务评测，但目前自己判 passed

### 2.2 当前缺失

当前缺失的不是“更多验证器”，而是一个统一的任务收口对象。

现有 `CompletionJudgment` 很接近最终判定，但它仍偏向专业任务内部判断，不承担完整外部协议职责。它缺少：

- 标准化 `status` 与 `completed` 对外语义。
- artifact refs / changed files / verification refs 的统一承接。
- `resume_recommended` 和 `next_required_actions`。
- 对普通任务、专业任务、委派任务、图任务的统一出口。
- 被 `TaskResult`、`done payload`、`long_runner`、UI 共同消费的协议位置。

### 2.3 不能继续采用的方式

禁止继续采用以下方式作为完成判定：

- 外层扫描 `event_types`。
- 外层识别 `professional_task_deliverable_validation_checked` 这类内部事件。
- 外层根据 `response.contains("验证")` 判定验证通过。
- 外层根据 `write_file` 出现判定任务完成。
- 外层根据文件存在覆盖 runtime 内部失败。
- finalizer 因为有 `final_content` 就把失败任务包装成可提交成功。

事件流只能作为审计日志，不能作为外部完成协议。

## 3. 设计原则

### 3.1 单一完成权威

任务完成权只属于 `RunOutcome`。

```text
RunOutcome.completed == true
```

是外部系统判断任务完成的唯一标准。

### 3.2 模型判断语义，运行时判断证据

模型负责：

- 理解用户目标。
- 规划步骤。
- 调用工具。
- 解释结果。
- 识别下一步。

运行时负责：

- 记录工具观察。
- 记录文件写入。
- 记录命令结果。
- 记录浏览器/测试证据。
- 判断最终声明是否有证据支撑。

### 3.3 事件是日志，Outcome 是协议

`runtime_loop_event`、`tool_result_received`、`professional_task_completion_judged` 都是内部过程事件。

外部系统不得直接依赖这些事件名做完成裁决。

### 3.4 Partial 不是 Completed

有产物但缺验证，应为：

```text
status = partial
completed = false
```

不能因为产物存在或回答非空就判 completed。

### 3.5 不允许外层重判

`long_runner`、UI、API、memory、trace 只能消费 `RunOutcome`，不能重新解释任务完成状态。

## 4. 目标架构

### 4.1 固定链路

目标运行链路：

```text
User Request
  -> main-model-owned understanding
  -> task requirement contract
  -> professional/runtime execution
  -> evidence ledger
  -> verification review
  -> completion judgment
  -> RunOutcome
  -> TaskResult.completion
  -> done.completion
  -> UI / long_runner / API / memory
```

### 4.2 层级职责

#### professional_runtime

负责专业任务内部执行和证据判断。

输出：

- evidence packet
- deliverable validation
- obligation validation
- verification review
- completion judgment
- run outcome

#### finalizer

负责提交和持久化。

允许：

- 承接 `RunOutcome`
- 写入 `TaskResult`
- 写入 `done payload`
- 写入 checkpoint / trace

禁止：

- 重判 completion。
- 用 final content 覆盖 failed / partial。
- 把 `completion_allowed=false` 改成 completed。

#### task_result

任务结果的持久化对象。

必须包含：

```text
completion: RunOutcome
```

`TaskResult.status` 从 `RunOutcome.status` 派生。

#### long_runner

长任务评测系统。

专业任务判定规则：

```text
if done.completion exists:
    passed = done.completion.completed is true
else if professional task:
    passed = false
else:
    use legacy checks
```

#### UI / API

只展示和传递 `RunOutcome`，不再从事件中拼状态。

## 5. RunOutcome 数据模型

新增模块：

```text
backend/runtime/outcome/
  __init__.py
  models.py
  builder.py
  policies.py
```

### 5.1 模型定义

```python
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


RunOutcomeStatus = Literal[
    "completed",
    "partial",
    "blocked",
    "failed",
    "aborted",
]

EvidenceConfidence = Literal[
    "none",
    "claimed",
    "observed",
    "verified",
]


@dataclass(frozen=True, slots=True)
class RunOutcome:
    outcome_id: str
    task_run_id: str
    task_id: str
    runtime_lane: str
    source: str

    status: RunOutcomeStatus
    completed: bool
    terminal_reason: str
    user_visible_status: str
    summary: str = ""

    evidence_confidence: EvidenceConfidence = "none"
    verification_passed: bool = False
    completion_allowed: bool = False

    completion_judgment_ref: str = ""
    verification_ref: str = ""
    evidence_packet_ref: str = ""

    satisfied_deliverables: tuple[str, ...] = ()
    missing_deliverables: tuple[str, ...] = ()
    unsatisfied_obligations: tuple[str, ...] = ()
    missing_output_paths: tuple[str, ...] = ()
    unsupported_claims: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    artifact_refs: tuple[str, ...] = ()
    changed_files: tuple[str, ...] = ()
    verification_refs: tuple[str, ...] = ()
    observation_refs: tuple[str, ...] = ()

    resume_recommended: bool = False
    resume_reason: str = ""
    next_required_actions: tuple[str, ...] = ()

    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "runtime.run_outcome"

    def __post_init__(self) -> None:
        if self.authority != "runtime.run_outcome":
            raise ValueError("RunOutcome authority must be runtime.run_outcome")
        if not self.outcome_id:
            raise ValueError("RunOutcome requires outcome_id")
        if not self.task_run_id:
            raise ValueError("RunOutcome requires task_run_id")
        if self.completed != (self.status == "completed"):
            raise ValueError("RunOutcome.completed must match status == completed")
        if self.completed and not self.completion_allowed:
            raise ValueError("completed RunOutcome requires completion_allowed")
        if self.completed and not self.verification_passed:
            raise ValueError("completed RunOutcome requires verification_passed")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in (
            "satisfied_deliverables",
            "missing_deliverables",
            "unsatisfied_obligations",
            "missing_output_paths",
            "unsupported_claims",
            "limitations",
            "artifact_refs",
            "changed_files",
            "verification_refs",
            "observation_refs",
            "next_required_actions",
        ):
            payload[key] = list(getattr(self, key))
        return payload
```

### 5.2 状态语义

#### completed

允许对用户说任务已完成。

必须满足：

- `completion_allowed = true`
- `verification_passed = true`
- 无 missing deliverables
- 无 unsupported claims
- 无 unsatisfied obligations

#### partial

有真实产物或真实进展，但未满足完整验收。

典型情况：

- 文件写了，但浏览器验证没跑。
- 修复做了，但测试没通过。
- 部分 deliverables 满足。
- 工具预算到达，但 evidence ledger 有真实产物。

#### blocked

不能继续执行。

典型情况：

- 缺权限。
- 缺工具。
- 缺材料。
- contract gate 阻塞。
- 必要能力不可用。

#### failed

执行或收口失败。

典型情况：

- executor failed。
- protocol leak。
- unsupported claims 严重。
- validation contradicted。

#### aborted

用户或系统中断。

## 6. Builder 规则

### 6.1 professional outcome builder

新增：

```text
backend/runtime/outcome/builder.py
```

核心函数：

```python
def build_professional_run_outcome(
    *,
    task_run_id: str,
    task_id: str,
    runtime_lane: str,
    terminal_reason: str,
    verification: dict[str, Any],
    completion_judgment: dict[str, Any],
    tool_observation_ledger: dict[str, Any],
    result_refs: list[str],
    final_content: str,
) -> RunOutcome:
    ...
```

状态映射：

```text
completion_allowed=true and verification.passed=true
  -> completed

terminal_reason in user_aborted
  -> aborted

completion_judgment.status in contradicted
  -> failed

has artifact refs or observation refs and missing deliverables
  -> partial

missing required actions / blocked reason
  -> blocked

otherwise
  -> failed
```

### 6.2 evidence confidence

```text
none      没有真实 observation
claimed   只有最终回答声称
observed  有工具观察、文件写入、命令输出
verified  有验证命令或浏览器/测试证据，并通过
```

### 6.3 resume recommendation

如果状态不是 completed，且存在真实进展，应该给出续跑建议：

```text
resume_recommended = true
```

`next_required_actions` 从以下来源合并：

- missing required actions
- missing deliverables
- required action queue
- completion judgment reasons

## 7. 对现有代码的改造点

### 7.1 `backend/runtime/professional_runtime/driver.py`

在 `professional_task_completion_judged` 后构建 `RunOutcome`。

当前已有：

- `verification`
- `completion_judgment`
- `tool_observation_ledger`
- `outcome.terminal_reason`
- `outcome.result_refs`
- `outcome.final_content`

新增：

```python
run_outcome = build_professional_run_outcome(...)
outcome.run_outcome = run_outcome.to_dict()
```

并追加事件：

```text
professional_task_run_outcome_built
```

事件用于审计，不作为外部协议。

### 7.2 `ProfessionalTaskRunOutcome`

增加：

```python
run_outcome: dict[str, Any] = field(default_factory=dict)
```

### 7.3 `backend/task_system/tasks/run_models.py`

`TaskResult` 增加：

```python
completion: dict[str, Any] = field(default_factory=dict)
```

`to_dict()` 保持结构化输出。

### 7.4 `backend/runtime/unit_runtime/finalizer.py`

finalizer 接收 `task_result` 时：

- 如果已有 `completion`，必须原样保留。
- `TaskResult.status` 不得覆盖 `completion.status`。
- `terminal_reason` 不得覆盖 `completion.terminal_reason`。

禁止：

```text
final_content 非空 -> completed
```

### 7.5 `backend/runtime/unit_runtime/loop.py`

done payload 增加：

```python
"completion": task_result.get("completion") or outcome.run_outcome
```

专业任务如果没有 completion envelope，应视为 runtime assembly 缺陷。

### 7.6 `backend/runtime/memory/trace_reader.py`

trace summary 增加：

```text
run_outcome
completion_status
completion_allowed
resume_recommended
```

trace reader 可以从 event 或 task_result 读取，但对外只输出 `run_outcome`。

### 7.7 `backend/tests/system_eval/long_runner.py`

删除基于 professional event 的直接判定。

新增规则：

```python
completion = done_payload.get("completion") or runtime_trace.get("run_outcome")
if completion:
    turn_result.passed = bool(completion.get("completed") is True)
elif "professional_task" in scenario.coverage:
    turn_result.passed = False
else:
    turn_result.passed = legacy_check_result
```

专业任务缺 envelope 必须失败：

```text
professional.completion_envelope_missing
```

## 8. 文件级实施清单

### Phase 1：新增模型，不接入旧链路

文件：

- `backend/runtime/outcome/__init__.py`
- `backend/runtime/outcome/models.py`
- `backend/runtime/outcome/builder.py`
- `backend/tests/run_outcome_model_regression.py`

完成标准：

- `RunOutcome` 状态约束生效。
- completed 但 verification false 会抛错。
- partial 可以携带 artifact refs 和 resume actions。

### Phase 2：professional runtime 产出 RunOutcome

文件：

- `backend/runtime/professional_runtime/driver.py`
- `backend/runtime/professional_runtime/completion_judgment.py`（只补字段读取，不改核心判断）
- `backend/tests/professional_task_run_regression.py`

完成标准：

- 每个 professional task 都产出 `outcome.run_outcome`。
- `professional_task_run_outcome_built` 事件存在。
- 当前游戏长任务应得到 `status=partial` 或 `failed`，不能 completed。

### Phase 3：TaskResult / done payload 承接

文件：

- `backend/task_system/tasks/run_models.py`
- `backend/runtime/unit_runtime/finalizer.py`
- `backend/runtime/unit_runtime/loop.py`
- `backend/tests/query_runtime_runtime_loop_regression.py`

完成标准：

- `task_result.completion` 存在。
- `done.completion` 存在。
- finalizer 不覆盖 completion 状态。

### Phase 4：外层系统只消费 RunOutcome

文件：

- `backend/tests/system_eval/long_runner.py`
- `backend/runtime/memory/trace_reader.py`
- 可能涉及前端展示：
  - `frontend/src/lib/store/runtime.ts`
  - `frontend/src/components/chat/ChatPanel.tsx`

完成标准：

- 专业任务缺 completion envelope 直接失败。
- `completion.completed=false` 时 long_runner 不得 passed。
- UI 能显示 partial / blocked / failed 和 next required actions。

### Phase 5：清理旧对接

目标：

- 删除所有外层直接解释 professional 内部事件的成功判定。
- 保留事件只作 trace。
- 删除 response keyword 对专业任务 completed 的影响。

## 9. 验证矩阵

### 9.1 completed

场景：

- 代码修复
- 文件写入
- terminal 验证通过
- deliverable validation passed

期望：

```text
RunOutcome.status = completed
completed = true
long_runner.passed = true
```

### 9.2 partial

场景：

- 游戏文件写入完成
- 资产写入完成
- terminal 文件验证通过
- 浏览器玩法验收缺失

期望：

```text
RunOutcome.status = partial
completed = false
resume_recommended = true
long_runner.passed = false
```

### 9.3 failed

场景：

- 模型最终回答声称浏览器验证通过
- evidence ledger 没有 browser evidence

期望：

```text
unsupported_claims 非空
completed = false
long_runner.passed = false
```

### 9.4 blocked

场景：

- 必需工具不可见
- 权限拒绝
- 材料缺失

期望：

```text
status = blocked
resume_recommended = true 或 false
next_required_actions 指明阻塞项
```

### 9.5 aborted

场景：

- 用户中断

期望：

```text
status = aborted
completed = false
```

## 10. Cutover 规则

### 10.1 旧任务兼容

普通非专业任务可以短期保留 legacy checks。

专业任务不允许 fallback：

```text
professional task without RunOutcome = failed
```

### 10.2 禁止双写分歧

迁移期间允许：

```text
TaskResult.status
TaskResult.completion.status
```

同时存在。

但必须满足：

```text
TaskResult.status == normalize(completion.status)
TaskResult.terminal_reason == completion.terminal_reason
```

若不一致，应记录结构错误并让外层失败。

### 10.3 回滚规则

如果 RunOutcome 构建异常：

- 不允许静默 completed。
- task result status = failed。
- terminal_reason = outcome_build_failed。
- done.completion.status = failed。

## 11. 反模式清单

禁止：

- 在 `long_runner` 里解析 `professional_task_completion_judged` 决定成功。
- 在 UI 里根据最终回答包含“完成”显示成功。
- 在 finalizer 里因为有 `final_content` 改成 completed。
- 在 validator 里直接删除 partial 产物。
- 用 env 开关保留旧收口路径。
- 用关键词替代 evidence refs。

允许：

- 事件用于审计。
- response 用于展示。
- artifact refs 用于打开产物。
- evidence ledger 用于构建 outcome。
- completion envelope 用于外部判定。

## 12. 最终目标

完成后，项目的收口链路应变成：

```text
内部可以复杂；
外部只读 RunOutcome。
```

最终判断只有一句：

```text
RunOutcome.completed == true
```

这会消除当前“内部失败、外部 passed”的结构性问题，也为后续任务系统 registry、长任务续跑、UI 状态展示、自动评测提供稳定协议。
