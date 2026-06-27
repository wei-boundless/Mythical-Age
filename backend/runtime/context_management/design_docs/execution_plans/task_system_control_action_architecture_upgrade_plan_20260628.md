# 任务系统控制动作架构升级设计书

## 0. 文档状态

本文是任务系统控制动作与任务契约模型的架构升级设计书。

状态：等待用户审阅后再实施。

本文替代此前围绕 `request_task_run`、`entry_reason` 和七类 `primary_mode` 的临时草案。当前代码尚未按本文修改。

本次关键修正：

- `request_task_run` 名称保留。
- `request_task_run` 是 agent 发出的“启动持续任务生命周期”的控制信号。
- 系统不根据用户自然语言猜测是否应该启动任务。
- provider strict tool/function calling 用作控制动作 schema 的承载层。
- `entry_reason` 退出 agent-facing 启动合同。
- agent-facing 启动合同使用 `task_objective` 表达任务目标。
- `goal / plan / todo` 是任务模式，因为它们是 agent 可以显式建立并执行的任务契约。
- `investigation / recovery / monitor / open_work` 不是与 `goal / plan / todo` 同级的任务模式，而是通过填写显式任务契约形成的任务形态。
- 图任务以后应复用这些显式任务契约，而不是重新写一套隐式任务语义。

## 1. 核心定义

### 1.1 TaskRun

`TaskRun` 是持续任务生命周期容器。

它负责绑定：

- 任务身份；
- 任务目标；
- 显式任务模式契约；
- 任务形态契约；
- 执行状态；
- 进度投影；
- 暂停、恢复、停止和失败收口；
- 验收与最终回复要求。

`TaskRun` 不是 agent 的普通工具调用结果，也不是系统根据用户文字生成的语义标签。

### 1.2 任务模式 Task Mode

任务模式是 agent 可以显式建立的执行契约。

当前任务模式只包括：

```text
goal
plan
todo
```

原因：

- `goal` 建立目标契约，明确要达成什么、成功定义是什么、哪些证据可以证明完成。
- `plan` 建立计划契约，明确按哪些步骤推进、如何变更计划、何时重规划。
- `todo` 建立执行清单契约，明确当前事项、执行游标、完成状态和更新规则。

它们不是普通字段，也不是低一层的附属材料。它们之所以叫任务模式，正是因为 agent 可以选择建立这些契约，并在这些契约下执行任务。

### 1.3 任务形态 Task Shape

任务形态是由任务模式契约组合出来的工作场景。

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

- `investigation`：由目标、计划、证据范围和调查裁决合同形成。
- `recovery`：由恢复句柄、旧状态、恢复边界和目标/计划/todo 合同形成。
- `monitor`：由观察对象、触发条件、检查点和停止规则形成。
- `open_work`：由最小目标、当前边界、下一步和后续升级条件形成。

任务形态不能替代任务模式。即使是 `recovery`，也必须说明恢复后是在目标模式、计划模式还是 todo 模式下继续执行。

## 2. 当前问题

### 2.1 七类 `primary_mode` 混成同一层

当前代码把下面七个值放进同一个任务启动枚举：

```text
goal | plan | todo | investigation | recovery | monitor | open_work
```

证据：

- `backend/harness/runtime/control_action_schema.py:19`
- `backend/harness/loop/model_action_protocol.py:570`

问题在于：

- `goal / plan / todo` 是 agent 可显式建立的任务模式契约。
- `investigation / recovery / monitor / open_work` 是通过契约组合得到的任务形态。
- 二者不应该共用 `primary_mode`。

这会导致 agent 误以为“调查”“恢复”“监控”本身就是主执行契约，而不再明确建立目标、计划或 todo。

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
- 用哪个显式任务模式承载；
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

agent 才能决定本次任务以哪个显式任务模式执行。runtime 可以校验、归一化和拒绝，但不能在启动路径里补猜模式。

### 2.4 模型可见上下文只真实承接了三类契约

当前 manifest 和 tail context 主要承接：

- `goal_context`
- `plan_context`
- `todo_context`

证据：

- `backend/harness/runtime/task_contract_manifest.py:151`
- `backend/harness/runtime/dynamic_context/task_mode_tail_context.py:17`
- `backend/harness/runtime/compiler.py:6981`
- `backend/harness/runtime/compiler.py:4217`

这说明 `goal / plan / todo` 确实已经是系统里真实存在的执行契约层。正确方向不是把它们降级，而是把它们正式命名为任务模式，并让调查、恢复、监控、开放工作通过形态契约挂到这些模式上。

## 3. 目标模型

### 3.1 启动合同分层

`request_task_run` 提交的是紧凑 `TaskStartIntent`。

`TaskStartIntent` 包含两层选择：

```text
primary_mode: goal | plan | todo
task_shape: standard | investigation | recovery | monitor | open_work
```

含义：

- `primary_mode` 表示 agent 要显式建立哪一种主任务模式契约。
- `task_shape` 表示这次任务属于哪一种工作形态。

示例：

```text
调查 bug 根因：
primary_mode = plan
task_shape = investigation

恢复失败任务：
primary_mode = todo 或 plan
task_shape = recovery

持续观察日志：
primary_mode = plan
task_shape = monitor

目标明确但无需复杂计划：
primary_mode = goal
task_shape = standard
```

### 3.2 任务模式与任务形态的关系

```text
TaskRun
├─ primary_mode: goal | plan | todo
├─ mode_contracts
│  ├─ goal_contract
│  ├─ plan_contract
│  └─ todo_contract
└─ task_shape
   ├─ standard
   ├─ investigation_contract
   ├─ recovery_contract
   ├─ monitor_contract
   └─ open_work_contract
```

规则：

- 每个 TaskRun 必须有一个 `primary_mode`。
- `primary_mode` 只能是 `goal / plan / todo`。
- `task_shape` 默认是 `standard`。
- 非 standard 形态必须填写对应形态契约。
- 形态契约不能替代模式契约。
- 图任务节点以后可以直接引用这些模式契约和形态契约。

## 4. TaskStartIntent v3

agent-facing `request_task_run` 参数：

```json
{
  "public_progress_note": "向用户说明正在开启一条持续任务线",
  "public_action_state": {
    "visible_status": "thinking",
    "current_judgment": "当前目标需要持续任务生命周期",
    "next_action": "提交 request_task_run",
    "evidence_refs": [],
    "open_risks": [],
    "completion_status": "working"
  },
  "task_objective": "这条任务线最终要完成的具体目标",
  "primary_mode": "goal|plan|todo",
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
  "mode_contracts": {
    "goal": {},
    "plan": {},
    "todo": {}
  },
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
- `mode_contracts`
- `shape_contract`

公开反馈字段：

- `public_progress_note`
- `public_action_state`

公开反馈用于用户可见状态和动作一致性，不参与系统判断是否应该启动任务。

## 5. 显式任务模式契约

### 5.1 Goal Mode Contract

用途：

Goal Mode 用来建立目标型任务。agent 明确知道要达成什么，并能给出成功定义。

契约：

```json
{
  "mode_kind": "goal",
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
- 如果目标太大，需要同时建立 Plan Mode 作为 supporting mode。
- 如果执行中目标变化，必须通过 replan 或任务控制显式说明。

图任务用途：

- 图节点可以把 `goal_contract` 作为节点任务目标。
- 图边可以读取 `success_definition` 和 `completion_evidence` 判断是否进入下一节点。

### 5.2 Plan Mode Contract

用途：

Plan Mode 用来建立步骤型任务。agent 需要按计划推进、更新步骤、记录偏差，并在必要时重规划。

契约：

```json
{
  "mode_kind": "plan",
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

- Plan Mode 的核心是“按步骤推进”，不是把目标写成一段说明。
- 计划很长时，完整计划进入稳定上下文，当前步骤进入尾部注意力索引。
- 偏离计划必须解释偏离原因或更新计划。
- 计划不是 todo cursor；todo 是执行清单，plan 是策略结构。

图任务用途：

- 图任务可以把 `major_steps` 编译成子节点、阶段或边条件。
- 图运行器可以用 `active_step_id` 和 `done_when` 做进度投影。

### 5.3 Todo Mode Contract

用途：

Todo Mode 用来建立执行清单型任务。agent 需要维护当前事项、完成状态和执行游标。

契约：

```json
{
  "mode_kind": "todo",
  "todo_contract": {
    "todo_list_id": "todo:stable-id",
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

- Todo Mode 的核心是“执行游标和状态更新”。
- 进度变化时必须更新 todo。
- todo 不替代 plan；todo 可以来自 plan，也可以单独作为轻量执行契约。
- 完成 todo 不等于任务验收完成，最终仍看 acceptance。

图任务用途：

- 图任务可以把 todo item 编译成可恢复的执行单元。
- 图运行器可以用 `active_item_id` 保存恢复位置。

## 6. 任务形态契约

任务形态不是 `primary_mode`。它们是通过填写形态契约，让 Goal/Plan/Todo Mode 进入某种具体工作场景。

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
- 普通 todo 执行任务。

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

模式组合建议：

- `primary_mode=plan`：适合多步调查。
- supporting `todo`：适合跟踪调查项。
- supporting `goal`：适合固定最终要回答的问题。

图任务用途：

- 图节点可用 `decision_gate.allowed_outcomes` 决定下一条边。
- `evidence_targets` 可转成节点输入资源。

### 6.3 Recovery Task Shape

用途：

恢复型任务。它不是“恢复模式”，而是带恢复合同的任务形态。恢复后仍必须在 Goal/Plan/Todo Mode 中继续执行。

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

模式组合建议：

- `primary_mode=todo`：适合从中断清单继续。
- `primary_mode=plan`：适合从中断阶段继续。
- supporting `goal`：用于保留原目标。

图任务用途：

- 图运行器可用 `previous_state_ref` 和 `next_resume_step` 恢复节点。
- `unfinished_work` 可转成新的 todo items。

### 6.4 Monitor Task Shape

用途：

监控型任务。当前阶段仅表示有边界的 TaskRun 内观察任务；除非后续实现真实调度器，否则不能暗示无限期后台监控。

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

模式组合建议：

- `primary_mode=plan`：适合按观察步骤推进。
- supporting `todo`：适合记录检查项。
- supporting `goal`：适合说明监控的最终判断目标。

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
    "stabilization_target": "需要逐步稳定成明确 goal、plan 或 todo 的对象",
    "known_boundary": "当前已知边界",
    "known_unknowns": [],
    "minimum_progress_unit": "最小可交付进展",
    "promotion_policy": {
      "promote_to_goal_when": "",
      "promote_to_plan_when": "",
      "promote_to_todo_when": ""
    },
    "review_checkpoint": "何时要求用户或系统重新确认形态"
  }
}
```

模式组合建议：

- `primary_mode=goal`：适合目标可写但范围仍开放。
- `primary_mode=plan`：适合先用探索计划推进。
- 不允许没有显式任务模式就进入 open_work。

图任务用途：

- 图任务可把 open_work 用作前置澄清节点。
- 达到 `promotion_policy` 后必须转换为明确目标、计划或 todo 节点。

## 7. Agent-facing 启动引导

目标文案：

```text
你正在为本轮选择唯一行动。

选择 request_task_run，表示你要开启一条新的持续任务线。
这条任务线必须建立一个显式任务模式契约：goal、plan 或 todo。

先选择 primary_mode：
- goal：你要建立目标契约，按成功定义推进；
- plan：你要建立计划契约，按步骤推进并允许重规划；
- todo：你要建立执行清单契约，按事项和游标推进。

再选择 task_shape：
- standard：普通任务；
- investigation：查明未知问题；
- recovery：从失败、暂停或中断状态恢复；
- monitor：在有边界的观察窗口内监控目标；
- open_work：目标或范围尚未完全稳定，但确需持续任务生命周期。

task_shape 不能替代 primary_mode。
即使是 recovery、monitor 或 investigation，也必须说明恢复、监控或调查是在 goal、plan 还是 todo 契约下执行。

填写 TaskStartIntent 时：
- task_objective 写任务最终要完成什么；
- primary_mode 写主任务模式，只能是 goal、plan 或 todo；
- task_shape 写任务形态；
- mode_contracts 写显式任务模式契约；
- shape_contract 写任务形态需要的额外合同；
- minimum_viable_next_step 写任务启动后的第一步；
- working_scope 写当前任务绑定对象、路径、来源、排除范围和约束；
- acceptance 写验收方式、完成标准和最终回复要求。

不要填写 entry_reason。
不要提交内部 TaskRunContract、工具授权、模型配置、环境策略或 memory 规则。
无法写清任务目标、任务模式、任务形态、第一步、范围或验收时，选择 ask_user。
需要先取得事实再判断是否启动任务时，选择 tool_call。
当前回合可以完成时，选择 respond。
```

## 8. Runtime 承接链路

目标链路：

```text
provider strict request_task_run
-> TaskStartIntent v3
-> TaskModeContract normalizer
-> TaskShapeContract normalizer
-> canonical TaskRunContract
-> task lifecycle creates task_run_id
-> task_contract_manifest projects mode_contracts and shape_contract
-> task_mode_tail_context projects current mode focus and shape focus
-> Current Task Attention Index
-> executor acts under primary_mode and task_shape
-> projection / monitor / closeout
```

硬性规则：

- runtime 不替 agent 选择 `primary_mode`。
- runtime 不把 `task_shape` 提升成 `primary_mode`。
- unsupported `task_shape` 必须显式报错。
- `open_work` 不能作为 unsupported mode 的自动 fallback。
- `recovery` 必须有恢复句柄或上一状态引用。
- `monitor` 在没有调度器前只能表示有边界观察任务。

## 9. Current Task Attention Index

尾部注意力索引需要同时呈现任务模式和任务形态。

目标结构：

```json
{
  "current_task_attention_index": {
    "task_objective": "",
    "primary_mode": "goal|plan|todo",
    "task_shape": "standard|investigation|recovery|monitor|open_work",
    "minimum_viable_next_step": "",
    "required_target_objects": [],
    "workspace_refs": [],
    "source_refs": [],
    "excluded_scope": [],
    "known_constraints": [],
    "goal_focus": {},
    "plan_focus": {},
    "todo_focus": {},
    "shape_focus": {},
    "acceptance_focus": {},
    "agent_use_contract": "选择下一步前，先重新锚定当前 TaskRun 的任务模式、任务形态、目标、范围、todo/plan 游标和验收边界。"
  }
}
```

规则：

- `primary_mode` 和 `task_shape` 必须同时出现。
- `goal_focus / plan_focus / todo_focus` 来自显式模式契约。
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
- 任务模式契约定义；
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
- `primary_mode` enum 改为 `goal | plan | todo`。
- 新增 `task_shape` enum：`standard | investigation | recovery | monitor | open_work`。
- 移除 agent-facing `entry_reason`。
- 新增 `mode_contracts` 和 `shape_contract`。

完成标准：

- strict schema 中不再要求 `entry_reason`。
- provider schema 不暴露内部 TaskRunContract。

### 11.2 compiler.py / tool_call_contract.py

目标：

- 用第 7 节的中文 agent-facing 引导替换旧说明。
- 删除“入口理由”式表达。
- 把 `GoalContext / PlanContext / TodoContext` 改写为显式任务模式契约。
- attention index 同时呈现 `primary_mode` 和 `task_shape`。

完成标准：

- prompt 不再把 `investigation / recovery / monitor / open_work` 说成 primary mode。
- prompt 不再要求 agent 填 `entry_reason`。

### 11.3 model_action_protocol.py

目标：

- 归一化 TaskStartIntent v3。
- 验证 `primary_mode` 只能是 `goal / plan / todo`。
- 验证 `task_shape` 是合法任务形态。
- 根据 `primary_mode` 规范化对应模式契约。
- 根据 `task_shape` 规范化对应形态契约。
- 删除普通 agent-authored 路径上的旧 seed 猜模式逻辑。

完成标准：

- unsupported mode 或 shape 显式报错。
- 没有 silent fallback 到 `goal / plan / open_work`。

### 11.4 task_lifecycle.py

目标：

- 只消费 canonical TaskRunContract seed。
- 不再二次判断模式。
- `TaskRunContract` 同时保存 `primary_mode`、`task_shape`、`mode_contracts`、`shape_contract`。
- display title 从 `task_objective` 和显式契约派生。

完成标准：

- lifecycle 层不能改变 primary mode 或 task shape。

### 11.5 task_contract_manifest.py

目标：

- model-visible payload 明确输出：
  - `task_run_context`
  - `mode_contracts`
  - `goal_context`
  - `plan_context`
  - `todo_context`
  - `shape_context`
  - `acceptance_contract`
- `shape_context` 根据 `task_shape` 输出 investigation/recovery/monitor/open_work 的专门上下文。

完成标准：

- 图任务和 agent runtime 都能从 manifest 读取同一套显式契约。

### 11.6 task_mode_tail_context.py

目标：

- 保留并强化 goal/plan/todo tail context。
- 新增 shape tail context：
  - `task_investigation_context`
  - `task_recovery_context`
  - `task_monitor_context`
  - `task_open_work_context`
- 这些不是任务模式 tail，而是形态 focus。

完成标准：

- 当前任务尾部能同时提醒任务模式和任务形态。

### 11.7 task_executor.py / projector / run_monitor

目标：

- executor 根据 `primary_mode` 执行显式契约。
- executor 根据 `task_shape` 调整工作语义。
- run monitor 显示模式和形态。
- closeout 按形态输出对应收口：
  - investigation 输出发现、证据缺口、裁决；
  - recovery 输出恢复点、已恢复内容、未完成项；
  - monitor 输出观察结果、触发状态、停止条件；
  - open_work 输出已稳定部分、仍开放部分、建议升级模式。

完成标准：

- 任务不会全部被扁平化为 goal/plan 文案。

### 11.8 CLI / slash command

目标：

- CLI 支持显式任务模式：`goal`、`plan`、`todo`。
- CLI 可通过参数或 contract file 指定 `task_shape`。
- slash command 不应把 `recovery`、`monitor` 当作主模式命令。

示例：

```powershell
python -m backend.cli task-run plan --shape investigation "调查任务系统启动失败原因"
python -m backend.cli task-run todo --shape recovery "从上次失败的任务恢复"
python -m backend.cli task-run plan --shape monitor "观察运行监控事件"
```

完成标准：

- CLI 的主命令体现任务模式；
- shape 是模式上的任务形态参数。

### 11.9 图任务系统

相关文件：

- `backend/task_system/graphs/*`
- `backend/task_system/graph_instances/*`
- `backend/api/graph_system.py`
- `backend/api/graph_task_instances.py`

目标：

- 图节点可以声明 `primary_mode`。
- 图节点可以声明 `task_shape`。
- 图节点使用同一套 `goal_contract / plan_contract / todo_contract / shape_contract`。
- 图边可以读取：
  - goal success；
  - plan step completion；
  - todo item status；
  - investigation decision gate；
  - monitor trigger；
  - recovery resume status。

完成标准：

- 图任务不再重新定义一套任务语义。
- 图任务和普通 TaskRun 使用同一套任务契约。

## 12. 阶段计划

### Phase 1：修正任务分类与文档

目标：

- 锁定 `primary_mode = goal | plan | todo`。
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

- provider schema 使用 TaskStartIntent v3。
- prompt 不再把 task shape 当 primary mode。

### Phase 3：改造 action protocol 和 lifecycle

涉及文件：

- `model_action_protocol.py`
- `task_lifecycle.py`
- `admission.py`

完成标准：

- runtime 只校验与归一化，不再猜模式。
- `entry_reason` 不再是启动合同字段。

### Phase 4：改造 manifest、tail context、attention index

涉及文件：

- `task_contract_manifest.py`
- `task_mode_tail_context.py`
- `dynamic_context/manager.py`
- `compiler.py`

完成标准：

- 显式模式契约和形态契约都能进入模型可见上下文。

### Phase 5：改造 executor、monitor、closeout

涉及文件：

- `task_executor.py`
- `task_state_projector.py`
- `run_monitor/projector.py`

完成标准：

- 执行与收口同时尊重任务模式和任务形态。

### Phase 6：接入 CLI 和图任务

涉及文件：

- `backend/cli/main.py`
- `task_mode_slash_command.py`
- `task_system/graphs/*`
- `task_system/graph_instances/*`

完成标准：

- CLI 可以启动 goal/plan/todo，并指定 task_shape。
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

### 13.2 历史数据只读

旧记录中可能存在 `container_contract.entry_reason`。

允许：

- 作为历史显示字段读取。

禁止：

- 新任务写入；
- 作为 task objective 使用；
- repair feedback 要求 agent 补齐；
- 用它决定模式或形态。

### 13.3 open_work 不得当 fallback

`open_work` 是任务形态，不是系统兜底。

只有 agent 明确选择 `task_shape=open_work`，并填写 `open_work` 形态契约时，runtime 才能接受。

## 14. 验证计划

项目规则：不新增回归测试文件，不伪造结果。

静态检查：

```powershell
rg -n "entry_reason|primary_mode.*investigation|primary_mode.*recovery|primary_mode.*monitor|primary_mode.*open_work" backend/harness backend/cli backend/task_system
python -m compileall backend/harness/runtime backend/harness/loop backend/harness/entrypoint backend/cli backend/task_system
```

真实 CLI 验证：

```text
1. 固定后端端口 http://127.0.0.1:8003。
2. 若端口占用，先确认是否属于本项目旧进程。
3. 启动后端。
4. CLI 创建或选择 session。
5. 启动 plan + investigation 任务。
6. 启动 todo + recovery 任务。
7. 启动 plan + monitor 任务。
8. 查看 monitor 中 task_run_id、primary_mode、task_shape、task_objective、tail focus、closeout。
```

验收不变量：

- `primary_mode` 只包含 `goal / plan / todo`。
- `task_shape` 承载 `standard / investigation / recovery / monitor / open_work`。
- runtime 不替 agent 猜模式。
- task shape 不替代 mode contract。
- 图任务能复用同一套显式契约。
- todo cursor 仍然放 volatile tail。
- provider stable schema 不因当前任务进度变化而失效。

## 15. 禁止事项

禁止：

- 把 `investigation / recovery / monitor / open_work` 继续作为 `primary_mode`。
- 把 `goal / plan / todo` 降级为普通字段。
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
- agent 显式建立 `goal / plan / todo` 任务模式契约。
- `investigation / recovery / monitor / open_work` 作为任务形态由契约生成。
- runtime 接收的是机器可执行的任务合同，而不是启动理由。
- 普通 TaskRun 和图任务共用同一套契约。
- 当前任务注意力索引能同时提醒任务模式、任务形态、目标、计划、todo、恢复/调查/监控焦点和验收。
- 旧的七模式混层和 `entry_reason` 合同污染被清理。

## 17. 审批门槛

本文涉及 runtime、prompt、provider tool/function calling schema、任务合同、状态投影、CLI 和图任务语义。按项目规则，实施前必须等待用户确认。

确认后应按阶段完整实施。若实施时发现本文分层假设不成立，必须暂停并重新说明偏差。
