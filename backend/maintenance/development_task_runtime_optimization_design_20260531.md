# 开发任务 Runtime 与工具环境优化设计书

日期：2026-05-31

状态：已确认并开始实施。本文保留目标设计，同时记录本轮实施边界。

## 0. 执行结论

当前项目已经具备较好的 agent runtime 基础：`RuntimeAssembly`、`RuntimeCompiler`、任务环境、工具包、operation authorization、TaskRun 合同、事件日志和恢复记录都已经存在。现在开发任务的主要问题不是“缺一个工具”，而是开发任务链路还没有形成足够稳定的专业执行协议。

目标是把开发任务升级为接近 Codex / Claude Code 的工作方式：

```text
用户请求
-> 主 agent 语义判断：直接回答 / 提问 / 开任务 / 继续任务 / 先回答再继续
-> TaskRun 合同：目标、范围、产物、验证、权限、恢复策略
-> 开发环境绑定：sandbox / readonly / frontend / game / verification
-> 工具包装配：代码智能、文件读写、Git、执行、浏览器、生图
-> 工具门控：每次调用按 operation + 环境 + 合同裁决
-> 执行循环：定位、局部读取、编辑、验证、观察失败、恢复
-> 最终回复：真实改动、真实验证、真实限制
```

本设计不建议继续靠硬编码关键词决定是否进入任务，也不建议只靠 prompt 解决所有行为问题。正确方向是：

```text
模型负责语义决策。
系统负责资源、权限、装配和记录。
prompt 负责告诉模型如何在当前边界内专业工作。
测试负责证明模型能看到正确上下文并真实调用正确工具。
```

## 1. 当前源码依据

### 1.1 任务环境

相关文件：

```text
backend/task_system/environments/default_environments.py
backend/task_system/environments/models.py
backend/task_system/environments/catalog.py
backend/task_system/environments/registry.py
```

当前已有环境：

```text
env.development.sandbox
env.development.readonly
env.creation.writing
env.research.web
env.document.processing
env.general.workspace
```

开发环境已经表达了资源边界：

```text
development.sandbox:
  真实项目作为读取来源
  写入、命令、浏览器和交付物受 sandbox overlay 与任务授权约束
  环境不直接授予工具，只声明资源边界

development.readonly:
  只允许读取、搜索、审查、方案评估
  不允许写入、shell、浏览器
```

已新增的 Python AST 使用约束也已经位于环境 prompt 中：

```text
python_symbol_search
python_code_outline
python_parse_check
```

### 1.2 工具包与工具注册

相关文件：

```text
backend/capability_system/tool_packages.py
backend/capability_system/tool_definitions.py
backend/capability_system/operation_registry.py
backend/permissions/resource_scope_mapping.py
backend/capability_system/units/tools/python_ast_tools.py
```

当前 `pkg.development.python` 已经具备合理边界：

```text
包含：
  op.codebase_search
  op.python_code_outline
  op.python_symbol_search
  op.python_parse_check
  op.git_status
  op.git_diff
  op.git_log
  op.git_show
  op.git_branch_list

不包含：
  op.read_file
  op.write_file
  op.edit_file
  op.shell
  op.python_repl
  op.browser_control
```

这个设计是正确的。开发工具包应该表达“开发专用智能和诊断”，通用文件读写和执行能力由独立包授权。

### 1.3 runtime 装配

相关文件：

```text
backend/harness/runtime/assembly.py
backend/harness/runtime/compiler.py
backend/prompt_library/assembly.py
backend/prompt_library/registry.py
backend/prompt_library/packs.py
```

当前链路：

```text
assemble_runtime()
-> build_runtime_assembly_profile()
-> resolve task environment
-> project_operation_authorization()
-> build_authorized_tool_set()
-> collect agent_prompt_refs / environment_prompt_refs
-> RuntimeCompiler.compile_turn_action_packet()
-> RuntimeCompiler.compile_task_execution_packet()
```

关键点：

```text
agent prompt、environment prompt、tool catalog、operation authorization 都会进入 runtime packet。
环境 prompt 只有在 environment_prompt_refs 被正确装配时才会进入模型上下文。
```

### 1.4 runtime mode 与默认环境

相关文件：

```text
backend/agent_system/profiles/runtime_mode_config.py
backend/harness/runtime/assembly.py
```

重要风险：

```text
_default_environment_id_for_mode() 默认返回 env.general.workspace。
runtime mode config 当前没有把 professional / standard 自动绑定到 development sandbox。
```

这意味着：开发环境 prompt 写得再好，如果开发任务没有显式选择 `env.development.sandbox` 或 `env.development.readonly`，模型仍可能只看到通用环境。

这不是 prompt 问题，而是任务合同和 runtime selection 的绑定问题。

### 1.5 TaskRun 合同与模型选择绑定

相关文件：

```text
backend/harness/loop/task_lifecycle.py
backend/harness/loop/model_action_runtime.py
backend/runtime/shared/resume_decision.py
```

当前 TaskRun 合同具备：

```text
user_visible_goal
task_run_goal
required_artifacts
required_verifications
completion_criteria
resource_requirements
permission_requirements
task_environment_id
runtime_profile
prompt_contract
```

这是正确的合同承载层。开发任务的环境、工具包、验证要求、prompt contract 都应该最终落到这里，而不是散落在 UI、关键词判断或临时参数里。

## 2. 真实问题定义

### 2.1 不是单个 prompt 不够好

开发任务表现不自然、反复读代码、忘记验证、断点后自顾自继续，这些现象背后是同一类问题：

```text
开发任务缺少稳定的专业执行协议。
```

具体表现：

```text
1. 任务环境不一定稳定绑定到 development sandbox / readonly。
2. 开发工具包有了，但模型不一定被清晰训练成优先使用代码智能工具。
3. 环境 prompt 负责资源边界，但缺少按任务类型装配的开发执行策略 prompt。
4. 断点恢复事实、用户当前输入、任务合同修订之间还需要更明确地区分。
5. 最终回复缺少强制的开发交付闭环。
6. 监控能记录工具调用，但缺少开发任务质量诊断指标。
```

### 2.2 正确终态

正确终态不是“每次都自动进任务”，也不是“永远先回答不做任务”，而是：

```text
每个 turn 都由模型基于上下文自由判断下一步。
系统给模型足够清晰的当前事实、活动任务、断点、工具和权限。
模型必须回复用户，或者回复后继续任务；不能只控制内部任务而忽视用户。
进入开发任务后，执行链路自然使用代码智能、局部编辑和验证。
```

## 3. 目标架构

### 3.1 权责链

目标链路固定为：

```text
RequestFacts
-> BoundaryPolicy
-> ContextCandidates
-> ModelTurnDecision
-> TaskContract
-> RuntimeAssembly
-> RuntimeInvocationPacket
-> ModelActionRequest
-> AdmissionDecision
-> ToolExecution
-> ObservationLedger
-> FollowupPacket
-> CompletionReview
-> UserVisibleAnswer
```

各层职责：

```text
RequestFacts:
  只记录用户说了什么、当前是否有 active task、是否有断点。

BoundaryPolicy:
  只决定模式边界、角色模式限制、安全边界，不替模型决定任务语义。

ContextCandidates:
  提供候选上下文、活动任务、断点摘要、工具目录、权限投影。

ModelTurnDecision:
  由模型决定回答、提问、开任务、继续任务、先回答再继续或阻塞。

TaskContract:
  承载开发任务目标、环境、产物、验证、权限、恢复策略。

RuntimeAssembly:
  只做装配，不做语义重写。

AdmissionDecision:
  每次工具调用独立门控，不信任 prompt 授权。

ObservationLedger:
  记录真实工具结果和失败，不让模型伪造状态。

UserVisibleAnswer:
  必须对用户当前输入有自然回应，并报告真实工作状态。
```

### 3.2 开发任务环境分层

建议明确四类开发环境或环境 profile：

```text
env.development.readonly
  用于审查、定位、方案、解释。
  禁止写入、shell、浏览器。

env.development.sandbox
  用于普通代码修改、配置修改、测试验证。
  写入和执行受 sandbox / task grant 控制。

env.development.frontend
  可作为 sandbox 的 specialization。
  强调固定端口、浏览器验证、截图/Playwright、响应式检查。

env.development.asset_game
  可作为 sandbox 的 specialization。
  强调可玩交付、生图资源、资源路径、浏览器运行验证。
```

第一阶段可以不新增物理环境，只通过 task_goal_type + prompt refs 做 specialization。后续如果前端和游戏任务越来越多，再拆成独立 environment definition。

### 3.3 开发执行策略 prompt

环境 prompt 只写资源边界，不应承担所有开发方法论。需要新增一个独立的开发任务执行策略 prompt。

建议 prompt id：

```text
strategy.development.execution.v1
strategy.development.frontend_delivery.v1
strategy.development.game_delivery.v1
strategy.development.verification.v1
```

示例正文风格：

```text
你是一名开发执行 agent。
你负责把用户要求落实为真实代码、配置、资源或验证结果。
你必须先定位相关代码，再做最小必要编辑。
你不能用计划、报告或设计文档冒充实现。
如果知道符号名但不知道文件，优先使用符号搜索。
如果知道文件但不了解结构，优先查看代码 outline。
修改 Python 后先做语法检查，再运行更重的测试。
修改前端后必须启动或检查对应页面，并用浏览器验证关键交互。
工具失败时，你要基于失败观察修正路径、参数或策略，不能重复同一个失败。
最终回复必须说明真实修改、真实验证和剩余风险。
```

注意：prompt 要写给 agent 执行，不要写成：

```text
这是开发策略节点，用于约束开发任务。
```

### 3.4 开发工具默认使用链

成熟开发任务的默认链应为：

```text
定位：
  python_symbol_search / python_code_outline / codebase_search / search_text

读取：
  read_file 只读取必要局部，不反复整文件阅读

修改：
  edit_file 优先用于精确修改
  write_file 用于新文件或整体生成

低成本验证：
  python_parse_check
  git_diff

重验证：
  pytest / npm test / build / browser verification

交付：
  final answer with changed files, verification, limitations
```

工具使用反模式：

```text
反复读同一个文件但不形成假设。
明明知道符号名却全仓扫读。
修改后直接总结，不做 parse/test/diff。
工具失败后重复同样参数。
readonly 环境声称已经完成修改。
用 shell 代替现有专用工具。
```

### 3.5 开发主页面

开发主页面应该挂在现有 workbench / task-system 结构内，而不是重造一个孤立壳。

建议页面骨架：

```text
左侧栏
  文件树
  文件搜索
  最近打开
  固定文件

中间主区
  开发任务对话口
  当前任务状态
  自然语言计划片段
  重要工具观察摘要

右侧栏
  文件查看器
  diff 视图
  图片预览
  快速定位到行号
  验证输出

底部或折叠区
  计划
  验证
  Git 状态
  运行日志
```

交互原则：

```text
1. 对话是主线，文件树和文件查看是辅助。
2. 选中文件后可以在中心区打开文件页，不必离开工作台。
3. 文件页应支持只读查看与受控编辑两种状态。
4. 对话里提到路径、符号、diff、验证结果时，应该能直接跳转。
5. 页面风格应简洁、密度高、偏 Codex 工具台，不做营销式布局。
```

建议复用现有前端结构：

```text
frontend/src/components/layout/WorkbenchShell.tsx
frontend/src/components/workspace/views/task-system/TaskSystemShell.tsx
frontend/src/components/workspace/views/task-system/TaskSystemWorkbenchUi.tsx
frontend/src/components/chat/ChatPanel.tsx
frontend/src/components/editor/InspectorPanel.tsx
```

如果需要单独的开发主页面，优先新增一个 workspace view，而不是让首页 page.tsx 继续承载所有工作台逻辑。

## 4. 推荐实施方案

### Phase 1：稳定开发任务环境绑定

目标：

```text
开发任务必须稳定进入正确 task environment。
```

改动范围：

```text
backend/task_system/goal_profiles/task_goal_profiles.py
backend/task_system/goal_profiles/goal_profile_binding.py
backend/task_system/planning/execution_shape_resolver.py
backend/task_system/engagement/contract_issuer.py
backend/harness/loop/task_lifecycle.py
backend/tests
```

设计决策：

```text
inspection / code_review -> env.development.readonly
implementation / code_fix_execution / frontend_app_delivery / game_vertical_slice_delivery -> env.development.sandbox
verification -> env.development.sandbox 或 readonly，取决于是否需要命令执行
role_conversation -> 不允许绑定开发任务环境
```

完成标准：

```text
TaskRunContract.task_environment_id 对开发任务不为空。
compile_task_execution_packet 中 stable_prompt_refs 包含对应 environment prompt。
角色模式不会因为历史 active task 自动进入开发环境。
```

验证：

```text
新增测试：开发修复任务合同默认绑定 env.development.sandbox。
新增测试：只读审查任务绑定 env.development.readonly。
新增测试：角色模式问题不进入 TaskRun，也不装配 development environment。
```

### Phase 2：新增开发执行策略 prompt

目标：

```text
把开发方法论从环境 prompt 中拆出来，按任务类型装配。
```

改动范围：

```text
backend/prompt_library/packs.py
backend/prompt_library/registry.py
backend/harness/runtime/compiler.py
backend/task_system/goal_profiles/task_goal_profiles.py
backend/tests/prompt_library_runtime_pack_test.py
```

设计决策：

```text
environment prompt:
  只写资源边界、权限边界、sandbox 语义。

development strategy prompt:
  写开发执行方法、工具使用顺序、验证闭环、失败恢复。

task prompt contract:
  写本任务具体目标、产物、验收标准。
```

完成标准：

```text
开发 TaskRun packet 同时包含 runtime task prompt、agent role prompt、environment prompt、development strategy prompt。
非开发任务不装配 development strategy prompt。
```

验证：

```text
新增 prompt manifest 断言。
新增 packet content 断言：开发策略进入 `model_messages`，但 stable payload 只保留 prompt ref。
```

### Phase 3：开发工具选择诊断

目标：

```text
让系统能解释“为什么 agent 一直读代码”。
```

新增诊断指标：

```text
code_intelligence_used_before_large_read
repeated_same_file_read_count
repeated_same_tool_failure_count
python_edit_without_parse_check
workspace_edit_without_diff
frontend_edit_without_browser_or_build_verification
readonly_claimed_write_completion
```

改动范围：

```text
backend/runtime/memory/tool_observation_ledger.py
backend/runtime/shared/tool_repetition_guard.py
backend/harness/runtime/monitor_projection.py
backend/health_system/governance.py
backend/tests/tool_repetition_guard_regression.py
```

完成标准：

```text
任务事件日志能显示工具使用质量。
健康检查能指出低效探索、缺失验证、重复失败。
```

### Phase 4：断点恢复与当前用户输入分离

目标：

```text
断点事实提供给模型，但是否继续由模型决定。
```

模型可见恢复包：

```text
active_task_summary
last_checkpoint
last_tool_observation
completed_steps
remaining_contract
new_user_message
allowed_next_actions:
  respond
  ask_user
  continue_task
  answer_then_continue_task
  revise_task_contract
  block
```

改动范围：

```text
backend/runtime/shared/resume_decision.py
backend/harness/loop/task_checkout.py
backend/harness/loop/task_steering.py
backend/harness/runtime/compiler.py
backend/tests/system_eval/long_task_natural_language_control_experiment.py
```

设计决策：

```text
resume_decision 只能描述恢复候选，不能替模型决定本轮继续。
当前用户输入必须作为当前 turn input，不得降级成弱 resume_context。
模型输出必须包含用户可见回应，或者明确 answer_then_continue_task。
```

完成标准：

```text
断点后用户问问题时，agent 会先自然回答。
断点后用户说继续时，agent 可继续任务。
断点后用户改变目标时，agent 可请求合同修订。
```

### Phase 5：开发任务端到端实验

目标：

```text
证明 agent 不靠显式指令也会自然使用开发工具。
```

实验集：

```text
1. Python 小 bug：
   期望链路：symbol/outline -> read_file -> edit_file -> python_parse_check -> test/diff -> final

2. 只读代码审查：
   期望链路：search/outline -> read evidence -> findings
   禁止：write/edit/shell

3. 前端 UI 修复：
   期望链路：inspect -> edit -> run fixed 3000/8003 -> browser verification -> final

4. 游戏垂直切片：
   期望链路：implement playable loop -> image_generate if required -> asset path verification -> browser verification

5. 断点恢复：
   期望链路：模型看到断点和用户新输入，自主选择 answer / continue / answer_then_continue
```

改动范围：

```text
backend/tests/system_eval
backend/tests/python_ast_tool_runtime_experiment.py
backend/tests/prompt_library_runtime_pack_test.py
backend/tests/runtime_profile_tool_package_regression.py
```

## 5. 文件级执行清单

### 环境与合同

```text
backend/task_system/environments/default_environments.py
  收窄环境 prompt：保留资源边界，把开发方法迁移到 strategy prompt。

backend/task_system/goal_profiles/task_goal_profiles.py
  为开发 goal profile 增加默认 environment / strategy prompt metadata。

backend/task_system/goal_profiles/goal_profile_binding.py
  把 task_goal_type 绑定到默认环境和默认策略 prompt。

backend/harness/loop/task_lifecycle.py
  确保 TaskRunContract.task_environment_id 和 prompt_contract 能承载开发策略。

frontend/src/components/layout/WorkbenchShell.tsx
  复用现有工作台壳，不重造页面框架。

frontend/src/components/workspace/views/task-system/TaskSystemShell.tsx
  作为 task-system 页面布局参考，沿用对象导航和内容区分层。

frontend/src/components/workspace/views/task-system/TaskSystemWorkbenchUi.tsx
  作为任务系统工作台风格参考，提炼成开发任务主页面布局。

frontend/src/components/chat/ChatPanel.tsx
  作为开发任务对话主视图的交互基底。

frontend/src/components/editor/InspectorPanel.tsx
  用于文件查看、只读浏览和受控编辑。
```

### prompt 装配

```text
backend/prompt_library/packs.py
  新增 development strategy prompt resources。

backend/prompt_library/registry.py
  确认 strategy prompt 可作为 task_execution prompt refs 装配。

backend/harness/runtime/compiler.py
  根据 task contract / goal profile 装配 strategy prompt refs。
```

### 工具与权限

```text
backend/capability_system/tool_packages.py
  保持 pkg.development.python 只放开发专用诊断工具。

backend/capability_system/tool_definitions.py
  优化 AST 工具 descriptions，让模型理解使用时机。

backend/permissions/resource_scope_mapping.py
  保持 AST 工具 operation 映射和门控。

backend/runtime/tool_runtime/tool_executor.py
  确认 tool admission 失败会形成可恢复 observation。
```

### 监控与诊断

```text
backend/runtime/shared/tool_repetition_guard.py
  增加开发任务重复读取、重复失败、缺失验证诊断。

backend/runtime/memory/tool_observation_ledger.py
  记录工具调用质量标签。

backend/harness/runtime/monitor_projection.py
  前端可展示开发任务质量状态。

backend/health_system/governance.py
  把缺失验证、重复失败、readonly 越界声明提升为 health risk。
```

### 测试

```text
backend/tests/prompt_library_runtime_pack_test.py
  验证 development strategy prompt 装配。

backend/tests/task_environment_registry_regression.py
  验证开发环境可解析。

backend/tests/runtime_profile_tool_package_regression.py
  验证开发工具包、默认工具包、blocked operations 合并正确。

backend/tests/python_ast_tool_runtime_experiment.py
  验证 AST 工具真实可调用。

backend/tests/system_eval/*
  增加端到端开发任务实验。
```

## 6. 验证矩阵

```text
开发修复任务：
  必须进入 env.development.sandbox。
  必须看到 development strategy prompt。
  修改 Python 后必须至少 parse check 或说明不能验证。

只读审查任务：
  必须进入 env.development.readonly。
  不得暴露 write/edit/shell。
  最终只能给诊断和建议。

角色模式：
  不得因 active task 自动进入任务。
  不得装配开发任务上下文。
  可以自然回答用户。

断点恢复：
  恢复事实可见。
  当前用户输入可见。
  继续与否由模型输出决定。

前端任务：
  固定端口 3000 / 8003。
  必须真实启动或说明无法启动。
  UI 改动后必须浏览器验证。

游戏任务：
  不能只交设计文档。
  需要 playable artifact。
  需要真实图片路径或明确生图失败原因。
```

## 7. 迁移与切换规则

### 7.1 旧逻辑保留边界

允许短期保留：

```text
现有 environment prompt。
现有 tool package。
现有 TaskRunContract 字段。
现有 prompt pack。
```

不允许继续扩大：

```text
关键词硬编码决定是否进任务。
resume 层替模型决定继续任务。
环境 prompt 承担所有开发执行策略。
工具包混入通用读写和 shell。
测试只验证注册表，不验证 runtime packet 和真实工具调用。
```

### 7.2 切换顺序

```text
先绑定开发 task_goal_type -> environment。
再新增 strategy prompt。
再增加 runtime packet 装配测试。
再增加工具使用质量监控。
最后做端到端系统实验。
```

不要先改 UI，也不要先扩工具。否则前端会展示更多状态，但底层决策仍然不稳定。

## 8. 风险与控制

### 风险 1：prompt 过长导致模型忽略重点

控制：

```text
环境 prompt 只保留资源边界。
开发策略 prompt 保持短而强。
任务合同只写本任务具体要求。
```

### 风险 2：系统再次用硬编码替模型决策

控制：

```text
系统只能提供 allowed_next_actions。
模型必须输出 action_type。
测试覆盖：用户问问题时不能只继续任务。
```

### 风险 3：工具有权限但模型不用

控制：

```text
tool description 写清使用时机。
strategy prompt 写清默认链路。
监控标记低效探索。
端到端实验验证自然选择工具。
```

### 风险 4：开发环境绑定过度

控制：

```text
role_conversation、light_qa 不绑定 development environment。
inspection 默认 readonly。
真正修改才 sandbox。
```

### 风险 5：验证成本过高

控制：

```text
先低成本验证：parse check、git diff。
再按任务需要运行测试、build、浏览器。
不能验证时必须说明限制。
```

## 9. 最终建议

本轮优化应以“三件事”为主线：

```text
1. 开发任务稳定绑定开发环境。
2. 开发执行策略 prompt 独立装配。
3. 用端到端实验验证 agent 自然选择正确开发工具。
```

这三件事完成后，再做前端 UI 的开发任务体验优化才有意义。否则 UI 只是展示了更多状态，不能解决 agent 是否真正像成熟 coding agent 一样工作的核心问题。
