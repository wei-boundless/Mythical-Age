# DeepSearch 重构与子 Agent 能力接入计划书

日期：2026-06-02

## 1. 技术源报告

### 1.1 当前问题

当前能力系统已经有 `DeepSearchCapability` 和 `CodebaseSearchCapability`，但它们没有通过 harness 的子 Agent 主链路形成稳定执行入口。`spawn_subagent` 能创建子 `TaskRun` / `AgentRun`，后台也会调用 `execute_task_run`，但 `execute_task_run` 目前仍默认进入模型循环，没有先根据子 Agent 的 `AgentRuntimeProfile.metadata.runtime_config.runtime_kind` 路由到能力本体。

这导致两个问题：

1. 能力存在，但子 Agent 执行入口不够明确。
2. DeepSearch 内部仍混有本地文件、RAG、memory 等重复 provider，和现有 `codebase_search_agent`、`knowledge_search_agent`、`memory_search_agent` 的权责重叠。

### 1.2 本地代码依据

项目内当前关键链路如下：

- `backend/harness/agent_control/controller.py`
  - `spawn_subagent` 创建子 `AgentRun` 和子 `TaskRun`。
  - `_append_child_task_run` 通过 `execute_task_run_callback` 后台执行子任务。
  - `wait` / `_child_result_payload` 只读取 `AgentRun.result_ref` 和 `AgentRunResult`。
- `backend/harness/entrypoint/runtime_facade.py`
  - `_resolve_task_run_runtime_profile` 已经能根据子 `TaskRun.agent_profile_id` 解析 `AgentRuntimeProfile`。
- `backend/harness/loop/task_executor.py`
  - `execute_task_run` 负责 lease、lifecycle、runtime assembly、模型循环、结果落账。
  - 当前缺少 profile 专家运行时路由。
  - 预检发现 `_record_task_step_summary` 函数体被后续 helper 打断，能编译但不能完整记录步骤摘要，执行前必须修复。
- `backend/agent_system/profiles/runtime_profile_registry.py`
  - `agent:web_researcher` 已声明 `runtime_config.runtime_kind = "search_agent"`。
  - `agent:codebase_searcher` 已声明 `runtime_config.runtime_kind = "codebase_search_agent"`。
- `backend/capability_system/capabilities/deepsearch`
  - DeepSearch 能力本体已存在，但 `providers.py` 仍包含 local files、RAG、memory provider。
- `backend/capability_system/capabilities/codebase_search`
  - Codebase Search 能力本体已存在，定位为只读本地代码搜索能力。

### 1.3 Codex 源码参考

本地 Codex 源码位于 `D:\AI应用\openai-codex`。关键参考：

- `codex-rs/core/src/tools/handlers/multi_agents_v2/spawn.rs`
  - `spawn_agent` 通过 `agent_control.spawn_agent_with_metadata` 创建独立子 Agent。
  - 子 Agent 有自己的 config、role、thread/source metadata。
- `codex-rs/core/src/tools/handlers/multi_agents_v2/wait.rs`
  - `wait_agent` 订阅 mailbox 变化，只等待和返回状态，不负责决定子 Agent 能力。
- `codex-rs/core/src/tools/orchestrator.rs`
  - tool 执行统一经过 approval、sandbox、retry 语义。
- `codex-rs/core/src/tools/registry.rs` 与 `router.rs`
  - registry/router 是 turn 级工具能力表，不把能力绑定到任务实例本身。

对本项目的结论：成熟实现不是把 `TaskRun` 变成 capability binding 表，而是保留 profile / router 的决策权。主 Agent 可同时 spawn 多个子 Agent，runtime 并发调度这些子执行实例，结果通过 mailbox/result_ref 回到父链路。

## 2. 目标权责链

目标链路固定为：

```text
主 Agent 语义决策
-> spawn_subagent 创建子执行实例
-> 子 TaskRun/AgentRun 只承载生命周期和结果引用
-> execute_task_run 解析 AgentRuntimeProfile
-> SpecialistRuntimeRouter 根据 runtime_kind 路由
-> capability_system 内能力本体执行
-> task_executor 记录 AgentRunResult/result_ref/lifecycle
-> wait_subagent 读取结果投回父 Agent
```

权责约束：

1. `TaskRun` 不拥有 capability 绑定权，只能保存执行实例、状态和诊断。
2. `AgentRuntimeProfile` / `runtime_kind` 是专家运行时选择的权威来源。
3. `harness` 只路由、调度、落账和回收，不承载能力算法。
4. `capability_system` 保留能力本体，禁止迁移到 runtime 目录。
5. DeepSearch 只负责外部 web 研究和 URL fetch，不再内嵌 local files、RAG、memory provider。
6. Codebase Search 保留为独立本地代码检索能力。
7. 并发多个 Agent 由父 Agent 通过多次 `spawn_subagent` 发起，harness 后台调度多个子执行实例；不做隐式自动 fan-out。

## 3. 目标执行流

### 3.1 单个专家子 Agent

```text
spawn_subagent(target_agent_id="agent:web_researcher")
-> child TaskRun(agent_profile_id="web_research_agent", execution_runtime_kind="subagent_task")
-> execute_task_run(child_task_run_id)
-> resolve profile
-> runtime_kind == "search_agent"
-> DeepSearchCapability.run(...)
-> AgentRunResult + result_ref
-> wait_subagent(...) 返回 summary/evidence/artifact refs
```

### 3.2 多个专家并发

```text
主 Agent:
  spawn_subagent(agent:web_researcher)
  spawn_subagent(agent:codebase_searcher)
  spawn_subagent(agent:verifier)

harness:
  每个 child TaskRun 独立执行
  每个 child profile 独立路由到自己的 runtime/capability
  wait_subagent/list_subagents 聚合状态和结果
```

该模式和 Codex 的 `spawn_agent` / `wait_agent` 相同：主 Agent 负责拆分，runtime 负责并发执行和结果邮箱。

## 4. 实施计划

### 阶段 0：修复执行器预检问题

目标：

- 修复 `backend/harness/loop/task_executor.py` 中 `_record_task_step_summary` 函数体被 helper 打断的问题。
- 保证后续能力执行的 step summary、public action state、latest diagnostics 能正常落账。

完成标准：

- `_record_task_step_summary` 完整记录事件并更新 `TaskRun.diagnostics`。
- `_drop_empty` 等模型诊断 helper 保持独立。
- `python -m py_compile backend/harness/loop/task_executor.py` 通过。

### 阶段 1：新增 SpecialistRuntimeRouter

新增文件：

- `backend/harness/loop/specialist_runtime_router.py`

职责：

- 从 `AgentRuntimeProfile.metadata.runtime_config` 读取 `runtime_kind`。
- 支持：
  - `search_agent` -> `DeepSearchCapability`
  - `codebase_search_agent` -> `CodebaseSearchCapability`
- 组装能力请求对象：
  - `request_id`
  - `task_run_id`
  - `session_id`
  - `source_agent_id`
  - `target_agent_id`
  - `instruction`
  - `input_payload`
  - `diagnostics`
- 返回结构化执行结果，不直接写 `TaskRun`、`AgentRun` 或 event log。

不允许：

- 不在 router 内保存全局状态。
- 不向 `TaskRun` 写入 capability binding。
- 不迁移能力实现到 harness/runtime。
- 不保留旧兼容 fallback。

### 阶段 2：接入 `execute_task_run`

修改文件：

- `backend/harness/loop/task_executor.py`

接入点：

- `execute_task_run` 完成 profile 解析、runtime assembly、executor claim、`agent_run` 创建之后。
- 在进入 `_execute_claimed_task_run` 模型循环之前，调用 `SpecialistRuntimeRouter.try_run(...)`。

行为：

- 若 router 不支持该 `runtime_kind`，继续原模型循环。
- 若 router 支持，则直接执行能力，并用现有 lifecycle/result 账本完成：
  - `runtime_objects.put_object("agent_run_result", ...)`
  - `AgentRun.result_ref`
  - `AgentRunResult`
  - `finish_task_lifecycle`
  - `step_summary_recorded`
  - `work_rollout`
- 能力失败时记录明确 terminal reason 和 limitations，不制造假成功。

### 阶段 3：DeepSearch 内部瘦身

修改文件：

- `backend/capability_system/capabilities/deepsearch/models.py`
- `backend/capability_system/capabilities/deepsearch/providers.py`
- `backend/capability_system/capabilities/deepsearch/runtime.py`
- `backend/tests/search_specialist_split_regression.py`

目标：

- 移除 DeepSearch 内部 local files、RAG、memory provider。
- DeepSearch 保留 web search + fetch + evidence distillation + evidence packet。
- 如果配置传入非 web source，返回 `deepsearch_unsupported_source`，不静默降级到 web，也不借用其他能力。
- `required_operations_for_search_config` 只表达 DeepSearch web 所需操作。

原因：

- 本地代码检索已经由 `CodebaseSearchCapability` 承担。
- RAG/knowledge 已有 `knowledge_search_agent`。
- memory 已有 `memory_search_agent`。
- DeepSearch 继续持有这些 provider 会造成能力边界重复。

### 阶段 4：测试与回归

新增或更新测试：

- `backend/tests/specialist_runtime_router_regression.py`
  - `search_agent` profile 路由到 DeepSearch。
  - `codebase_search_agent` profile 路由到 Codebase Search。
  - 未知 `runtime_kind` 不拦截普通模型循环。
  - router 不读写 `TaskRun` capability binding。
- `backend/tests/search_specialist_split_regression.py`
  - DeepSearch web-only。
  - 非 web source 明确失败。
- `backend/tests/subagent_control_regression.py`
  - 保持 spawn/wait 生命周期。
  - 至少覆盖一个能力子 Agent 结果可以被 `wait_subagent` 投影。

验证命令：

```powershell
python -m py_compile backend/capability_system/capabilities/deepsearch/*.py backend/capability_system/capabilities/codebase_search/*.py backend/harness/loop/specialist_runtime_router.py backend/harness/loop/task_executor.py
python -m pytest backend/tests/search_specialist_split_regression.py backend/tests/codebase_search_capability_regression.py backend/tests/subagent_control_regression.py backend/tests/specialist_runtime_router_regression.py -q
rg -n "capability.*task_run|task_run.*capability|runtime\\.template\\.deepsearch|runtime_kind.*search_agent" backend -g "*.py"
rg -n "LocalFilesSearchProvider|RAGSearchProvider|MemorySearchProvider|allow_local_files|allow_memory_read|units[/\\\\]tools|legacy|compat|fallback_result|NOISE_TERMS" backend/capability_system/capabilities/deepsearch backend/capability_system/capabilities/codebase_search -g "*.py"
```

## 5. 执行前自审

### 5.1 是否和用户约束冲突

- 不绑定 `TaskRun`：无冲突。能力选择来自 profile runtime_kind。
- 不搬能力到 runtime：无冲突。能力仍在 `capability_system`。
- 不沿用 Soul 系统：无冲突。本计划不使用 `SoulImageAssetService`。
- 不保留旧兼容层：无冲突。DeepSearch 重复 provider 将删除。
- 不做前端：无冲突。全部为后端 CLI 级变更。

### 5.2 是否和 Codex 模型冲突

无冲突。Codex 的多 Agent 是 spawn/wait/mailbox 模式，router/registry 负责能力暴露，具体执行实例只记录状态与结果。本计划照这个方向实现。

### 5.3 是否遗漏并发多 Agent

未遗漏。当前计划不做“自动 fan-out”，但保留并强化父 Agent 多次 `spawn_subagent` 后后台并发执行的能力。后续如需更高阶批量调度，应新增批量 spawn 工具或规划器策略，而不是把并发能力塞进 `TaskRun`。

### 5.4 当前可执行结论

可以执行。唯一预检问题是 `_record_task_step_summary` 现有结构损坏，已列入阶段 0；这不是架构矛盾，而是实施前必须修复的局部问题。
