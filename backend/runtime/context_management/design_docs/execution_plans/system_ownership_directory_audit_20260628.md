# System Ownership Directory Audit

日期：2026-06-28  
状态：系统归属审计；只定名、定权威、定治理规则，不修改运行代码。  
范围：项目根目录、`backend` 一级系统、已知模糊目录、运行态数据目录、旧 agent 神经结构。

## 1. 审计结论

当前项目的问题不是目录不够多，而是系统名、authority 名、文件实际职责之间出现错位。`harness`、`runtime`、`orchestration`、`context_system`、`runtime/context_management`、`prompting`、`prompt_library`、`prompt_composition` 等名字同时存在，后续开发者很难一眼判断一个文件到底有没有资格决定 agent 行动、工具面、权限、上下文、输出提交或图状态。

目标治理原则：

- 每个系统只拥有一种主权威：事实源、控制层、执行层、传输层、存储层、展示层不能混名。
- 每个文件必须能回答三个问题：属于哪个系统、拥有哪个决策权、生命周期由谁管理。
- 一个 authority 字符串必须指向真实系统，不能继续用 `orchestration.*` 泛指所有运行对象。
- 运行态数据不能散在项目根目录；源码系统和 runtime data 必须分开。
- 旧链路不以兼容为理由保留。若 active path 已有目标系统，同阶段 cutover 后删除旧路径。

正确总图：

```text
backend/harness              Agent neural control system
backend/graph_system         Target: executable graph system
backend/task_system          Task / graph authoring, contracts, compiler
backend/runtime              Provider / tool / context / storage infrastructure
backend/capability_system    Tool / MCP / Skill capability facts
backend/permissions          Boundary policy and operation admission
backend/memory_system        Memory facts and memory hints
backend/agent_system         Agent identity, profile, body, groups
backend/context_system       Generic context policy / compaction / resolution toolkit
backend/prompt_library       Prompt resources and prompt pack registry
backend/prompt_composition   Prompt/message materialization engine
storage/                     Runtime data root, not a source system
```

## 2. 系统定名规则

命名必须按权威来，不按文件内容的表面名来。

| 问题 | 合法答案 | 禁止答案 |
|---|---|---|
| 谁观察事实 | request facts、session state、file state、memory hints、capability facts | intent、plan、route |
| 谁决定 agent 下一步 | model decision in harness loop | request parser、permission、provider、tool executor |
| 谁授权动作 | permissions + harness admission/action permit | tool executor 自己猜、provider 层兜底 |
| 谁执行动作 | runtime tool/model infra | harness prompt compiler、task compiler |
| 谁推进图状态 | graph system | harness loop、task compiler、runtime provider |
| 谁生成 agent-visible prompt | harness compiler + prompt composition | provider payload sidecar、tool runtime |
| 谁绑定 provider 传输 | runtime model gateway | agent memory、stable prompt |
| 谁封存历史证据 | runtime ledger / runtime memory stores | memory hint、dynamic tail |

判断标准：如果一个模块会选择目标、改写目标、授权执行、提交输出、推进状态机，它就拥有决策权，必须放在对应系统；如果它只是格式转换、存储、传输或展示，就不能拥有上游决策权。

## 3. 根目录归属审计

| 路径 | 当前事实 | 目标归属 | 处理意见 |
|---|---|---|---|
| `backend/` | 后端源码主系统 | Source system | 保留 |
| `frontend/` | 主工作台前端 | Source system | 保留 |
| `apps/ai-global-trends/` | 已跟踪的独立 Next app | Satellite app system | 保留在 `apps/`，不要散到根目录 |
| `extensions/vscode/` | 已跟踪 VS Code 扩展 | Extension system | 保留在 `extensions/` |
| `scripts/` | 根级运维/开发脚本 | Project operations | 保留，但脚本必须有清楚系统对象 |
| `.codex/`、`.codex-runtime-logs/`、`.runtime_logs/`、`.tmp/`、`.pytest_cache/`、`__pycache__/` | 本地工具、日志、缓存 | Local workspace cache | 不作为项目系统；保持 ignored |
| `node_modules/` | 依赖缓存 | Dependency cache | 不作为项目系统 |
| `storage/` | `ProjectLayout` 的 runtime data root | Runtime data root | 正式运行态数据只进这里 |
| `runtime_state/`、`runtime_cache/`、`runtime_objects/`、`runtime_views/`、`prompt_accounting/`、`state_index/` | 根级运行态残留 | Should be under `storage/` | 迁移或删除残留，不能作为根系统 |
| `events/`、`event_index/`、`event_payloads/`、`executions/`、`facts/`、`traces/`、`runs/`、`queued_user_inputs/`、`file_state/` | 根级 runtime store 残留，多数为空 | Should be under `storage/` | 按数据有效性迁移/删除 |
| `graph_checkpoints.sqlite` | 根级图 checkpoint 数据库 | `storage/graph_system/` 或 `storage/runtime_state/graph_system/` | 图系统独立时迁移 |
| `output/` | 忽略的产物目录 | Generated artifacts | 可保留为 ignored 产物目录；不要放源码 |
| `docs/` | 根级文档目录，但 `.gitignore` 忽略 `docs/` | Shadow docs, not canonical | 若需要版本化，移入可跟踪设计文档目录或调整 ignore |
| `source/` | 图片素材，当前 ignored | Generated/source assets | 归入 `storage/generated`、`output/source_assets` 或正式 asset 系统 |
| `scifact/` | 外部数据集，ignored | External dataset | 应走 external data root，不做项目源码 |
| `mario-game/`、`resume-website/` | 已跟踪生成/示例产物 | Ambiguous sample/deliverable | 若是产品样例，移入 `apps/samples/`；若是生成产物，移入 `output/` 并停止跟踪 |
| `mythical-agent/` | 空目录 | No owner | 删除或明确为未来 workspace，不保留空系统名 |

根目录目标：源码系统、扩展系统、卫星 app、运行数据、生成产物五类必须分开。`storage/` 是 runtime data 的系统边界；根级 `runtime_*`、`events`、`facts` 等目录不应继续存在为独立系统。

## 4. Backend 一级系统归属

| 目录 | 正名 | 主权威 | 禁止承担 |
|---|---|---|---|
| `api/` | HTTP/API adapter | 请求/响应协议、依赖注入、调用后端服务 | 业务决策、agent prompt 决策、图状态推进 |
| `bootstrap/` | App composition | 应用生命周期、服务装配、运行配置控制台 | agent 行动裁决 |
| `core/` | Core utilities | config、project layout、json store、token/text helpers | 业务语义 |
| `harness/` | Agent neural control system | request boundary、runtime assembly、packet、compiler、model loop、admission、feedback、output commit | provider transport、长期记忆存储、能力事实注册、图核心状态机 |
| `graph_system/` | Target executable graph system | 图配置、图运行、状态机、checkpoint、resume、work order | agent prompt、工具权限、模型 provider |
| `task_system/` | Task authoring and compiler | 任务合同、任务图定义、编译、registry、project/task repository | 执行 agent turn、推进 graph runtime |
| `runtime/` | Low-level runtime infrastructure | model gateway、tool execution、physical context、ledger、shared events/stores | agent 语义裁决、当前工具面决策、最终输出裁决 |
| `capability_system/` | Capability fact system | Tools / MCP / Skills registry、supply、catalog facts、远程能力管理 | 当前回合工具授权和 agent-facing action choice |
| `permissions/` | Boundary policy system | operation gate、approval、permission policy、resource decision | 改写用户目标、替 agent 换行动 |
| `memory_system/` | Memory fact/hint system | durable/session/working/formal memory、memory governance、runtime memory hints | 替代 evidence、重新授权当前行动 |
| `agent_system/` | Agent identity/profile system | agent identity、profile、body、group、runtime spec facts | runtime loop 执行 |
| `context_system/` | Generic context toolkit | compaction、budget、context package、resolution、projection helpers | provider-visible physical plan、agent prompt 最终拼接 |
| `runtime/context_management/` | Physical context pipeline | provider-visible ledger、cache plan、physical context segments | agent 意图裁决 |
| `prompt_library/` | Prompt resource library | role prompts、prompt packs、rules、tool guidance resources | 当前回合 prompt 物理拼接 |
| `prompt_composition/` | Prompt materialization engine | section rendering、message specs、provider payload plan inputs | prompt 资源事实、agent 行动裁决 |
| `prompting/` | Legacy prompt toolkit | 旧 builder、旧 manifest、旧 strategy prototypes | 新运行链路入口；新代码不应继续依赖 |
| `sessions/` | Session store and projection | session payload、fork、task binding、public/api transcript | graph/harness 命名权威、agent 决策 |
| `file_management/` | File repository/access system | 文件网关、access table、metadata、receipts | agent tool policy 和 evidence timeline 决策 |
| `artifact_system/` | Artifact repository/governance | artifact namespace、repository、materialization receipts | 任务执行和 agent loop |
| `knowledge_system/` | Knowledge ingestion/indexing | ingestion、conversion、indexing、retrievers | runtime evidence commit |
| `evidence/` | Evidence orchestration workers | RAG/pdf/table/image evidence packet production | agent final output commit |
| `health_system/` | Runtime health and inspector system | health records、runtime monitor projection、command supervision | agent 行动裁决 |
| `code_environment/` | Code environment integration | PI process/environment、workspace tree | permission policy 或 tool contract |
| `integrations/` | External integration adapters | VS Code connection 等 | domain logic |
| `project_workspaces/` | Workspace registry/service | workspace binding service | file/tool execution |
| `modality_index/` | Modality artifact index | modality artifact refs | runtime control |
| `observability/` | Tracing integration | LangSmith/debug trace | runtime decisions |
| `cli/` | CLI client | command-line adapter | backend service authority |
| `tests/` | Tests | behavior verification | 旧结构化石不能保护已废弃系统 |
| `storage/` | Misplaced runtime data | None as source | 应迁到根 `storage/` 或删除 |
| `file_state/` | Empty/no owner | None | 删除或合并到 canonical file state system |

## 5. 主要模糊区裁决

### 5.1 `backend/orchestration`

当前 `orchestration/__init__.py` 作为大 re-export，把 `runtime`、`permissions`、`capability_system`、旧 `ControlKernel`、旧 `TaskContract`、`commit_gate`、`runtime_directive` 混成一个门面。这个名字已经不能准确代表真实权威。

裁决：

- `ControlKernel`、`CandidateEnvelope`、旧 `TaskContract`、旧 `ExecutionGraph`：旧神经结构，若不在 active 主链中，删除并删除 fossil tests。
- `commit_gate.py`：归 `harness.runtime.commit_gate` 或并入 `harness.runtime.output_commit_authority`。
- `runtime_directive.py`：归 `runtime.shared.runtime_directive`。
- `execution_scheduler.py` 的 `BackgroundTaskManager`：归 `runtime.shared.background_tasks` 或具体消费系统。
- `resource_runtime_view.py`：归 `capability_system/permission_projection.py` 或 `permissions` projection。
- `unit_registry.py`：若前端仍需要 catalog，归 `capability_system.catalog_projection`；否则删除。
- `resource_inventory.py`：过时静态 inventory，不应作为 runtime 代码。

长期目标：删除 `backend/orchestration` 作为 active 目录。`orchestration.*` authority 字符串分批改成真实系统 authority。

### 5.2 `backend/harness/graph*`

`backend/harness/graph_harness.py` 和 `backend/harness/graph/` 实际是完整图系统，不是 agent 神经系统内部细节。

裁决：

- 图核心迁入 `backend/graph_system`。
- `GraphHarness` 改为 `GraphSystem`。
- `GraphHarnessConfig` 改为 `ExecutableGraphConfig`。
- `graph_harness_config_id` 改为 `graph_config_id` 或 `executable_graph_config_id`。
- `harness/graph/work_order_contract.py` 是 harness adapter，迁到 `harness/runtime/graph_node_contract.py`，不进 graph core。

### 5.3 `backend/runtime` 内的 agent 神经散点

`runtime` 应是基础设施，但以下目录有 agent 决策味道：

| 当前目录 | 问题 | 目标 |
|---|---|---|
| `runtime/output_boundary` | 最终输出裁决、finalization policy 不应在低层 runtime | 拆分：输出卫生可留低层，final/commit 裁决进 harness |
| `runtime/outcome` | RunOutcome 与 active harness outcome 权威未统一 | 若接 active 主链则进 `harness/runtime/outcome`，否则删除 |
| `runtime/contracts/obligation_validation.py` | 交付义务裁决属于 agent run outcome | 进 harness outcome/obligations 或删除 |
| `runtime/contracts/continuation_*` | graph stage、continuation policy 混层 | graph stage 归 graph/task；agent continuation 归 harness |
| `runtime/tooling/capability_table.py` | current-turn capability surface 不应在 low-level runtime | 进 `harness/runtime/capability_surface` 或 stable execution contract |
| `runtime/tooling/supervisor.py` | tool execution supervision 是低层工具执行基础设施 | 进 `runtime/tool_runtime/supervision.py` |

### 5.4 `context_system` vs `runtime/context_management`

这两个可以同时存在，但名字和边界必须钉死：

- `context_system`：通用上下文算法库，负责 compaction、budget preset、context package、resolution、projection helper。
- `runtime/context_management`：当前 provider-visible context 的物理流水线，负责 cache spine、sealed ledger、physical plan、tool transcript。

禁止：`context_system` 直接决定 provider sidecar；`runtime/context_management` 重新裁决 agent 意图。

### 5.5 `prompt_library` vs `prompt_composition` vs `prompting`

裁决：

- `prompt_library` 是资源库：prompt pack、role prompt、tool guidance、规则资源。
- `prompt_composition` 是材料化引擎：把资源、上下文、message specs 编译成 provider/message 结构。
- `prompting` 是旧 prompt toolkit。仍被少数旧调用和测试引用，但不应成为新链路入口。后续按功能并入 `prompt_library` 或 `prompt_composition`，剩余无 active import 后删除。

### 5.6 `request_intent`

当前 `request_intent/request_signals.py` 自己声明 `structural_observation_only`，并且 `capability_intent.tool_selection_allowed=False`。这说明它不是“意图裁决者”，而是“请求事实/结构信号”。

裁决：

- `frame_access.py`、`request_signals.py` 改名归入 `context_system/request_signals` 或 `harness/runtime/request_facts`。
- `memory_intent.py` 如果继续用 marker 判断 memory read/write，只归 `memory_system/request_signals`，不能作为全局 request intent。
- 不再允许 `request_intent` 这个目录名代表最终用户意图。

### 5.7 `continuation` vs `harness/continuation`

当前根级 `backend/continuation` 是候选收集/决策算法；`backend/harness/continuation` 是 runtime recovery boundary、record、selector。

裁决：

- runtime 恢复权威只属于 `harness/continuation`。
- 根级 `continuation` 若仍 active，迁入 `harness/continuation/candidates` 或改名为 `continuation_candidates`；否则删除。
- 不保留两个同名 continuation 系统。

### 5.8 `runtime_objects`

`backend/runtime_objects` 当前保存 tool result storage、read observation artifacts、runtime context layout。它是 runtime object storage helper，不应作为根级“对象系统”。

裁决：

- 通用 object store helper 归 `runtime/shared`。
- tool result / read observation artifact 归 `runtime/tool_runtime` 或 `runtime/memory`，按读写权威拆分。
- 根目录 `runtime_objects/` 是数据残留，归 `storage/` 或删除。

### 5.9 `sessions`

`backend/sessions/__init__.py` 同时包含 session store、fork context snapshot、project binding、task binding、provider cache fork metadata，并仍有 `graph_harness_config_id`。

裁决：

- `sessions` 是 session infrastructure，不是 graph/harness authority。
- graph 字段 cutover 时，`graph_harness_config_id` 必须随 `graph_system` 一起改名。
- 后续可拆成 `sessions/store.py`、`sessions/forking.py`、`sessions/bindings.py`、`sessions/projections.py`，但不因为文件大而先拆。

## 6. Authority 字符串治理

当前 `orchestration.*` 已被写成泛用 authority，例如 task run、runtime observation、execution receipt、memory scope、agent profile、graph run control、protocol boundary。这个会造成审计混乱。

目标 authority 前缀：

| 旧泛用前缀 | 目标前缀 |
|---|---|
| `orchestration.task_run` | `harness.task_run` 或 `runtime.shared.task_run_record`，按对象决定 |
| `orchestration.runtime_observation` | `harness.feedback` 或 `runtime.observation`，按是否 agent feedback 决定 |
| `orchestration.execution_receipt` | `runtime.execution_receipt` |
| `orchestration.runtime_commit_gate` | `harness.output_commit` |
| `orchestration.graph_run_control` | `graph_system.run_control` |
| `orchestration.agent_registry` | `agent_system.registry` |
| `orchestration.memory_scope_policy` | `memory_system.scope_policy` |
| `orchestration.protocol_boundary` | `runtime.model_gateway.protocol_boundary` 或 `harness.action_feedback.protocol_repair` |

迁移原则：不要只改字符串。authority 改名必须和文件归属、模型归属、写入点、读取点同阶段 cutover。

## 7. 目标目录骨架

```text
backend/
  api/
  bootstrap/
  core/
  agent_system/
  task_system/
  graph_system/                 # target
  harness/
    entrypoint/
    continuation/
    loop/
    runtime/
      context_contract/
      capability_surface/
      output_boundary/
      outcome/
      graph_node_contract.py
  runtime/
    context_management/
    model_gateway/
    tool_runtime/
    memory/
    shared/
    output_stream/
    prompt_accounting/
  capability_system/
    tools/
    mcp/
    skills/
  permissions/
  memory_system/
  context_system/
  prompt_library/
  prompt_composition/
  file_management/
  artifact_system/
  knowledge_system/
  evidence/
  health_system/
  sessions/
  integrations/
  project_workspaces/
```

根目录目标：

```text
/
  backend/
  frontend/
  apps/
  extensions/
  scripts/
  storage/                      # ignored runtime data
  output/                       # ignored generated deliverables
  backend/runtime/context_management/design_docs/  # 当前可跟踪架构文档入口
```

## 8. 推荐执行顺序

此文档不是执行许可。涉及 runtime / prompt / tool / permission / API 字段的大改仍需确认后实施。

推荐顺序：

1. 固定系统目录规则：确认本文档为 system ownership map。
2. 先做 `graph_system` 独立，移除 `harness.graph*` 命名污染。
3. 拆 `orchestration`，把 active infra 迁入真实系统，旧 control brain 删除。
4. 收束 `runtime/output_boundary`、`runtime/outcome`、`runtime/tooling` 等 agent 神经散点。
5. 处理 `request_intent`、`continuation`、`prompting` 的名称不正问题。
6. 清理根目录 runtime data 残留，统一进入 `storage/`。
7. 最后再做 authority 字符串 cutover 和前端/API 字段同步。

## 9. 审计不变量

- `harness` 是 agent 神经系统，不吞掉 provider、memory、permission、capability registry。
- `graph_system` 是图系统，不再写成 `harness.graph_*`。
- `runtime` 是基础设施，不成为第二个 agent brain。
- `permissions` 只执行边界并反馈，不改写 agent 目标。
- `capability_system` 是能力事实源；当前回合工具面归 harness。
- `memory_system` 是 memory hint 事实源；证据必须来自 evidence/ledger/tool observation。
- `provider tools sidecar` 是 hidden transport，不进 stable prompt、不进 memory、不进 sealed provider-visible history。
- 根目录只保留源码系统、扩展系统、卫星 app、运行数据根和产物根；不允许 runtime data 以系统目录形式散落。

