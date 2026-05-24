# Vibe Coding 项目自有环境与能力移植计划

日期：2026-05-25

## 1. 技术源头清点

本项目已经具备支撑 vibe coding 的基础链路，但当前被旧禁用逻辑截断：

- `backend/capability_system/operation_registry.py` 已注册文件读写、目录/路径、全文搜索、git 只读、shell、浏览器、todo、委派等 coding agent 所需操作。
- `backend/runtime/tool_runtime/native_tools.py` 与 `backend/runtime/tool_runtime/tool_executor.py` 已承接这些操作的真实执行。
- `backend/permissions/runtime_policy_builder.py`、`backend/permissions/operation_gate.py`、`backend/runtime/execution_permit/permit_builder.py` 已提供权限与执行准入。
- `backend/prompt_library/default_resources.py` 和 `backend/prompt_library/registry.py` 已有 `vibe_coding` prompt 资源。
- `backend/agent_system/registry/worker_agent_factory.py` 已有 `worker.vibe_coding.executor`，但它引用的 `vibe_coding_task` lane 当前没有注册。
- `backend/orchestration/interaction_mode_policy.py` 定义了 `VIBE_CODING_MODE`，但没有加入可用模式集合，并且把 `vibe`、`coding`、`vibe_coding` 等别名降级到 `professional_mode`。
- `backend/agent_system/profiles/runtime_mode_config.py` 定义了 `VIBE_CODING_MODE`，但没有加入模式目录。
- `backend/agent_system/profiles/runtime_profile_registry.py` 在读取和迁移 profile 时过滤 `vibe_coding`，并把 `vibe_coding_task` 映射回 `professional_task`。
- `backend/task_system/planning/execution_recipe_builder.py` 只把 role/standard/professional 接入统一 interaction recipe，没有接入 `runtime.recipe.vibe_coding`。
- 旧测试 `backend/tests/interaction_mode_policy_regression.py` 与 `backend/tests/professional_mode_runtime_regression.py` 正在保护禁用行为。

Pi 环境当前只能作为辅助依赖：

- 已新增 `backend/vibe_coding/pi_environment.py`、`backend/vibe_coding/pi_rpc_process.py`、`backend/api/vibe_coding.py` 和前端诊断页面。
- 现状依赖环境变量或默认 `D:/AI应用/pi-main`，还不是项目配置所有。
- Pi CLI 构建产物可能不存在，因此不能作为本项目 vibe coding 能力的主入口。

## 2. 设计方向

本项目必须自己拥有 vibe coding 能力。Pi 只作为本地可选 sidecar / 环境诊断来源，不承接主平台、主编排、主记忆、主权限或主输出。

必须取用：

- 固定本地节点：前端 `127.0.0.1:3000`，后端 `127.0.0.1:8003`，前端 API Base `127.0.0.1:8003/api`。
- 项目自己的 `OperationRegistry -> OperationGate -> ToolRuntime -> Evidence/Closeout` 能力链。
- 项目自己的 `RuntimeInteractionModePolicy`、`RuntimeLaneRegistry`、`ExecutionRecipe`、`AgentRuntimeProfile`。
- 已存在的 main agent profile、vibe coding worker blueprint、prompt resource。
- Pi 的本地路径、Node/npm/RPC/CLI 可用性诊断，以及后续可选只读 sidecar 调用。

不取用：

- 不把 Pi 变成本项目主平台。
- 不整体搬 Pi 的 UI、任务系统、记忆系统、权限系统、工具注册表或 TUI。
- 不把 Pi prompt 原样当本项目 prompt。
- 不为了“兼容旧禁用逻辑”保留降级到 `professional_mode` 的隐藏分支。

## 3. 目标状态

完成本阶段后：

- `vibe_coding` 是可被显式选择和语义任务选择的 interaction/runtime mode。
- `vibe_coding_task` 是真实注册的 runtime lane。
- `runtime.recipe.vibe_coding` 进入统一 interaction-mode recipe，并沿用成熟的 professional driver 执行，但 mode/lane/tool policy/metadata 独立标识为 coding。
- main agent profile 允许 `vibe_coding` 模式和 `vibe_coding_task` lane。
- 旧存储 profile 被迁移为保留 vibe coding，而不是过滤或映射。
- Pi 环境配置归项目 `backend/config.json` 所有，默认 diagnostic-only，缺失 CLI 时只报告诊断，不阻塞项目自有 vibe coding mode。

## 4. 实施步骤

### 阶段一：接通运行模式

修改：

- `backend/orchestration/interaction_mode_policy.py`
- `backend/orchestration/runtime_lane_registry.py`
- `backend/task_system/planning/execution_recipe_builder.py`

要求：

- `INTERACTION_MODES` 加入 `vibe_coding`。
- `vibe`、`vibe_code`、`vibe_coding`、`coding`、`code`、`coder` 映射到 `vibe_coding`。
- 任务 profile 的 `material_policy.runtime_mode == "vibe_coding"` 返回 `vibe_coding`。
- 新增 `vibe_coding_task` lane，包含 list/stat/path/glob/search/read/write/edit/git/shell/browser/todo/delegate 等必要操作。
- `runtime.recipe.vibe_coding` 进入 interaction-mode recipe。
- vibe coding 的 tool policy 必须要求 evidence packet、change set metadata、strict verification、test or limitation。

完成标准：

- 显式 `interaction_mode=vibe_code` 输出 `interaction_mode=vibe_coding`、`runtime_lane=vibe_coding_task`、`recipe_id=runtime.recipe.vibe_coding`。
- 代码修复类语义任务可进入 `vibe_coding`。

### 阶段二：接通 profile 与模式目录

修改：

- `backend/agent_system/profiles/runtime_mode_config.py`
- `backend/agent_system/profiles/runtime_profile_registry.py`
- 必要时更新 `backend/task_system/storage/orchestration/agent_runtime_profiles.json`

要求：

- 模式目录新增 `vibe_coding`，位于 professional 与 custom 之间。
- 不再过滤 `vibe_coding`。
- 不再把 `vibe_coding_task` 映射成 `professional_task`。
- main agent profile 保留 `vibe_coding` 与 `vibe_coding_task`。

完成标准：

- mode catalog 暴露 vibe coding。
- profile list/save 后仍保留 `vibe_coding` 与 `vibe_coding_task`。

### 阶段三：项目所有的 Pi 环境配置

修改：

- `backend/config.py`
- `backend/config.json`
- `backend/vibe_coding/models.py`
- `backend/vibe_coding/pi_environment.py`

要求：

- 新增 `vibe_coding` 配置块，至少包含：
  - `enabled`
  - `pi_sidecar.enabled`
  - `pi_sidecar.mode`
  - `pi_sidecar.pi_source_root`
  - `pi_sidecar.pi_cli_path`
  - `workspace_root_policy`
- `pi_environment.py` 优先读取项目配置，再允许环境变量覆盖，最后使用默认路径。
- 响应体返回配置来源、sidecar 模式和项目权威信息。

完成标准：

- 没有 Pi CLI 时接口仍返回真实 diagnostic。
- 配置清楚表达 Pi 是 optional sidecar，不是主执行平台。

### 阶段四：测试更新

修改：

- `backend/tests/interaction_mode_policy_regression.py`
- `backend/tests/professional_mode_runtime_regression.py`
- 必要时新增/更新 runtime mode/profile 配置测试。

要求：

- 删除旧的“vibe coding alias falls back to professional mode”断言。
- 增加 `vibe_coding` mode、lane、recipe、tool policy、mode catalog、profile registry 的正向断言。
- 不绕过测试，不用伪结果应付验证。

### 阶段五：验证

至少执行：

- `python -m py_compile` 覆盖本次改动的后端文件。
- `python -m pytest backend/tests/interaction_mode_policy_regression.py backend/tests/professional_mode_runtime_regression.py backend/tests/orchestration_agent_management_regression.py backend/tests/soul_projection_interaction_mode_regression.py`
- `cd frontend && npx tsc --noEmit`

如果前端改动未触及业务逻辑，可不启动浏览器；如果后续改 UI 行为，必须用固定 `3000/8003` 节点验证。

## 5. 风险控制

- 本阶段不声称已经实现完整 change set、patch approval、workspace snapshot 内核；本阶段目标是让项目拥有真实可路由、可授权、可执行的 vibe coding mode/lane/config。
- 后续独立阶段再实现 coding session、change set receipt、diff approval、verification receipt 与前端 change set 管理。
- 如果 Pi 缺失或未构建，不能让 `vibe_coding` mode 失效；Pi 只影响 sidecar diagnostics。
