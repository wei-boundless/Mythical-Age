# 任务系统控制动作架构升级设计书

## 0. 文档状态

本文是任务系统控制动作与任务契约模型的架构升级设计书。

状态：等待用户审阅后再实施。

本文替代此前围绕 `request_task_run`、`entry_reason`、七类 `primary_mode` 以及把 `todo` 当作任务模式的临时草案。当前代码尚未按本文修改。

执行链路以 `task_as_turn_overlay_architecture_review_20260628.md` 为更底层约束：本文件负责定义 `request_task_run`、`TaskStartIntent` 和任务契约分层；普通 `TaskRun` 的模型决策、工具调用和最终回复必须回到 `single_agent_turn + task overlay + state patch`，不能默认进入独立 `task_executor` 模型循环。

底层源码对照见 `task_as_turn_overlay_architecture_review_20260628.md` 第 2.9 节；该节已对 Codex、Claude Code、Hermes 与当前项目的 runtime branch、TaskRun lifecycle、ActiveTurn state、task executor、provider schema 和 CLI/slash 入口逐项对齐。

本次关键修正：

- `request_task_run` 名称保留。
- `request_task_run` 是 agent 发出的“请求系统开启长任务运行资源”的控制信号。
- 系统不根据用户自然语言猜测是否应该启动任务。
- provider strict tool/function calling 用作控制动作 schema 的承载层。
- `entry_reason` 退出 agent-facing 启动合同。
- agent-facing 启动合同使用 `task_objective` 表达任务目标。
- `primary_mode` 只表示请求 `TaskRun` 资源时要保存的主执行契约，只能是 `goal` 或 `plan`。
- `todo` 不是任务模式；`todo` 是任务执行工具契约，用来维护执行清单、状态和当前游标。
- `investigation / recovery / monitor / open_work` 不是 `primary_mode`，而是通过填写形态契约形成的任务形态。
- 图任务以后应复用同一套显式任务契约，而不是重新写一套隐式任务语义。

## 1. 核心定义

### 1.1 TaskRun

`TaskRun` 是系统为长任务运行分配的资源。

它负责绑定和管理：

- 任务身份；
- 任务目标；
- 主执行契约；
- 可选执行工具契约；
- 任务形态契约；
- 执行状态；
- 进度投影；
- 暂停、恢复、停止和失败收口；
- 验收与最终回复要求。

`TaskRun` 不是 agent 的普通工具调用结果，不是 agent 的新生命周期，也不是系统根据用户文字生成的语义标签。

对 agent 来说，`TaskRun` 只通过当前 turn 的动作面和尾部状态投影出现。agent 不进入 task 模式；agent 仍然在 turn 中行动。

### 1.2 主任务模式 Primary Mode

主任务模式是 agent 请求系统开启 `TaskRun` 资源时选择的主执行契约。

当前 `primary_mode` 只包括：

```text
goal
plan
```

含义：

- `goal` 建立目标契约，明确要达成什么、成功定义是什么、哪些证据可以证明完成。
- `plan` 建立计划契约，明确按哪些步骤推进、如何变更计划、何时重规划。

`primary_mode` 决定这段长任务资源保存哪一种主执行契约。它回答的是：后续 turn 的持续状态应以“达成目标”为主，还是以“按计划推进”为主。

### 1.3 Todo Tool Contract

`todo` 不是 `primary_mode`。

`todo` 是任务执行工具契约。它负责维护：

- 当前执行清单；
- 当前 active item；
- item 状态；
- item 依赖；
- 清单更新规则；
- 任务恢复时的执行游标。

`todo` 可以挂在任何 `TaskRun` 上，但它不能单独定义一段长任务资源。

换句话说：

- 如果 agent 要达成一个结果，使用 `primary_mode=goal`，必要时挂载 `todo_tool_contract`。
- 如果 agent 要按阶段或步骤推进，使用 `primary_mode=plan`，必要时挂载 `todo_tool_contract`。
- 如果 agent 只是需要维护事项清单，也必须先说明这条清单服务于哪个目标或计划。

`todo` 是显式任务契约构件，但不是任务模式。

### 1.4 任务形态 Task Shape

任务形态是主执行契约进入具体工作场景后的形状。

任务形态包括：

```text
standard
investigation
recovery
monitor
open_work
```

它们不是 `primary_mode`。

它们通过填写对应的形态契约获得：

- `standard`：普通目标或计划任务。
- `investigation`：查明未知问题，输出结论、证据和下一步裁决。
- `recovery`：从失败、暂停或中断状态恢复，接续已有目标、计划和执行游标。
- `monitor`：在有边界的观察窗口内持续观察目标。
- `open_work`：目标或范围尚未完全稳定，但确实需要系统分配长任务资源的过渡形态。

任务形态不能替代主任务模式。即使是 `recovery`，也必须说明恢复后是在 `goal` 还是 `plan` 契约下继续执行。

## 2. 当前问题

### 2.1 七类 `primary_mode` 混成同一层

当前代码把下面七个值放进同一个任务启动枚举：

```text
goal | plan | todo | investigation | recovery | monitor | open_work
```

证据：

- `backend/harness/runtime/control_action_schema.py:19`
- `backend/harness/loop/model_action_protocol.py:570`

问题在于这个枚举混合了三类不同对象：

- `goal / plan` 是启动 TaskRun 的主执行契约。
- `todo` 是任务执行工具契约和游标。
- `investigation / recovery / monitor / open_work` 是任务形态。

它们不应该共用 `primary_mode`。

这会导致 agent 误以为：

- 可以用清单本身启动任务，而不说明清单服务的目标或计划；
- 可以把“调查”“恢复”“监控”当作主执行契约，而不建立真实的目标或计划；
- 可以让系统根据模糊语义补猜 agent 本应显式给出的任务结构。

### 2.2 `entry_reason` 仍然污染启动合同

当前代码仍要求 agent 填写 `entry_reason`：

- `backend/harness/runtime/control_action_schema.py:197`
- `backend/harness/runtime/control_action_schema.py:228`
- `backend/harness/loop/model_action_protocol.py:573`
- `backend/harness/loop/model_action_protocol.py:575`
- `backend/harness/runtime/compiler.py:3005`
- `backend/harness/loop/single_agent_turn.py:5693`

问题：

`entry_reason` 让 agent 解释为什么当前 turn 不足以承载任务。这是开发视角或人类解释，不是系统启动任务需要的机器字段。

runtime 真正需要的是：

- 要完成什么；
- 用 `goal` 还是 `plan` 承载；
- 是否需要 `todo` 执行工具；
- 当前任务是什么形态；
- 第一步做什么；
- 看哪些对象；
- 如何验收；
- 有哪些恢复、调查、监控或开放工作边界。

### 2.3 旧路径仍会替 agent 选择模式

当前存在旧 seed 转换逻辑，会把旧字段推成 `goal` 或 `plan`：

- `backend/harness/loop/model_action_protocol.py:1070`
- `backend/harness/loop/task_lifecycle.py:121`
- `backend/harness/loop/task_lifecycle.py:261`

问题：

agent 才能决定本次任务以哪个主执行契约运行。runtime 可以校验、归一化和拒绝，但不能在启动路径里补猜模式。

### 2.4 模型可见上下文混淆了主契约和工具契约

当前 manifest 和 tail context 主要承接：

- `goal_context`
- `plan_context`
- `todo_context`

证据：

- `backend/harness/runtime/task_contract_manifest.py:151`
- `backend/harness/runtime/dynamic_context/task_mode_tail_context.py:17`
- `backend/harness/runtime/compiler.py:6981`
- `backend/harness/runtime/compiler.py:4217`

这说明系统已经需要同时暴露目标、计划和执行清单。但正确方向不是把三者都叫任务模式，而是明确分层：

- `goal_context / plan_context` 来自主执行契约；
- `todo_context` 来自执行工具契约和当前游标；
- tail context 应该提醒 agent 同时关注主契约、任务形态和 todo 游标，而不是把 todo 伪装成主模式。

## 3. 目标模型

### 3.1 启动合同分层

`request_task_run` 提交的是紧凑 `TaskStartIntent`。

`TaskStartIntent` 包含两类选择和一类可选工具：

```text
primary_mode: goal | plan
task_shape: standard | investigation | recovery | monitor | open_work
todo_tool_contract: null | TodoToolContract
```

含义：

- `primary_mode` 表示 agent 要建立哪一种主执行契约。
- `task_shape` 表示这次任务属于哪一种工作形态。
- `todo_tool_contract` 表示这次任务是否需要清单、状态和执行游标。

示例：

```text
调查 bug 根因：
primary_mode = plan
task_shape = investigation
todo_tool_contract = 可选，用于跟踪调查项

恢复失败任务：
primary_mode = plan 或 goal
task_shape = recovery
todo_tool_contract = 可选，用于恢复 active item

持续观察日志：
primary_mode = plan
task_shape = monitor
todo_tool_contract = 可选，用于记录检查项

目标明确但无需复杂计划：
primary_mode = goal
task_shape = standard
todo_tool_contract = 可选，用于跟踪小事项

用户给出一组待办并要求执行：
primary_mode = plan
task_shape = standard
todo_tool_contract = 必填，用作执行游标
```

### 3.2 TaskRun 契约结构

```text
TaskRun
├─ task_objective
├─ primary_mode: goal | plan
├─ primary_mode_contract
│  ├─ goal_contract
│  └─ plan_contract
├─ todo_tool_contract
│  └─ todo_cursor
├─ task_shape
│  ├─ standard
│  ├─ investigation_contract
│  ├─ recovery_contract
│  ├─ monitor_contract
│  └─ open_work_contract
└─ acceptance_contract
```

规则：

- 每个 `TaskRun` 必须有一个 `primary_mode`。
- `primary_mode` 只能是 `goal / plan`。
- `todo_tool_contract` 可以为空，但不能替代 `primary_mode_contract`。
- `task_shape` 默认是 `standard`。
- 非 standard 形态必须填写对应形态契约。
- 形态契约不能替代主执行契约。
- 图任务节点以后可以直接引用这些契约。

## 4. TaskStartIntent v3

agent-facing `request_task_run` 参数：

```json
{
  "public_progress_note": "向用户说明正在请求系统开启长任务资源",
  "public_action_state": {
    "visible_status": "thinking",
    "current_judgment": "当前目标需要系统分配长任务资源",
    "next_action": "提交 request_task_run",
    "evidence_refs": [],
    "open_risks": [],
    "completion_status": "working"
  },
  "task_objective": "这条任务线最终要完成的具体目标",
  "primary_mode": "goal|plan",
  "task_shape": "standard|investigation|recovery|monitor|open_work",
  "minimum_viable_next_step": "任务启动后立刻执行的第一步",
  "working_scope": {
    "target_objects": [],
    "workspace_refs": [],
    "source_refs": [],
    "excluded_scope": [],
    "known_constraints": []
  },
  "acceptance": {
    "mode": "checkpoint|user_review|best_effort|strict|none_yet",
    "criteria": [],
    "final_answer_requirements": []
  },
  "primary_mode_contract": {},
  "todo_tool_contract": null,
  "shape_contract": {}
}
```

必填机器字段：

- `task_objective`
- `primary_mode`
- `task_shape`
- `minimum_viable_next_step`
- `working_scope`
- `acceptance.mode`
- `primary_mode_contract`
- `todo_tool_contract`
- `shape_contract`

公开反馈字段：

- `public_progress_note`
- `public_action_state`

公开反馈用于用户可见状态和动作一致性，不参与系统判断是否应该启动任务。

`todo_tool_contract` 作为字段保留，但允许为 `null`。这样 strict schema 稳定，当前任务是否需要 todo 由 agent 在字段值中显式表达，而不是让 runtime 从自然语言里猜。

## 5. 显式契约构件

### 5.1 Goal Primary Contract

用途：

Goal contract 用来建立目标型任务。agent 明确知道要达成什么，并能给出成功定义。

契约：

```json
{
  "contract_kind": "goal",
  "goal_contract": {
    "user_visible_goal": "给用户看的目标表述",
    "task_run_goal": "agent 执行时使用的目标表述",
    "success_definition": "怎样才算目标达成",
    "non_goals": [],
    "working_scope": {
      "target_objects": [],
      "workspace_refs": [],
      "source_refs": [],
      "excluded_scope": [],
      "known_constraints": []
    },
    "completion_evidence": [],
    "evidence_policy": {
      "evidence_required": true,
      "acceptable_evidence_refs": []
    },
    "acceptance_ref": "acceptance"
  }
}
```

agent 使用规则：

- 目标必须可执行，不写“处理一下”“继续看”。
- 成功定义必须能被后续验收使用。
- 如果目标太大，需要选择 `primary_mode=plan`，或者在后续通过任务控制升级为计划推进。
- 如果执行中目标变化，必须通过 replan 或任务控制显式说明。

图任务用途：

- 图节点可以把 `goal_contract` 作为节点任务目标。
- 图边可以读取 `success_definition` 和 `completion_evidence` 判断是否进入下一节点。

### 5.2 Plan Primary Contract

用途：

Plan contract 用来建立步骤型任务。agent 需要按计划推进、更新步骤、记录偏差，并在必要时重规划。

契约：

```json
{
  "contract_kind": "plan",
  "plan_contract": {
    "plan_id": "plan:stable-id",
    "plan_version": "initial",
    "strategy_summary": "总体推进策略",
    "plan_status": "agent_managed|user_approved|blocked|completed",
    "active_step_id": "",
    "major_steps": [
      {
        "step_id": "step:1",
        "title": "步骤标题",
        "status": "pending|in_progress|completed|blocked",
        "done_when": "该步骤完成条件",
        "evidence_expectations": [],
        "depends_on_step_ids": []
      }
    ],
    "allowed_plan_operations": ["create", "update", "replan", "explain_deviation"],
    "replan_policy": {
      "requires_reason": true,
      "version_must_change_or_reason_required": true
    },
    "working_scope": {
      "target_objects": [],
      "workspace_refs": [],
      "source_refs": [],
      "excluded_scope": [],
      "known_constraints": []
    }
  }
}
```

agent 使用规则：

- Plan contract 的核心是“按步骤推进”，不是把目标写成一段说明。
- 计划很长时，完整计划进入稳定上下文，当前步骤进入尾部注意力索引。
- 偏离计划必须解释偏离原因或更新计划。
- todo 不是计划本身；todo 是执行清单和当前游标，plan 是策略结构。
- 如果需要逐项执行和频繁更新状态，在 `todo_tool_contract` 中维护执行游标。

图任务用途：

- 图任务可以把 `major_steps` 编译成子节点、阶段或边条件。
- 图运行器可以用 `active_step_id` 和 `done_when` 做进度投影。

### 5.3 Todo Tool Contract

用途：

Todo tool contract 用来在任务执行中维护清单、状态和当前游标。它帮助 agent 记住“现在正在做哪一项”，但不决定这条任务为什么存在。

契约：

```json
{
  "tool_kind": "todo",
  "todo_tool_contract": {
    "enabled": true,
    "todo_list_id": "todo:stable-id",
    "attached_to_primary_mode": "goal|plan",
    "source": "agent_created|derived_from_plan|restored_from_task|user_supplied",
    "active_item_id": "",
    "items": [
      {
        "todo_id": "todo:1",
        "content": "要完成的事项",
        "active_form": "正在执行时的表述",
        "status": "pending|in_progress|completed|blocked",
        "notes": "",
        "evidence_expectations": [],
        "depends_on_todo_ids": []
      }
    ],
    "completion_policy": "checkpoint_only|all_items_required|user_review",
    "allowed_todo_operations": ["create", "update_status", "reorder", "append", "close"],
    "cursor_policy": {
      "single_active_item": true,
      "update_required_on_progress_change": true
    }
  }
}
```

agent 使用规则：

- 不允许使用 `primary_mode=todo`。
- todo 只维护事项、状态和游标，不定义最终验收。
- todo 可以来自 plan，也可以附着在 goal 下做轻量执行跟踪。
- 如果用户给的是一组执行事项，通常应使用 `primary_mode=plan`，并把事项放入 `todo_tool_contract`。
- 进度变化时必须更新 todo cursor。
- 完成 todo 不等于任务验收完成，最终仍看 `acceptance`。

图任务用途：

- 图任务可以把 todo item 编译成可恢复的执行单元。
- 图运行器可以用 `active_item_id` 保存恢复位置。
- 图边可以读取 todo item status，但不能把 todo status 当作任务生命周期的主模式。

## 6. 任务形态契约

任务形态不是 `primary_mode`。它们是通过填写形态契约，让 `goal` 或 `plan` 主契约进入某种具体工作场景。

### 6.1 Standard Task Shape

用途：

默认任务形态。没有额外调查、恢复、监控或开放边界。

契约：

```json
{
  "task_shape": "standard",
  "shape_contract": {
    "notes": []
  }
}
```

适用：

- 明确目标任务；
- 普通计划任务；
- 挂载 todo 执行游标的目标或计划任务。

### 6.2 Investigation Task Shape

用途：

调查型任务。目标不是直接完成产物，而是查明未知问题，形成结论、证据和下一步裁决。

契约：

```json
{
  "task_shape": "investigation",
  "shape_contract": {
    "problem_statement": "要查明的问题",
    "question": "需要回答的核心问题",
    "known_facts": [],
    "unknowns": [],
    "evidence_targets": [],
    "source_rules": {
      "must_read_refs": [],
      "allowed_source_refs": [],
      "excluded_source_refs": []
    },
    "expected_finding": {
      "must_include_root_cause": false,
      "must_include_evidence": true,
      "must_include_next_action": true
    },
    "decision_gate": {
      "allowed_outcomes": ["resolved", "needs_more_evidence", "blocked", "handoff_to_plan"],
      "default_when_insufficient": "needs_more_evidence"
    }
  }
}
```

组合建议：

- `primary_mode=plan`：适合多步调查。
- `primary_mode=goal`：适合只需回答一个边界清楚的问题。
- `todo_tool_contract`：适合跟踪调查项和证据项。

图任务用途：

- 图节点可用 `decision_gate.allowed_outcomes` 决定下一条边。
- `evidence_targets` 可转成节点输入资源。

### 6.3 Recovery Task Shape

用途：

恢复型任务。它不是“恢复模式”，而是带恢复合同的任务形态。恢复后仍必须在 `goal` 或 `plan` 主契约下继续执行。

契约：

```json
{
  "task_shape": "recovery",
  "shape_contract": {
    "recovery_handle": "runtime 提供或显式任务提供的恢复句柄",
    "previous_state_ref": "上一状态引用",
    "failure_origin": "失败、暂停或中断来源",
    "preserved_state_refs": [],
    "completed_work_refs": [],
    "unfinished_work": [],
    "next_resume_step": "恢复后的第一步",
    "resume_policy": {
      "requires_same_task_identity": true,
      "allow_replan_after_resume": true
    },
    "stop_boundary": {
      "must_report_unfinished_work": true,
      "must_report_resume_hint": true
    }
  }
}
```

组合建议：

- `primary_mode=plan`：适合从中断阶段继续。
- `primary_mode=goal`：适合围绕原目标恢复并直接收口。
- `todo_tool_contract`：适合恢复 active item、未完成事项和执行游标。

图任务用途：

- 图运行器可用 `previous_state_ref` 和 `next_resume_step` 恢复节点。
- `unfinished_work` 可转成新的 todo items，但仍挂在 `todo_tool_contract` 下。

### 6.4 Monitor Task Shape

用途：

监控型任务。当前阶段仅表示有边界的 `TaskRun` 内观察任务；除非后续实现真实调度器，否则不能暗示无限期后台监控。

契约：

```json
{
  "task_shape": "monitor",
  "shape_contract": {
    "monitor_target": "要观察的目标",
    "observation_window": {
      "mode": "bounded|until_trigger|single_checkpoint",
      "max_duration_hint": "",
      "max_observation_count": 0
    },
    "trigger_conditions": [],
    "checkpoint_policy": {
      "report_on_each_trigger": true,
      "report_when_no_trigger": true
    },
    "stop_conditions": [],
    "report_shape": {
      "include_current_state": true,
      "include_trigger_status": true,
      "include_next_recommendation": true
    }
  }
}
```

组合建议：

- `primary_mode=plan`：适合按观察步骤推进。
- `primary_mode=goal`：适合围绕一个明确判断目标观察。
- `todo_tool_contract`：适合记录检查项。

图任务用途：

- 图节点可把 `trigger_conditions` 编译为边条件。
- 调度器成熟后可把 `observation_window` 接入周期任务。

### 6.5 Open Work Task Shape

用途：

开放工作型任务。它不是兜底垃圾桶，而是目标暂未完全稳定但确实需要持续生命周期时的过渡形态。

契约：

```json
{
  "task_shape": "open_work",
  "shape_contract": {
    "stabilization_target": "需要逐步稳定成明确 goal 或 plan 的对象",
    "known_boundary": "当前已知边界",
    "known_unknowns": [],
    "minimum_progress_unit": "最小可交付进展",
    "promotion_policy": {
      "promote_to_goal_when": "",
      "promote_to_plan_when": ""
    },
    "review_checkpoint": "何时要求用户或系统重新确认形态"
  }
}
```

组合建议：

- `primary_mode=goal`：适合目标可写但范围仍开放。
- `primary_mode=plan`：适合先用探索计划推进。
- `todo_tool_contract`：只用于跟踪当前开放工作里的执行事项。
- 不允许没有主执行契约就进入 `open_work`。

图任务用途：

- 图任务可把 `open_work` 用作前置澄清节点。
- 达到 `promotion_policy` 后必须转换为明确目标或计划。

## 7. Agent-facing 启动引导

目标文案：

```text
你正在为本轮选择唯一行动。

当当前目标需要系统保存目标、步骤、todo 游标、恢复点或验收边界时，选择 request_task_run。
request_task_run 是资源启动信号。你发出它，就表示你要让 runtime 建立 TaskRun 资源，并从 minimum_viable_next_step 开始持续承载这项工作。

先选择 primary_mode，只能二选一：
- goal：你要达成一个明确结果，并能写出成功定义；
- plan：你要按步骤、阶段或策略推进，并可能更新计划。

todo 不是 primary_mode。
todo 是你在任务执行中维护清单、状态和当前游标的工具契约。
如果这条任务需要跟踪事项，填写 todo_tool_contract。
不要用 todo 启动任务；要说明这份清单服务于 goal 还是 plan。

再选择 task_shape：
- standard：普通目标或计划任务；
- investigation：查明未知问题，并给出证据、结论和下一步裁决；
- recovery：从失败、暂停或中断状态恢复；
- monitor：在有边界的观察窗口内观察目标；
- open_work：目标或范围尚未完全稳定，但确需系统分配长任务资源。

task_shape 不能替代 primary_mode。
即使是 recovery、monitor 或 investigation，也必须说明它在 goal 还是 plan 契约下执行。

填写 TaskStartIntent 时：
- task_objective 写任务最终要完成什么；
- primary_mode 写主执行契约，只能是 goal 或 plan；
- task_shape 写任务形态；
- primary_mode_contract 写 goal 或 plan 对应的契约；
- todo_tool_contract 写执行清单和游标；不需要时填 null；
- shape_contract 写任务形态需要的额外合同；
- minimum_viable_next_step 写任务启动后的第一步；
- working_scope 写当前任务绑定对象、路径、来源、排除范围和约束；
- acceptance 写验收方式、完成标准和最终回复要求。

不要填写 entry_reason。
不要提交内部 TaskRunContract、工具授权、模型配置、环境策略或 memory 规则。
无法写清任务目标、主执行契约、任务形态、第一步、范围或验收时，选择 ask_user。
需要先取得事实再判断是否启动任务时，选择 tool_call。
当前回合可以完成时，选择 respond。
```

这段引导必须作为 agent 可直接执行的行动说明，而不是写给开发者看的实现说明。

## 8. Runtime 承接链路

目标链路：

```text
provider strict request_task_run
-> TaskStartIntent v3
-> PrimaryModeContract normalizer
-> TodoToolContract normalizer
-> TaskShapeContract normalizer
-> canonical TaskRunContract
-> TaskRunResourceAllocator creates task_run_id and binds active turn
-> task_contract_manifest projects primary contract, todo tool and shape contract
-> task_mode_tail_context projects primary focus, todo cursor and shape focus
-> Current Task Attention Index
-> single_agent_turn receives task overlay and chooses normal action
-> normal tool execution or normal respond
-> TaskStatePatchExtractor updates plan, todo cursor, shape progress and acceptance
-> projection / monitor / closeout
```

硬性规则：

- runtime 不替 agent 选择 `primary_mode`。
- runtime 不把 `task_shape` 提升成 `primary_mode`。
- runtime 不把 `todo_tool_contract` 提升成 `primary_mode`。
- unsupported `task_shape` 必须显式报错。
- `open_work` 不能作为 unsupported mode 的自动 fallback。
- `recovery` 必须有恢复句柄或上一状态引用。
- `monitor` 在没有调度器前只能表示有边界观察任务。
- todo 完成状态不能替代 `acceptance`。

## 9. Current Task Attention Index

尾部注意力索引需要同时呈现主执行契约、任务形态和 todo 游标。

目标结构：

```json
{
  "current_task_attention_index": {
    "task_objective": "",
    "primary_mode": "goal|plan",
    "task_shape": "standard|investigation|recovery|monitor|open_work",
    "minimum_viable_next_step": "",
    "required_target_objects": [],
    "workspace_refs": [],
    "source_refs": [],
    "excluded_scope": [],
    "known_constraints": [],
    "goal_focus": {},
    "plan_focus": {},
    "todo_cursor": {
      "enabled": false,
      "todo_list_id": "",
      "active_item_id": "",
      "active_item": "",
      "pending_count": 0,
      "blocked_count": 0,
      "update_required": false
    },
    "shape_focus": {},
    "acceptance_focus": {},
    "agent_use_contract": "选择下一步前，先重新锚定当前 TaskRun 的主执行契约、任务形态、目标、范围、plan step、todo 游标和验收边界。"
  }
}
```

规则：

- `primary_mode` 和 `task_shape` 必须同时出现。
- `goal_focus / plan_focus` 来自主执行契约。
- `todo_cursor` 来自 `todo_tool_contract`，不是模式 focus。
- `shape_focus` 来自调查、恢复、监控或开放工作合同。
- todo 游标必须放在 volatile tail。
- 长计划的完整内容可以放中段上下文，尾部只放当前步骤和短指针。
- final answer 前必须能看到 acceptance focus。

## 10. 缓存边界

### 10.1 stable prefix

适合缓存：

- 全局角色；
- 项目固定规则；
- provider control action schema；
- 工具 schema；
- goal primary contract 定义；
- plan primary contract 定义；
- todo tool contract 定义；
- 任务形态契约定义。

### 10.2 request overlay

每轮变化：

- allowed action set；
- provider tool binding；
- 当前权限面；
- 当前工具可用性；
- 本轮 action permit。

### 10.3 volatile tail

不能进入 stable prefix：

- 当前 `task_run_id`；
- 当前 `primary_mode` 和 `task_shape`；
- 当前 todo cursor；
- 当前 active plan step；
- 当前 recovery handle；
- 最新 tool observations；
- pending user steer；
- acceptance focus。

## 11. 模块改造计划

### 11.1 control_action_schema.py

目标：

- provider schema 使用 `TaskStartIntent v3`。
- `primary_mode` enum 改为 `goal | plan`。
- 新增 `task_shape` enum：`standard | investigation | recovery | monitor | open_work`。
- 移除 agent-facing `entry_reason`。
- 新增 `primary_mode_contract`、`todo_tool_contract` 和 `shape_contract`。

完成标准：

- strict schema 中不再要求 `entry_reason`。
- provider schema 不暴露内部 `TaskRunContract`。
- 新任务不能提交 `primary_mode=todo`。

### 11.2 compiler.py / tool_call_contract.py

目标：

- 用第 7 节的中文 agent-facing 引导替换旧说明。
- 删除“入口理由”式表达。
- 把 `GoalContext / PlanContext / TodoContext` 改写为主执行契约和 todo 工具契约。
- attention index 同时呈现 `primary_mode`、`task_shape` 和 `todo_cursor`。

完成标准：

- prompt 不再把 `todo` 说成 primary mode。
- prompt 不再把 `investigation / recovery / monitor / open_work` 说成 primary mode。
- prompt 不再要求 agent 填 `entry_reason`。

### 11.3 model_action_protocol.py

目标：

- 归一化 `TaskStartIntent v3`。
- 验证 `primary_mode` 只能是 `goal / plan`。
- 验证 `task_shape` 是合法任务形态。
- 根据 `primary_mode` 规范化对应主契约。
- 规范化可选 `todo_tool_contract`。
- 根据 `task_shape` 规范化对应形态契约。
- 删除普通 agent-authored 路径上的旧 seed 猜模式逻辑。

完成标准：

- unsupported mode 或 shape 显式报错。
- 没有 silent fallback 到 `goal / plan / open_work`。
- `primary_mode=todo` 在新任务启动中被拒绝。

### 11.4 task_lifecycle.py

目标：

- 只消费 canonical `TaskRunContract` seed。
- 不再二次判断模式。
- `TaskRunContract` 同时保存 `primary_mode`、`task_shape`、`primary_mode_contract`、`todo_tool_contract`、`shape_contract`。
- display title 从 `task_objective` 和显式契约派生。

完成标准：

- lifecycle 层不能改变 `primary_mode` 或 `task_shape`。
- lifecycle 层不能把 todo 升级为主模式。

### 11.5 task_contract_manifest.py

目标：

- model-visible payload 明确输出：
  - `task_run_context`
  - `primary_mode_contract`
  - `goal_context`
  - `plan_context`
  - `todo_tool_context`
  - `shape_context`
  - `acceptance_contract`
- `shape_context` 根据 `task_shape` 输出 investigation/recovery/monitor/open_work 的专门上下文。

完成标准：

- 图任务和 agent runtime 都能从 manifest 读取同一套显式契约。
- todo context 被标注为执行工具上下文，而不是主模式上下文。

### 11.6 task_mode_tail_context.py

目标：

- 保留并强化 goal/plan tail context。
- 新增 todo cursor tail：
  - `task_todo_cursor`
- 新增 shape tail context：
  - `task_investigation_context`
  - `task_recovery_context`
  - `task_monitor_context`
  - `task_open_work_context`
- shape tail 不是任务模式 tail。
- todo tail 不是任务模式 tail。

完成标准：

- 当前任务尾部能同时提醒主执行契约、任务形态和 todo 游标。

### 11.7 task overlay / state patch / projector / run_monitor

目标：

- `single_agent_turn` 根据 task overlay 继续普通行动选择。
- `TaskStatePatchExtractor` 从普通 turn 的结构化动作、工具观察和最终回复中更新任务状态。
- task overlay 同时呈现 `primary_mode`、`task_shape`、todo cursor、active plan step 和 acceptance focus。
- run monitor 显示主模式、形态和 todo cursor。
- closeout 按形态输出对应收口：
  - investigation 输出发现、证据缺口、裁决；
  - recovery 输出恢复点、已恢复内容、未完成项和 todo cursor；
  - monitor 输出观察结果、触发状态、停止条件；
  - open_work 输出已稳定部分、仍开放部分、建议升级目标或计划。

完成标准：

- 普通 `TaskRun` 不调用独立 task model loop。
- 任务不会全部被扁平化为 goal/plan 文案。
- todo 完成状态不会被当作验收完成。

### 11.8 CLI / slash command

目标：

- CLI 支持显式主执行模式：`goal`、`plan`。
- CLI 可通过参数或 contract file 指定 `task_shape`。
- CLI 可通过参数或 contract file 挂载 `todo_tool_contract`。
- slash command 不应把 `todo`、`recovery`、`monitor` 当作主模式命令。

示例：

```powershell
python -m backend.cli task-run plan --shape investigation --todo "检查 schema;检查 prompt;验证 CLI" "调查任务系统启动失败原因"
python -m backend.cli task-run plan --shape recovery --todo-contract .\recovery-todo.json "从上次失败的任务恢复"
python -m backend.cli task-run plan --shape monitor "观察运行监控事件"
python -m backend.cli task-run goal --shape standard --todo "修正文档;复查残留" "完成任务系统升级计划书修正"
```

完成标准：

- CLI 的主命令体现主执行契约；
- shape 是主契约上的任务形态参数；
- todo 是附加执行工具参数。

### 11.9 图任务系统

相关文件：

- `backend/task_system/graphs/*`
- `backend/task_system/graph_instances/*`
- `backend/api/graph_system.py`
- `backend/api/graph_task_instances.py`

目标：

- 图节点可以声明 `primary_mode`。
- 图节点可以声明 `task_shape`。
- 图节点使用同一套 `goal_contract / plan_contract / todo_tool_contract / shape_contract`。
- 图边可以读取：
  - goal success；
  - plan step completion；
  - todo item status；
  - investigation decision gate；
  - monitor trigger；
  - recovery resume status。

完成标准：

- 图任务不再重新定义一套任务语义。
- 图任务和普通 `TaskRun` 使用同一套任务契约。
- todo item status 是执行状态输入，不是主任务模式。

## 12. 阶段计划

### Phase 1：修正任务分类与文档

目标：

- 锁定 `primary_mode = goal | plan`。
- 锁定 `todo = task execution tool / cursor contract`。
- 锁定 `task_shape = standard | investigation | recovery | monitor | open_work`。
- 中文设计书完成。

完成标准：

- 本文通过用户审阅。

### Phase 2：改造启动 schema 和 agent prompt

涉及文件：

- `control_action_schema.py`
- `compiler.py`
- `tool_call_contract.py`
- `single_agent_turn.py`

完成标准：

- provider schema 使用 `TaskStartIntent v3`。
- prompt 不再把 todo 或 task shape 当 primary mode。

### Phase 3：改造 action protocol 和 lifecycle

涉及文件：

- `model_action_protocol.py`
- `task_lifecycle.py`
- `admission.py`

完成标准：

- runtime 只校验与归一化，不再猜模式。
- `entry_reason` 不再是启动合同字段。
- todo 只作为执行工具契约进入任务。

### Phase 4：改造 manifest、tail context、attention index

涉及文件：

- `task_contract_manifest.py`
- `task_mode_tail_context.py`
- `dynamic_context/manager.py`
- `compiler.py`

完成标准：

- 主执行契约、todo 工具契约和形态契约都能进入模型可见上下文。

### Phase 5：改造 task overlay、state patch、monitor、closeout

涉及文件：

- `task_executor.py`
- `single_agent_turn.py`
- `task_state_patch.py`
- `task_state_projector.py`
- `run_monitor/projector.py`

完成标准：

- 普通任务执行回到 `single_agent_turn`。
- `task_executor.py` 不再作为普通 `TaskRun` 默认模型循环。
- 状态回写与收口同时尊重主执行契约、任务形态和 todo 游标。

### Phase 6：接入 CLI 和图任务

涉及文件：

- `backend/cli/main.py`
- `task_mode_slash_command.py`
- `task_system/graphs/*`
- `task_system/graph_instances/*`

完成标准：

- CLI 可以启动 goal/plan，并指定 task_shape。
- CLI 可以附加 todo 工具契约。
- 图任务可以复用显式任务契约。

## 13. 迁移规则

### 13.1 不保留 agent-facing 兼容字段

不允许在 provider schema 中同时接受：

```text
entry_reason
task_objective
```

原因：

这会让 agent 继续学习旧合同，导致 prompt 和 runtime 语义漂移。

### 13.2 新任务不接受 legacy todo mode

不允许新任务提交：

```text
primary_mode = todo
```

旧记录如果已经存在 todo mode，只允许作为历史显示或显式迁移输入读取。

禁止：

- 新任务写入 todo mode；
- 把 todo mode 自动转成 goal 或 plan；
- repair feedback 要求 agent 补齐 todo mode；
- 用 todo mode 决定任务形态。

历史迁移只能通过显式迁移逻辑完成，并且迁移结果必须是：

```text
primary_mode = goal | plan
todo_tool_contract = restored todo cursor
```

### 13.3 历史 entry_reason 只读

旧记录中可能存在 `container_contract.entry_reason`。

允许：

- 作为历史显示字段读取。

禁止：

- 新任务写入；
- 作为 task objective 使用；
- repair feedback 要求 agent 补齐；
- 用它决定模式或形态。

### 13.4 open_work 不得当 fallback

`open_work` 是任务形态，不是系统兜底。

只有 agent 明确选择 `task_shape=open_work`，并填写 `open_work` 形态契约时，runtime 才能接受。

## 14. 验证计划

项目规则：不新增回归测试文件，不伪造结果。

静态检查：

```powershell
rg -n "entry_reason|primary_mode.*todo|todo.*primary_mode|primary_mode.*investigation|primary_mode.*recovery|primary_mode.*monitor|primary_mode.*open_work|task-run todo|Todo Mode" backend/harness backend/cli backend/task_system
python -m compileall backend/harness/runtime backend/harness/loop backend/harness/entrypoint backend/cli backend/task_system
```

真实 CLI 验证：

```text
1. 固定后端端口 http://127.0.0.1:8003。
2. 若端口占用，先确认是否属于本项目旧进程。
3. 启动后端。
4. CLI 创建或选择 session。
5. 启动 plan + investigation 任务，并附加 todo_tool_contract。
6. 启动 plan + recovery 任务，并恢复 todo cursor。
7. 启动 plan + monitor 任务。
8. 启动 goal + standard 任务，并附加轻量 todo。
9. 查看 monitor 中 task_run_id、primary_mode、task_shape、task_objective、todo_cursor、tail focus、closeout。
```

验收不变量：

- `primary_mode` 只包含 `goal / plan`。
- `task_shape` 承载 `standard / investigation / recovery / monitor / open_work`。
- `todo_tool_contract` 承载 todo 清单、状态和游标。
- runtime 不替 agent 猜模式。
- task shape 不替代 primary contract。
- todo tool 不替代 primary contract。
- 图任务能复用同一套显式契约。
- todo cursor 放 volatile tail。
- provider stable schema 不因当前任务进度变化而失效。

## 15. 禁止事项

禁止：

- 把 `todo` 作为 `primary_mode` 或任务模式。
- 把 `investigation / recovery / monitor / open_work` 继续作为 `primary_mode`。
- 把 `goal / plan` 降级为普通字段。
- 保留 `entry_reason` 作为 agent-facing 启动字段。
- 让系统根据用户关键词启动任务。
- 用 `open_work` 兜底 unsupported mode。
- 在 lifecycle 层二次猜测模式。
- 为图任务重新发明一套任务合同。
- 用 prompt 堆叠掩盖 runtime 合同不一致。
- 改动无关前端脏文件。

## 16. 预期结果

实施后：

- `request_task_run` 成为清晰的控制动作信号。
- agent 显式选择 `goal` 或 `plan` 作为主执行契约。
- todo 成为显式执行工具契约，负责清单、状态和当前游标。
- `investigation / recovery / monitor / open_work` 作为任务形态由契约生成。
- runtime 接收的是机器可执行的任务合同，而不是启动理由。
- 普通 `TaskRun` 和图任务共用同一套契约。
- 当前任务注意力索引能同时提醒主执行契约、任务形态、目标、计划、todo 游标、恢复/调查/监控焦点和验收。
- 旧的七模式混层、todo-as-mode 和 `entry_reason` 合同污染被清理。

## 17. 审批门槛

本文涉及 runtime、prompt、provider tool/function calling schema、任务合同、状态投影、CLI 和图任务语义。按项目规则，实施前必须等待用户确认。

确认后应按阶段完整实施。若实施时发现本文分层假设不成立，必须暂停并重新说明偏差。
