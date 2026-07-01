# 全局工具面收束与清理计划

状态：已确认，实施中  
日期：2026-07-01  
范围：全部 agent-visible native tools、operation packages、runtime profile 授权、skill/tool guidance、任务环境和生成态工具注册表

## 1. 用户裁决

用户明确要求整理的是所有工具，不只是项目网络工具：

```text
工具真有点多了。
所有工具都要整理。
有引用的也可以删。
```

因此本计划不以“保兼容”为目标，而以“减少 agent 可见工具心智负担、删除不好用或过碎工具、把引用改到新权威入口”为目标。

硬规则：

- 不因为已有引用就保留旧工具。
- 删除工具时必须同步删除或改写引用，不留旧入口影子链路。
- 工具少而强，内部 operation 可以细，但 agent-visible 工具不能碎成一堆命令。
- profile、skill、prompt、task environment、frontend registry 必须跟随新工具面一起改线。

## 2. 当前工具问题

当前 native tool catalog 已经达到 49 个工具。

主要噪声来源：

| 问题 | 例子 | 判断 |
| --- | --- | --- |
| 同一能力拆得过碎 | `list_dir / stat_path / path_exists / glob_paths / search_files / search_text / read_file` | 应合并成 workspace read/search 少量工具 |
| lifecycle 拆成多个按钮 | `spawn_subagent / send_subagent_message / wait_subagent / list_subagents / close_subagent` | 应合并成一个 subagent action tool |
| git 工具过多 | `git_status / git_diff / git_log / git_show / git_stage / git_commit ...` | 应合并成 git read/write 或单 git action tool |
| AST 小工具过碎 | `python_code_outline / python_parse_check / python_symbol_search` | parse check 可删除；outline/symbol search 可合并 |
| 新项目网络工具过碎 | `project_structure_read_node / read_edge / expand / directory_relations ...` | 应合并成少量网络管理工具 |
| 专用能力默认暴露过多 | `image_generate / mcp_* / browser_control / office_document` | 应变成按 skill/profile 显式启用 |
| 内部工具混在 agent 工具面 | `text_metric / read_persisted_tool_result / python_repl` | 应内部化或挂到统一工具，不作为独立 agent 工具 |

## 3. 目标工具面

### 3.0 工具层统一管理原则

本轮清理暴露出的根因不是单个旧工具名，而是工具权威分散：catalog、operation package、runtime adapter、prompt guidance、skill registry、公共投影和前端分类都曾各自维护工具认知，导致旧入口会在不同层重新出现。

目标架构必须改成：

```text
native_tool_catalog
  -> tool_surface 派生 agent-visible 工具面、action-operation 映射、公共标签、模型契约摘要
  -> authorization / runtime adapter / prompt guidance / skill registry / frontend projection 只消费派生结果
```

边界裁决：

- `native_tool_catalog.py` 是 agent-visible tool 的唯一登记权威。
- `operation_packages.py` 只管理权限包，不决定工具长什么样。
- `runtime/tool_runtime` 只执行 catalog 中登记的工具和 action，不保留旧工具入口分发表。
- prompt、skill、公共流和前端不得维护旧工具清单；需要展示、分类、契约摘要时从 `capability_system.tools.tool_surface` 派生。
- 旧 helper 可以作为内部实现保留，但不得出现在 catalog、prompt、skill、registry、公共投影或模型可见契约里。

### 3.1 Agent 常态可见工具

目标常态工具控制在 8 个以内：

| 新工具 | 取代旧工具 | 默认可见 | 说明 |
| --- | --- | --- | --- |
| `workspace_search` | `search_files`, `search_text`, `glob_paths`, `python_symbol_search` 的常态定位部分 | 是 | 路径、文本、glob、符号定位统一入口；输出 locator/read windows |
| `workspace_read` | `read_file`, `list_dir`, `stat_path`, `path_exists`, `read_persisted_tool_result` | 是 | 读取文件、目录、元信息、存在性和持久化工具输出 |
| `workspace_edit` | `write_file`, `edit_file`, `batch_edit_file` | 按任务 | 创建和精确编辑文件；batch 作为 action |
| `code_structure` | `python_code_outline`, `python_symbol_search`, `python_parse_check` | coding profile | AST/结构读取；parse check 并入 diagnostics action |
| `git` | 全部 `git_*` | coding profile | `action=status|diff|log|show|branch|stage|unstage|commit|restore|push` |
| `agent_state` | `agent_todo` | 是 | 任务步骤和可见执行状态 |
| `subagent` | 5 个 subagent lifecycle 工具 | 仅允许子 agent 的 profile | `action=spawn|send|wait|list|close` |
| `project_network` | 项目结构网络全部工具 | 项目网络 profile | `action=build_skeleton|read_node|read_edge|expand|directory_relations|collect_changes|repair_items|submit_overlay` |

### 3.2 专用工具

这些工具不进入默认工具面，只由 skill、任务环境或专用 profile 显式启用：

| 工具 | 处理 |
| --- | --- |
| `web` | 合并 `web_search` + `fetch_url`，用于实时/外部信息任务 |
| `browser` | 保留一项，替代 `browser_control` 名称，默认不启用 |
| `image` | 保留一项，替代 `image_generate` 名称，默认不启用 |
| `office_document` | 保留一项，继续作为文档处理专用工具 |
| `local_mcp` | 不作为普通 model-visible 工具；MCP 走 capability endpoint / skill route |
| `memory` | 保留 `memory_search`，后续 memory write 仍走 commit gate |
| `local_execution` | 合并 `terminal`，删除独立 `python_repl` model tool；脚本由 shell/python command 执行 |

### 3.2.1 Skill 与工具指引边界

Skill 只保留真正的任务角色、复杂方法论或可复用工作流，例如工程化 Debug、能力创建顾问、专门审查角色等。只是在教 agent 怎么调用某个工具、怎么填参数、怎么停止重试、怎么组织工具返回结果的内容，不再作为模型可见 Skill 存在。

归属规则：

| 内容类型 | 归属 |
| --- | --- |
| 工具参数、默认值、action 选择、失败重试、证据边界 | `prompt_library/tool_prompts.py` 的 tool guidance |
| 工具名、action-operation 映射、公共标签、契约摘要 | `capability_system/tools/native_tool_catalog.py` 与 `tool_surface.py` |
| 本地 MCP 能力的路由、资源类型、规范化输出 | `capability_system/mcp/local_registry.py` |
| 长程研究、审查、调试、创作审核等角色化工作流 | Skill |

因此以下旧 Skill 不再保留为模型可见能力：

```text
browser-operation
web-search-briefing
deep-web-research
image-prompt-design
visual-asset-generation
pdf-analysis
rag-skill
structured-data-analysis
```

其中：

- 浏览器操作原则进入 `tool.guidance.browser`。
- 快速/深度网络搜索原则进入 `tool.guidance.web_fetch`。
- 生图 prompt、参数和重试规则进入 `tool.guidance.image`。
- PDF、表格、OCR 与文档处理边界进入 `tool.guidance.office_document` 或本地 MCP 能力注册。
- 知识库检索、PDF 阅读和结构化数据分析作为本地能力单元保留，不通过旧 Skill 名路由。

### 3.3 直接删除的工具入口

这些旧工具入口实施时直接从 `native_tool_catalog.py` 删除，并同步删/改引用：

```text
list_dir
stat_path
path_exists
glob_paths
search_files
search_text
read_file
read_persisted_tool_result
python_code_outline
python_parse_check
python_symbol_search
git_status
git_diff
git_log
git_show
git_branch_list
git_branch_create
git_stage
git_unstage
git_commit
git_restore
git_push
write_file
edit_file
batch_edit_file
spawn_subagent
send_subagent_message
wait_subagent
list_subagents
close_subagent
web_search
fetch_url
browser_control
image_generate
attachment_extract_text
text_metric
terminal
python_repl
project_structure_build_skeleton
project_structure_read_node
project_structure_read_edge
project_structure_expand
project_structure_directory_relations
project_structure_collect_git_changes
project_structure_create_repair_work_items
project_structure_submit_semantic_overlay
```

说明：

- 删除的是 agent-visible tool entry，不一定删除底层服务代码。
- 对底层服务仍有价值的能力，改由新统一工具 action 调用。
- `text_metric` 改为内部 Python service，不再是 agent 工具。
- `attachment_extract_text` 改由 `local_mcp` 或文档/附件 pipeline 调度，不再是独立工具。

## 4. Operation 层设计

工具入口减少，但 operation 仍需要精确表达权限。

目标：

```text
agent-visible tool = 少量统一 action tool
operation = 权限、风险、审批、任务环境控制的真实最小边界
```

因此不要把所有权限粗暴合并成一个 operation。

建议 operation 分层：

| 新工具 | operation 策略 |
| --- | --- |
| `workspace_search` | `op.workspace_search` |
| `workspace_read` | `op.workspace_read` |
| `workspace_edit` | `op.workspace_write`, `op.workspace_edit` |
| `code_structure` | `op.code_structure_read` |
| `git` | `op.git_read`, `op.git_write`, `op.git_remote` |
| `subagent` | 保留 `op.subagent_spawn/message/wait/list/close` 或合并为 `op.subagent_lifecycle`，由 action gate 二次校验 |
| `project_network` | `op.project_network_read`, `op.project_network_build`, `op.project_network_maintenance`, `op.project_network_semantic_submit` |
| `web` | `op.web_search`, `op.fetch_url` 可保留为 operation，但 tool 合并为 `web` |
| `browser` | `op.browser_control` |
| `image` | `op.image_generate` |
| `office_document` | `op.office_document` |
| `local_execution` | `op.shell` |

裁决：

- 工具名可以合并，operation 不必全部合并。
- Runtime permission 继续按 operation gate 控制。
- Tool action 必须映射到 operation，禁止一个 action 绕过对应 operation。

## 5. 工具包重构

删除当前碎包和重复包，重建包：

| 新 package | 默认 | operations |
| --- | --- | --- |
| `pkg.workspace.read` | 是 | `op.workspace_search`, `op.workspace_read`, `op.code_structure_read` |
| `pkg.workspace.write` | 按 coding profile | `op.workspace_write`, `op.workspace_edit` |
| `pkg.git` | coding profile | `op.git_read`, `op.git_write`；remote 单独审批 |
| `pkg.agent.control` | 主 agent / coordinator | `op.agent_todo`, subagent operations |
| `pkg.project_network` | 只给项目网络 profile | project network operations |
| `pkg.web` | 按任务 | web operations |
| `pkg.browser` | 按任务 | browser operation |
| `pkg.media` | 按任务 | image operation |
| `pkg.office` | office profile | office document operation |
| `pkg.local_execution` | 高风险显式 | shell operation |

默认启用不再包含：

```text
pkg.filesystem.write
pkg.git.write
pkg.web
pkg.multimodal
pkg.mcp.local
```

默认工具面只保留读取、搜索、代码结构、agent state。

## 6. Profile 与 Skill 改线

### 6.1 Runtime Profile

需要改：

```text
backend/agent_system/profiles/runtime_profile_registry.py
backend/agent_system/registry/worker_agent_factory.py
```

处理方式：

- 所有 `extra_allowed_operations` 改成新 operation。
- 删除旧 operation ref，不做 aliases fallback。
- coding main profile 使用 `workspace_* + code_structure + git + workspace_edit + local_execution`。
- project network profiles 使用 `project_network` operations。
- office profile 使用 `office_document + workspace_read`。
- web/research profiles 使用 `web` operations。
- browser/image 只在相关 skill 或 explicit task environment 中启用。

### 6.2 Skill Registry

需要改：

```text
backend/capability_system/skills/builtin/*
backend/capability_system/skills/operation_requirements.py
backend/capability_system/skills/registries/SKILLS_REGISTRY.json
backend/capability_system/skills/registries/SKILLS_SNAPSHOT.md
```

处理方式：

- 删除只负责说明工具调用方式的内置 Skill。
- `browser_control` 操作原则迁入 `tool.guidance.browser`。
- `image_generate` 操作原则迁入 `tool.guidance.image`。
- `web_search/fetch_url` 搜索方法迁入 `tool.guidance.web_fetch`。
- `mcp_pdf/mcp_retrieval/mcp_structured_data` 保持为本地 MCP 能力单元，但不再通过 `pdf-analysis`、`rag-skill`、`structured-data-analysis` 旧 Skill 名暴露。

### 6.3 Tool Guidance Prompt

需要改：

```text
backend/prompt_library/tool_prompts.py
```

旧工具 guidance 删除，改成新工具契约：

- `workspace_search`：只做 locator，不把命中当事实。
- `workspace_read`：读取证据，支持目录/文件/元信息/工具结果。
- `workspace_edit`：必须有目标路径和明确编辑意图。
- `project_network`：顺物理骨架爬行，不伪造语义边。
- `git`：read/write/remote action 分清。

Tool guidance 的 prompt ref 也必须使用统一工具面命名，例如 `tool.guidance.workspace_read`、`tool.guidance.workspace_search`、`tool.guidance.local_execution`、`tool.guidance.agent_state` 和 `tool.guidance.web`。旧 `read_file/write_file/terminal/todo/web_fetch` ref 只能存在于一次性迁移表中，不得作为默认注入、注册表或模型可见契约继续出现。

## 7. Task Environment 与 Planner 改线

需要改：

```text
backend/task_system/environments/default_environments.py
backend/task_system/contracts/runtime_contracts.py
backend/task_system/planning/execution_recipe_builder.py
backend/task_system/services/assembly_builder.py
```

处理方式：

- task environment 不再枚举一堆旧工具 operation。
- planner 的 required/optional operations 改为新 operation。
- runtime_contracts token 映射改成新工具/operation。
- assembly_builder 的特殊白名单同步改掉。

## 8. 前端与生成态注册

需要刷新：

```text
backend/capability_system/tools/registries/TOOLS_REGISTRY.json
```

如果前端直接展示工具列表，还需要检查：

```text
frontend / app capability catalog projection
backend/capability_system/catalog_projection.py
backend/capability_system/validation.py
backend/capability_system/unit_projection.py
```

目标：

- tool_count 从 49 降到约 14。
- `default_library` 必须为空。
- 默认 package 不包含写、web、多模态、MCP、browser。
- capability catalog 不再显示已删除旧工具。

## 9. 实施步骤

### Phase 1：建立新统一工具

新增/重写工具单元：

```text
backend/capability_system/tools/tool_units/workspace_tools.py
backend/capability_system/tools/tool_units/code_structure_tool.py
backend/capability_system/tools/tool_units/git_tool.py
backend/capability_system/tools/tool_units/subagent_tool.py
backend/capability_system/tools/tool_units/project_network_tool.py
backend/capability_system/tools/tool_units/web_tool.py
backend/capability_system/tools/tool_units/browser_tool.py
backend/capability_system/tools/tool_units/image_tool.py
backend/capability_system/tools/tool_units/local_execution_tool.py
```

保留或复用底层 service：

- `WorkspaceFileService`
- `WorkspaceSearchService`
- `ProjectStructure*Service`
- existing git subprocess helpers
- existing image/browser/office implementation

### Phase 2：替换 catalog 与 operations

改：

```text
backend/capability_system/tools/native_tool_catalog.py
backend/permissions/operations.py
backend/permissions/operation_packages.py
```

删除旧 tool definitions。

### Phase 3：全局引用改线

使用 `rg` 找所有旧工具名和旧 operation：

```text
op.read_file
op.search_text
op.git_status
browser_control
image_generate
...
```

逐个改到新 operation/tool。

### Phase 4：删除旧工具文件

删除无独立权威的 tool unit 文件：

```text
file_system_tools.py
search_files_tool.py
git_tools.py
subagent_control_tool.py
text_metric_tool.py
terminal_tool.py
python_repl_tool.py
web_search_tool.py
fetch_url_tool.py
python_ast_tools.py
```

说明：

- 若新统一工具复用其中代码，先迁移 helper，再删旧文件。
- `office_document_tool.py` 可保留。
- `browser_control_tool.py / image_generation_tool.py` 可改名或内部复用后删除旧文件。
- `project_structure_tools.py` 将被 `project_network_tool.py` 替代。

### Phase 5：刷新注册与静态验证

执行：

```powershell
python -m compileall backend\capability_system backend\permissions backend\agent_system backend\task_system backend\prompt_library backend\harness
python -c "from pathlib import Path; from capability_system.tools.registry import refresh_tool_registry; print(refresh_tool_registry(Path('.')))"
git diff --check
```

不新增测试文件。

### Phase 6：真实 smoke

用工具实例真实跑：

```text
workspace_search -> workspace_read -> code_structure
git action=status/diff
project_network action=build_skeleton/directory_relations
web action=search 仅在环境允许时测 schema，不强行外网
```

## 10. 风险与处理

| 风险 | 处理 |
| --- | --- |
| 旧 tests 引用旧工具 | 删除或改写旧测试，不保留旧工具 |
| skill registry 快照漂移 | 重新生成或同步修改 |
| task planner 仍产旧 operation | 全局 rg 阻断，compile 后再做 registry validation |
| 权限变粗 | 工具合并但 operation 不粗化；action 映射到 operation |
| agent 不知道 action 怎么用 | tool guidance 写成 agent 可执行契约，不写开发说明 |
| frontend 展示旧工具 | 刷新 `TOOLS_REGISTRY.json` 并检查 capability catalog |

## 11. 执行后验收标准

必须满足：

```text
tool_count <= 16
default_library == []
旧工具名在 native tool catalog 中不存在
旧 operation 不再出现在 profile / package / skill / task environment 中
项目网络工具不再是 8 个碎工具，而是一个 project_network 工具
workspace 文件工具不再是 8 个碎工具，而是 workspace_search/workspace_read/workspace_edit
git 不再是 11 个碎工具，而是 git action tool
subagent 不再是 5 个碎工具，而是 subagent action tool
```

允许底层服务和内部 helper 继续存在，但不得作为 agent-visible tool 或旧 operation 暴露。
