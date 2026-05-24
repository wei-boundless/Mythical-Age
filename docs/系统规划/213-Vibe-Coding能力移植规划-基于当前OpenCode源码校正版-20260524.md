# Vibe Coding 能力移植规划：基于当前 OpenCode 源码校正版

日期：2026-05-24

## 1. 校正结论

之前的 `212-Vibe-Coding能力移植规划-20260524.md` 使用了 `D:/AI应用/opencode-main` 作为 OpenCode 源码依据，这是错误的。该目录不是当前 OpenCode 的真实源码主线，文档中所有 Go 路径依据都应作废，包括：

- `D:/AI应用/opencode-main/internal/llm/agent/agent.go`
- `D:/AI应用/opencode-main/internal/llm/tools/view.go`
- `D:/AI应用/opencode-main/internal/llm/tools/edit.go`
- `D:/AI应用/opencode-main/internal/llm/tools/patch.go`
- `D:/AI应用/opencode-main/internal/permission/permission.go`

当前应参考的真实源码是 `D:/AI应用/opencode-dev`。它是 Bun/TypeScript monorepo，根 `package.json` 的包名为 `opencode`，仓库指向 `https://github.com/anomalyco/opencode`。

方向性结论仍然成立：不要把 OpenCode 整体搬进来，而是把它作为专业 coding agent 内核参考，吸收工作区快照、工具合同、权限规则、流式执行状态机、diff/diagnostics 闭环，重建为我们平台里的 `vibe_coding` 能力。

但能力重点必须修正：

- 不是 Go 版的轻量 `processGeneration` 主循环，而是 TypeScript 版 `SessionProcessor + LLM adapter + ToolRegistry + Permission ruleset + Snapshot` 的组合。
- 不是单纯“读后写保护”的编辑工具，而是工具执行前后统一携带 diff、files、diagnostics、truncation、permission metadata 的合同体系。
- 不是靠 route 或按钮本身完成 vibe coding，而是路由选择 `vibe_coding` 运行模式后，还必须有 coding workspace state、strict edit/patch、terminal 语义、安全权限、验证证据和前端 change set 管理。

## 2. 当前 OpenCode 源码依据

### 2.1 Agent 模式不是 prompt 开关，而是权限规则集

真实文件：`D:/AI应用/opencode-dev/packages/opencode/src/agent/agent.ts`

当前 OpenCode 内置 agent 包括：

- `build`：默认 primary agent，基于默认权限加用户权限，允许 question 和 plan_enter。
- `plan`：primary 计划模式，禁止所有 edit 类工具，只允许写 `.opencode/plans/*.md` 等计划文件。
- `general`：subagent，默认继承较宽工具能力，但禁用 `todowrite`。
- `explore`：subagent，只允许 grep/glob/list/bash/web/read 等探索能力，其他默认 deny。
- `compaction`、`title`、`summary`：隐藏 agent，权限默认全 deny。

权限不是写在 prompt 里，而是 `Permission.fromConfig()` 和 `Permission.merge()` 生成的 ruleset。`plan` 和 `explore` 的安全边界由规则强制执行。

真实文件：`D:/AI应用/opencode-dev/packages/opencode/src/agent/subagent-permissions.ts`

子 agent 权限派生时会把父 agent 的 edit deny 规则、父 session 的 deny/external_directory 规则继续下传，避免 plan mode 下子 agent 绕过父级禁写。这一点对我们非常重要：`vibe_coding` 里的 explorer/planner/verifier 必须靠 operation scope 和权限规则禁写，不能只靠角色说明。

### 2.2 Permission 是 ordered ruleset，不是工具内散落判断

真实文件：

- `D:/AI应用/opencode-dev/packages/core/src/permission.ts`
- `D:/AI应用/opencode-dev/packages/opencode/src/config/permission.ts`

核心模型是：

```text
Rule = { permission, pattern, action: allow | deny | ask }
Ruleset = Rule[]
evaluate(permission, pattern, ...rulesets) 使用 findLast 匹配
```

这意味着后合并的规则优先级更高。编辑类工具被统一归并为 `edit` 权限，包括 `edit`、`write`、`apply_patch`。这比我们当前只按工具名授权更适合 coding mode，因为用户真正关心的是“改哪些文件、改成什么样”，而不是模型调用了哪个编辑工具。

### 2.3 SessionProcessor 是当前 OpenCode 的执行内核

真实文件：`D:/AI应用/opencode-dev/packages/opencode/src/session/processor.ts`

新版 OpenCode 的核心不是旧文档说的 Go 主循环，而是 `SessionProcessor`：

- LLM stream 开始前先 `snapshot.track()` 捕获初始工作区快照。
- 处理 LLM 事件：`reasoning-start/delta/end`、`text-start/delta/end`、`tool-input-*`、`tool-call`、`tool-result`、`tool-error`、`step-start`、`step-finish`。
- 每个 tool call 都有 pending/running/completed/error 状态，并通过 call id 追踪。
- `step-finish` 时再次 `snapshot.track()`，再用 `snapshot.patch(initial)` 生成本步文件变更 part。
- 失败、abort、未完成工具会在 cleanup 中转为明确 error part。
- overflow 时触发 compaction，返回 `compact | stop | continue`。

这给我们的启示是：vibe coding 需要一个“执行流处理器”，把模型输出、工具状态、快照 diff、验证结果、最终输出绑定成一条可追踪事件链。只在路由上切 `vibe_coding`，还不等于拥有 coding 内核。

### 2.4 LLM 层有稳定的 adapter seam

真实文件：`D:/AI应用/opencode-dev/packages/opencode/src/session/llm.ts`

OpenCode 把不同 LLM runtime 统一成同一种 `LLMEvent` stream。默认走 AI SDK，也有 experimental native runtime；两者都被适配到 processor 消费的事件结构。

这对我们更像一个结构提示：我们的 Python runtime 不必照搬 Bun/Effect/AI SDK，但应保留一个明确的 `ModelEvent -> RuntimeEvent -> ToolEvent -> ChangeSetEvent` 适配层。否则后续接不同模型、不同工具执行方式时会继续把分支散落到主循环。

### 2.5 Snapshot 是工作区真相的一部分

真实文件：`D:/AI应用/opencode-dev/packages/opencode/src/snapshot/index.ts`

OpenCode 用隐藏 git dir 维护工作区快照：

- `track()` 初始化并写 tree hash。
- `patch(hash)` 得到本轮改动文件列表。
- `diff()` / `diffFull()` 生成 diff 信息。
- `restore()` / `revert()` 可以按快照恢复。
- 忽略 gitignored 文件，并排除超大文件。

我们不一定要照搬隐藏 git dir，但必须引入等价的 coding workspace snapshot。否则 vibe coding 的“改了什么、是否能回滚、最终输出依据是什么”都会停留在工具日志层。

### 2.6 ToolRegistry 是工具定义、插件、模型差异和动态描述的装配层

真实文件：

- `D:/AI应用/opencode-dev/packages/opencode/src/tool/tool.ts`
- `D:/AI应用/opencode-dev/packages/opencode/src/tool/registry.ts`

工具定义统一包含：

```text
id
description
parameters / jsonSchema
execute(args, ctx)
formatValidationError
```

工具执行包装层会先做参数 Schema 校验，再执行工具，最后对输出做 truncation。ToolRegistry 会：

- 初始化内置工具。
- 加载插件工具。
- 根据 feature flags 和模型 ID 选择 `apply_patch` 或 `edit/write`。
- 给 task/skill 动态拼接可用 agent/skill 描述。

我们应保留自己的 ToolRuntime/OperationRegistry，但需要给 `vibe_coding` 增加一层 coding tool profile：同一个操作在 coding mode 下必须返回 diff/change_set/diagnostics metadata，而不能只返回自然语言。

### 2.7 文件读取工具负责上下文节流和 LSP 预热

真实文件：`D:/AI应用/opencode-dev/packages/opencode/src/tool/read.ts`

`read` 工具有几个关键点：

- 绝对/相对路径归一化。
- external directory guard。
- read permission ask。
- 目录读取和文件读取分支。
- 二进制、图片、PDF 特殊处理。
- 文本读取带行号，默认 2000 行，单行 2000 字符，整体 50KB。
- 读取后异步 `lsp.touchFile()`。
- 可附加 loaded instruction reminder。

我们当前文件工具如果只返回全文或简单片段，不足以支撑长任务。vibe coding 第一阶段应补“带行号、有限窗口、read receipt、hash/mtime、引用化大内容”的读取协议。

### 2.8 edit/write/apply_patch 的价值在 diff + permission + diagnostics 合同

真实文件：

- `D:/AI应用/opencode-dev/packages/opencode/src/tool/edit.ts`
- `D:/AI应用/opencode-dev/packages/opencode/src/tool/write.ts`
- `D:/AI应用/opencode-dev/packages/opencode/src/tool/apply_patch.ts`
- `D:/AI应用/opencode-dev/packages/opencode/src/patch/index.ts`

新版 `edit`：

- 对同一文件使用 semaphore 锁。
- 支持新文件写入。
- 处理 BOM 和换行符。
- 构造 diff 后先 `ctx.ask(permission="edit", metadata={filepath,diff})`。
- 写入后格式化、发布 file watcher event、触发 LSP diagnostics。
- 替换逻辑会尝试 exact、trimmed、block anchor、whitespace、indentation、escape、context aware 等 fallback，最后仍要求唯一匹配。

新版 `write`：

- 读取旧内容，生成完整 diff。
- 申请 edit 权限。
- 写入、格式化、发布事件。
- 返回当前文件和部分项目 diagnostics。

新版 `apply_patch`：

- 解析 `*** Begin Patch` 自定义 patch grammar。
- 支持 add/update/delete/move。
- 先 parse/derive new content，再构造 per-file metadata 和 total diff。
- 对所有变更路径一次性申请 edit 权限。
- 应用后格式化、发布 watcher、touch LSP，返回 diagnostics。

这修正了旧规划中的一个细节：当前 OpenCode 不只是“严格 old_string 唯一匹配”，它在 edit 中允许多种修正匹配策略，但最终仍会拒绝找不到或多处命中的编辑。我们移植时应更保守：MVP 默认 exact/trim only，后续再加可审计 fuzzy repair。

### 2.9 Shell 工具是命令语义、外部目录权限和输出持久化的组合

真实文件：`D:/AI应用/opencode-dev/packages/opencode/src/tool/shell.ts`

`shell` 工具不是裸 subprocess：

- 使用 tree-sitter bash/powershell 解析命令。
- 从命令中识别可能访问的路径，外部目录触发 `external_directory` ask。
- 对命令 pattern 触发 shell permission ask。
- 支持 cwd 解析和 shell 环境插件注入。
- 输出流式收集，超限后写入 truncation 文件，只保留尾部和 metadata。
- timeout/abort 会进入 tool output metadata。

我们的环境主要是 Windows/PowerShell，不能照搬实现，但设计原则必须保留：shell 是高风险工具，必须有语义分析、路径边界、输出持久化、超时和可审计 receipt。

### 2.10 Compaction 不是简单摘要，而是延续状态选择器

真实文件：`D:/AI应用/opencode-dev/packages/opencode/src/session/compaction.ts`

OpenCode compaction 做了几件事：

- 识别已完成 compaction，保留 previous summary。
- 按 tail turn 和 token budget 保留最近上下文。
- 对旧 tool output 做 prune。
- 生成固定 Markdown 结构的 anchored summary。
- overflow 时可 replay 上一条用户消息或自动 continue。

这和我们 docs 的上下文原则一致：长期 coding 任务不能把所有文件内容和命令输出一直塞给模型，必须把“当前目标、约束、已完成、阻塞、关键决定、相关文件”结构化保留下来。

## 3. 对照我们已有架构

我们已经有 `vibe_coding` 的路由和模式接入雏形：

- `backend/orchestration/interaction_mode_policy.py`：能把部分 implementation/verification/code task 选到 `vibe_coding`。
- `backend/task_system/planning/execution_recipe_builder.py`：已有 `runtime.recipe.vibe_coding`，并提高 turn/model/event/time budget。
- `backend/orchestration/runtime_lane_registry.py`：已有 `vibe_coding_task` lane。
- `backend/agent_system/profiles/runtime_mode_config.py`：已有 `VIBE_CODING_MODE`。
- `backend/agent_system/registry/worker_agent_factory.py`：已有 `worker.vibe_coding.executor`。
- `storage/orchestration/agent_runtime_profiles.json` 和 `storage/prompt_library/prompt_resources.json`：已有 vibe_coding profile/prompt 资源绑定。
- `backend/capability_system/operation_registry.py`：已有 `op.browser_control` 统一命名。

这些说明我们现在“能把任务路由到 vibe_coding 模式”，但还不是一个完整可运作的 vibe coding 工具。

当前主要缺口：

1. 缺少 `CodingSession / WorkspaceSnapshot / ChangeSet` 作为 coding 真状态。
2. 现有 `write_file/edit_file/terminal` 还不是 coding 专用严格工具，缺少 read receipt、hash/mtime 防踩踏、diff permission payload、diagnostics receipt。
3. 缺少统一的 `ToolCall -> ChangeSetEvent -> VerificationEvent -> FinalEvidence` 流式状态机。
4. 缺少 shell command semantics，尤其 Windows PowerShell 场景下的路径/危险命令分析。
5. 前端还没有实用的本轮变更管理：文件 diff、验证命令、审批记录、归档/删除。
6. 缺少可恢复 workspace snapshot。现阶段最多能从工具日志推断，不足以 rollback 或做可靠 closeout。

## 4. docs 设计原则转成执行约束

### 4.1 对话循环：显式状态机和实时事件

`docs/设计原则/05-对话循环.md` 强调 AsyncGenerator 状态机、流式事件、工具结果和恢复过程实时投递。OpenCode 当前 `SessionProcessor` 也证明了这一点。

落地约束：

- `vibe_coding` 不能只是 final answer 增强，必须有 runtime event。
- 每个 tool call 都要有 pending/running/completed/error 状态。
- 写入后必须生成 change event，验证后必须生成 verification event。
- abort/permission reject/overflow 都必须转成明确状态，不能沉默失败。

### 4.2 上下文管理：工具输出必须引用化

`docs/设计原则/06-上下文管理.md` 强调多层压缩和 microcompact。OpenCode shell/read/compaction 都把大内容做截断或摘要。

落地约束：

- 大文件读取不能直接全量进 prompt。
- 大命令输出必须保存为 ref，模型只看尾部、摘要、exit code。
- final output 只能消费 canonical change set 和 verification summary，不能消费 refs-only 或 candidate 内容。

### 4.3 工具系统：Schema、权限和输出合同一体化

`docs/设计原则/09-工具系统设计.md` 强调工具接口、schema 和权限。OpenCode `Tool.define()` 进一步展示了参数校验、错误格式化、输出截断、metadata 的统一包装。

落地约束：

- coding 工具必须 schema-first。
- 参数不合法要返回模型可修正错误。
- 工具结果必须结构化：`output + metadata + artifacts/refs`。
- 编辑类工具必须返回 diff/change_set metadata。

### 4.4 Bash/Shell：fail-closed 和命令语义

`docs/设计原则/10-BashTool-深度剖析.md` 强调 shell AST/安全分析 fail-closed。OpenCode 当前 shell 使用 tree-sitter bash/powershell 解析命令。

落地约束：

- PowerShell 命令不能只靠字符串黑名单。
- 读搜类命令应引导使用专用工具。
- 写入/删除/移动/外部目录访问必须触发权限或拒绝。
- timeout、abort、exit code、output ref 都必须成为 receipt。

### 4.5 Agent 系统：默认隔离，显式共享

`docs/设计原则/12-Agent-系统.md`、`13-内置Agent设计模式.md`、`25-架构模式总结.md` 都强调子 agent 隔离、只读 agent 硬约束和权限链。

落地约束：

- `coding.explorer`、`coding.planner`、`coding.verifier` 默认禁写。
- `coding.executor` 的写权限也只能通过 change set / approval gate。
- 子 agent 不能继承出比父模式更宽的写权限。
- 权限边界必须由 operation scope / permit / ruleset 执行，不由 prompt 执行。

### 4.6 权限系统：deny 优先，ask payload 要可审查

`docs/设计原则/16-权限系统.md` 和 `25-架构模式总结.md` 强调权限链、deny 优先、bypass-immune 和熔断保护。OpenCode 使用 ordered ruleset 和 `ctx.ask()` metadata。

落地约束：

- `edit/write/apply_patch` 统一归入 `op.edit_workspace` 或等价 edit 权限。
- ask payload 必须展示 diff、文件、additions/deletions、风险标签。
- 用户批准的是 change set，不是抽象工具名。
- 重复被拒绝后要熔断，不能让 agent 无限重试。

### 4.7 Memory 与 canonical 输出：禁止 candidate 污染下游

`docs/设计原则/23-Memory系统.md` 和我们前面修过的 canonical memory 方向一致：记忆、摘要、refs 都不能替代当前轮 canonical truth。

落地约束：

- coding final answer 只允许从 required canonical change set、verification receipt、stable summary 取材。
- refs-only、draft/candidate、tool raw output 不能直接进入长期记忆或下游 final。
- 长期记忆最多记录稳定偏好、项目约束、已确认项目事实，不记录未验证的中间猜测。

## 5. 推荐设计方向

### 5.1 不移植 OpenCode 骨架，移植内核不变量

不建议照搬：

- Bun/Effect runtime。
- OpenCode session/message DB。
- OpenCode TUI/Desktop UI。
- OpenCode 插件系统。
- OpenCode 当前 patch parser 的全部细节。

建议借鉴：

- `SessionProcessor` 式流式事件处理器。
- agent mode + permission ruleset 的硬边界。
- snapshot -> patch part 的工作区变更记录。
- `read` 的行号化、限流、媒体/二进制处理、LSP 预热。
- `edit/write/apply_patch` 的 diff permission payload、format、watcher、diagnostics。
- `shell` 的命令语义、external directory guard、timeout、输出引用化。
- compaction 的 anchored summary + recent tail 保留策略。

### 5.2 目标结构

新增或强化以下概念：

```text
CodingSession
- session_id
- workspace_root
- mode: inspect | plan | edit | verify | review
- read_set: path -> {hash, mtime, size, line_windows}
- snapshot_before
- snapshot_after
- change_set_id
- command_receipts
- verification_receipts
- approval_receipts
- final_evidence_ref

WorkspaceChangeSet
- id
- files: [{path, status, additions, deletions, patch_ref}]
- total_diff_ref
- diagnostics
- approval_status
- applied_at

CommandReceipt
- id
- command
- cwd
- kind: inspect | build | test | lint | dev_server | git_read | git_write | unknown
- exit_code
- stdout_ref
- stderr_ref
- tail
- timeout_or_abort
```

## 6. 分阶段实施计划

### Phase 1：校正设计文档和模式边界

目标：停止使用错误 OpenCode 依据。

交付：

- 新增本校正版文档。
- 后续实施引用 `213`，不再引用 `212` 的 Go 源码路径。
- 在 backlog 中把 `vibe_coding` 定义为运行模式 + coding kernel，而不是单一入口按钮。

完成标准：

- 所有后续设计和任务拆分引用 `opencode-dev` TypeScript 路径。

### Phase 2：Coding Workspace State

目标：建立 coding 真状态。

建议新增：

- `backend/coding_system/models.py`
- `backend/coding_system/session_store.py`
- `backend/coding_system/workspace_snapshot.py`
- `backend/coding_system/change_set.py`
- `backend/coding_system/receipts.py`

改造：

- `backend/capability_system/workspace_file_service.py`
  - 增加 hash/mtime、safe text read、line window、binary/media 判断。
- `backend/runtime/memory/tool_observation_ledger.py`
  - 识别 coding receipts，避免大 raw output 污染上下文。

完成标准：

- 读取文件生成 read receipt。
- 写入前后能生成 change set。
- change set 能被 runtime event 和 final output 消费。

### Phase 3：Strict Coding Tools

目标：替换“轻文件工具”为 coding 专用合同。

新增：

- `backend/capability_system/units/tools/coding_read_file_tool.py`
- `backend/capability_system/units/tools/coding_edit_file_tool.py`
- `backend/capability_system/units/tools/coding_apply_patch_tool.py`
- `backend/capability_system/units/tools/coding_write_file_tool.py`

改造：

- `backend/capability_system/tool_definitions.py`
- `backend/capability_system/operation_registry.py`
- `backend/runtime/tool_runtime/tool_result_envelope.py`
- `backend/runtime/tool_runtime/tool_contract_gate.py`

MVP 规则：

- 修改已有文件前必须有 read receipt。
- hash/mtime 变化则拒绝写入。
- `old_text` 必须唯一匹配。
- patch 先 parse/validate/build change set，再 apply。
- 失败不能产生半应用。

完成标准：

- 未读文件不能改。
- 外部修改后不能改。
- 多处命中不能改。
- 工具结果含 diff/change_set/diagnostics metadata。

### Phase 4：Permission + Approval Payload

目标：让权限审批面向变更而不是工具名。

改造：

- `backend/runtime/execution_permit/*`
- `backend/permissions/*` 如存在对应 builder。
- 前端 approval 面板。

新增：

- `backend/coding_system/approval_payloads.py`
- `backend/coding_system/diff_preview.py`

完成标准：

- edit/write/patch 统一归入 edit workspace 权限。
- ask payload 包含文件、diff、additions/deletions、风险标签。
- 用户可按 change set 批准/拒绝。
- 拒绝后有熔断或明确停止策略。

### Phase 5：Coding Terminal + Verification

目标：补环境和验证闭环。

新增：

- `backend/coding_system/command_semantics.py`
- `backend/coding_system/verification.py`
- `backend/capability_system/units/tools/coding_terminal_tool.py`

改造：

- `backend/capability_system/units/tools/terminal_tool.py`
- `backend/runtime/professional_runtime/driver.py`
- `backend/runtime/professional_runtime/evidence_closeout.py`

完成标准：

- 命令有 kind、cwd、exit code、timeout、output ref。
- 写入后必须有验证记录，或明确无法验证的结构化原因。
- 大输出不进入 canonical final。
- Windows PowerShell 场景有独立安全分析，不用 Bash 假设。

### Phase 6：Vibe Coding Runtime Processor

目标：把路由模式升级为 coding 内核。

新增：

- `backend/runtime/vibe_coding/processor.py`
- `backend/runtime/vibe_coding/events.py`
- `backend/runtime/vibe_coding/closeout.py`
- `backend/runtime/vibe_coding/compaction.py`

改造：

- `backend/runtime/unit_runtime/loop.py`
- `backend/task_system/planning/execution_recipe_builder.py`
- `backend/orchestration/runtime_lane_registry.py`

完成标准：

- model delta、tool call、tool result、change set、verification 都成为统一事件。
- final answer 只消费 canonical change set 和 verification receipt。
- overflow/abort/permission reject 都有明确状态。

### Phase 7：前端实用管理页

目标：只做直接清晰的管理方式，不做复杂 IDE。

页面结构：

- 左侧：本轮 change set 文件列表。
- 中间：diff viewer。
- 右侧：验证命令、诊断、审批状态。
- 顶部或侧栏：运行状态、归档/删除。

不做：

- 召回模拟。
- 三套记忆系统管理页。
- 复杂合并工作流。
- 伪 IDE 式编辑器。

完成标准：

- 能看本轮改了哪些文件。
- 能看每个文件 diff。
- 能看验证命令和结果。
- 能归档/删除 change set 或 coding session。

## 7. 回答两个架构问题

### 7.1 Vibe coding 是路由还是按钮？

本质上是运行模式，不是按钮。

按钮可以作为显式入口，让用户强制当前任务进入 `vibe_coding`；路由可以根据 task_goal/work_mode/action_intent 自动选择 `vibe_coding`。但按钮和路由都只是 selection layer。

真正决定能力的是：

- runtime lane 是否进入 `vibe_coding_task`
- recipe 是否使用 `runtime.recipe.vibe_coding`
- tool profile 是否切到 coding strict tools
- permission/approval 是否按 change set 工作
- final closeout 是否只消费 canonical change set 和 verification evidence

### 7.2 我们离可运作 vibe coding 工具有多远？

现在已经有“模式选择骨架”，但离可运作工具仍差一层 coding kernel。

已有：

- 任务可路由到 `vibe_coding`。
- 有 `vibe_coding_task` lane 和 recipe。
- 有 worker blueprint 雏形。
- 有基础 shell/file/browser 工具。

缺少：

- workspace snapshot/change set。
- strict read/edit/patch。
- diff approval。
- command semantics 和验证 receipts。
- coding processor。
- 前端 change set 管理页。

所以当前状态可以叫 `vibe_coding mode skeleton`，还不能叫成熟 `vibe coding tool`。

## 8. 优先级建议

最小闭环不要先做 UI，也不要先扩 prompt。顺序应是：

1. `CodingSession + WorkspaceChangeSet`
2. `coding_read_file + coding_edit_file`
3. `coding_apply_patch`
4. `coding_terminal + verification receipt`
5. `vibe_coding processor closeout`
6. 前端 change set 管理页

这条路线符合本项目原则：结构优先、权限硬边界、canonical 输出门、清理旧残留，不靠 prompt 假装能力已经存在。

