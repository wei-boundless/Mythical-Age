# Agent 能力合同与读工具精准化优化书

日期：2026-06-11

## 一、背景与结论

当前问题不应优先理解为边缘控制不足，而应理解为 agent 能力供应链没有配置到位。合理顺序应是：

```text
先给予 agent 真实、可执行、模型可理解的能力
-> 再由模型做语义判断和调度
-> 最后由系统提供资源、对接、校验和边缘控制
```

本次追踪显示，任务可以正常进入 TaskRun，但持续任务执行阶段出现能力合同断裂：模型被提示可以使用 todo、子 agent、读写工具和验证能力，但实际 schema、runtime policy、工具投影和动态状态反馈没有形成同一个可执行合同。模型尝试使用高级能力失败后，回退到反复读取和搜索，导致任务长期运行、预算消耗、没有写入事件，也无法自然收口。

## 二、当前执行链路

当前从用户输入到任务执行的主链路如下：

```text
用户输入
-> runtime_facade 选择 single_agent_turn
-> compile_single_agent_turn_packet 组装 prompt、tools、allowed_action_types
-> 模型选择 respond / tool_call / request_task_run / active_work_control
-> admission 校验 action 是否允许
-> request_task_run 创建 TaskRunContract / TaskRun
-> execute_task_run 进入持续任务执行
-> compile_task_execution_packet 组装任务合同、工具目录、动态状态、读写记录
-> 模型每轮选择 tool_call / respond / ask_user / block
-> tool_control_plane / tool_runtime 执行工具
-> observation / file_state / projection 回灌给模型和前端
```

关键代码位置：

- `backend/harness/entrypoint/runtime_facade.py`：普通轮入口、任务启动、active work 对接。
- `backend/harness/loop/single_agent_turn.py`：单轮模型调度、action 解析、request_task_run 分发。
- `backend/harness/loop/task_lifecycle.py`：从 `request_task_run` 创建任务生命周期。
- `backend/harness/loop/task_executor.py`：持续任务执行主循环。
- `backend/harness/runtime/tool_catalog_manifest.py`：工具能力如何投影给模型。
- `backend/runtime/tool_runtime/native_tools.py`：native 工具实际执行。
- `backend/runtime/memory/file_state_authority.py`：文件读取、搜索、写入状态记录。

## 三、已确认的断裂点

### 1. agent_todo schema 与 prompt 不一致

`backend/capability_system/tools/tool_units/agent_todo_tool.py` 的 schema 要求：

```text
items[].status = pending | in_progress | completed
todo_id = start / complete / update_status / remove 的目标 id
```

但 `backend/prompt_library/tool_prompts.py` 中出现“active 项”的表述，容易诱导模型输出：

```json
{"status": "active", "id": "1"}
```

这与 schema 不匹配，会触发 `tool_input_schema_validation_failed`。

目标修复：

- 将 prompt 中 todo 状态统一为 `in_progress`，不再用 `active` 描述 todo item status。
- 明确 `todo_id` 是工具字段，不使用 `id`。
- 工具可见 schema summary 必须暴露 enum 和关键字段。

### 2. 子 agent ID 不可执行

runtime profile 允许的是 canonical ID：

```text
agent:codebase_searcher
agent:verifier
agent:web_researcher
...
```

但 prompt、规则和探索建议里存在裸名：

```text
codebase_searcher
web_researcher
```

当前 `normalize_agent_id()` 不会把裸名 `codebase_searcher` 规范为 `agent:codebase_searcher`，因此模型按 prompt 调用时会被 runtime 拒绝：`target_subagent_not_allowed`。

目标修复：

- 所有模型可见 prompt、advisory、completion verifier 指令统一使用 canonical ID。
- `allowed_subagent_ids` 必须直接投影到模型可见运行边界中。
- `spawn_subagent.target_agent_id` 的说明必须写成“只能使用 allowed_subagent_ids 中的值”。

### 3. 工具 schema 投影不够明确

`backend/harness/runtime/tool_catalog_manifest.py` 已有 `input_schema_summary` 机制，但 live packet 中可见 summary 不够稳定、不够显眼，模型不能可靠看到关键字段和枚举。

目标修复：

- 工具 catalog 的模型可见合同必须包含：
  - required inputs
  - optional inputs
  - enum
  - default
  - additionalProperties / 禁止字段提示
- 高风险和高频工具必须有专门摘要：
  - `agent_todo`
  - `write_file`
  - `edit_file`
  - `spawn_subagent`
  - `read_file`
  - `search_text`

### 4. 读工具鼓励继续读，缺少足够则行动的信号

`read_file` 已经具备：

- `start_line`
- `line_count`
- `total_lines`
- `end_line`
- `next_start_line`
- `has_more`
- `content_sha256`

`file_state_authority` 已经记录：

- read ranges
- search hits
- write events
- coverage
- next suggested read

问题在于动态投影更容易告诉模型“还有下一段可读”，但没有同等强度地告诉模型：

```text
当前任务相关窗口已经足够，可以停止读取，进入 edit/write/verify。
```

目标修复：

- 从“文件覆盖率”升级为“任务相关证据覆盖率”。
- 增加 read stop advisory，作为模型可见的非阻塞执行建议。
- 搜索结果给出 recommended read windows，而不是只给匹配行。

## 四、读工具精准化设计

### 1. 目标读取协议

目标协议应为：

```text
search/list/code_outline 定位候选
-> read_file 读取目标窗口
-> file_state 记录已读范围、hash 和读取意图
-> task_state 判断目标相关信息是否足够
-> 足够则进入 edit/write/verify，不继续爬全文
```

### 2. 增加 read_intent

读工具建议支持或投影读取意图：

```json
{
  "path": "basketball-game.html",
  "start_line": 330,
  "line_count": 90,
  "read_intent": "edit_target"
}
```

可选值建议：

```text
edit_target
verify_behavior
understand_api
locate_symbol
inspect_dependency
recover_failure
```

这样 file_state 不只知道“读了哪里”，还知道“为什么读”。

### 3. 增加 target_coverage

任务状态中应投影任务相关目标覆盖，而不是只投影文件覆盖：

```json
{
  "target": "rim collision and scoring logic",
  "paths": ["basketball-game.html"],
  "covered_ranges": [{"start_line": 330, "end_line": 410}],
  "sufficient_for": ["edit"],
  "missing_for": ["browser_verification"]
}
```

### 4. 增加 read_stop_advisory

当连续读/搜超过阈值时，系统不应硬阻塞模型，而应提供更成熟的观察：

```json
{
  "kind": "read_stop_advisory",
  "non_blocking": true,
  "current_assessment": "目标相关窗口已覆盖 power mapping、mouse aim、rim collision。",
  "recommended_next_actions": ["edit_file", "write_file", "verify"],
  "continue_reading_only_if": [
    "发现新的错误位置",
    "验证失败需要定位原因",
    "当前窗口不足以编辑"
  ]
}
```

这仍然遵循：系统提供观察和资源边界，大模型负责最终调度。

### 5. 搜索结果输出 recommended_read_windows

`search_text` 当前返回匹配行，但应额外给出可执行的读取窗口建议：

```json
{
  "recommended_read_windows": [
    {
      "path": "basketball-game.html",
      "start_line": 220,
      "line_count": 80,
      "reason": "constants and aiming variables"
    },
    {
      "path": "basketball-game.html",
      "start_line": 340,
      "line_count": 90,
      "reason": "shot physics and scoring"
    }
  ]
}
```

这样模型不需要一条条搜、一段段猜。

## 五、目标能力架构

建议整理为单向能力链：

```text
Capability Registry
-> Runtime Tool Catalog
-> Model Visible Tool Contract
-> Action Schema
-> Tool Runtime Validation
-> Observation + Recovery Contract
-> Dynamic Task State
-> Public Projection
```

职责划分：

- Capability Registry：定义真实工具、schema、operation、权限上限。
- Runtime Tool Catalog：只投影当前可用工具。
- Model Visible Tool Contract：字段必须可执行、可验证、无歧义。
- Prompt：告诉模型什么时候用，不写开发式说明。
- Model：做语义判断和调度。
- Admission：校验本轮 action 是否允许，不重写用户意图。
- Tool Runtime：执行工具并返回真实观察。
- Dynamic Task State：总结已读、已写、已验证、缺口和下一步候选。
- Public Projection：只展示用户可见进展，不泄露系统硬编码状态词。

## 六、项目目录外成熟实现对照：Codex 与 Claude Code 的读工具设计

本节依据项目目录外源码检查，参考路径包括：

- `D:\AI应用\openai-codex\codex-rs\core\gpt_5_2_prompt.md`
- `D:\AI应用\claude-code-nb-main\tools\FileReadTool\prompt.ts`
- `D:\AI应用\claude-code-nb-main\tools\FileReadTool\limits.ts`
- `D:\AI应用\claude-code-nb-main\tools\FileReadTool\FileReadTool.ts`
- `D:\AI应用\claude-code-nb-main\tools\GrepTool\prompt.ts`
- `D:\AI应用\claude-code-nb-main\tools\GrepTool\GrepTool.ts`
- `D:\AI应用\Claude-Code-Source-Study-main\docs\05-对话循环.md`
- `D:\AI应用\Claude-Code-Source-Study-main\docs\10-BashTool-深度剖析.md`
- `D:\AI应用\Claude-Code-Source-Study-main\docs\23-Memory系统.md`

### 1. Codex：shell-first，但靠强规则降低乱读

Codex 的读/搜能力不是 Claude Code 式的专用 `Read` 工具，而是主要依赖 shell 工具完成读取、搜索和检查。它的成熟点不在“专用读工具 schema”，而在模型可见的行为纪律：

- 搜索文本或文件时优先 `rg` / `rg --files`，不用慢速替代品。
- 不用 Python 脚本输出大段文件内容，避免绕过可观察工具边界和浪费上下文。
- 文件读取、搜索、列目录、`git show`、`nl`、`wc` 等只读操作尽量并行执行。
- 修改文件使用 `apply_patch`，修改后不反复重读同一文件；工具失败会直接暴露，不需要用重复读取确认每一步。

对本项目的启发：

- 如果保留 dedicated `read_file` / `search_text`，就不能只让它们“能用”，还要让模型明确知道什么时候使用它们、什么时候并行、什么时候停止读取。
- Codex 的关键不是阻止 agent 读，而是给它更清楚的低成本路径：先搜、并行读关键窗口、完成后进入编辑和验证。
- 对写入后的重复读要做成本提示：除非需要验证具体文本或错误定位，模型不应把“重读刚改过的文件”当作默认确认动作。

### 2. Claude Code：专用 Read / Grep / Glob，工具合同非常强

Claude Code 的读工具设计更适合作为本项目 dedicated tool 的直接参照。它把读取、搜索和 glob 列表拆成独立工具，并明确告诉模型：文件搜索用 `Glob`，内容搜索用 `Grep`，读文件用 `Read`，不要通过 Bash 调 `find`、`grep`、`rg`、`cat`、`head`、`tail` 来替代。原因不是模型不能执行 shell，而是专用工具有更稳定的 UI、权限、分页、结果压缩和错误语义。

`Read` 工具的关键合同：

- 工具名是 `Read`，只读文件，不读目录。
- `file_path` 必须是绝对路径。
- 默认最多从文件开头读取 `2000` 行。
- 支持 `offset` / `limit` 精准读窗口。
- 输出为 `cat -n` 风格，行号从 1 开始。
- 对大文件有字节上限和输出 token 上限，超限时要求模型改用 `offset` / `limit` 或搜索。
- 支持图片、PDF、Jupyter notebook 等多模态文件类型，并对 PDF 页数做专门限制。
- 工具声明 `isReadOnly() = true`、`isConcurrencySafe() = true`。
- 做路径规范化和读权限检查，避免相对路径、`~`、hook allowlist 等绕过权限。
- 对危险设备路径、二进制文件、超大内容等有明确拒绝路径。
- 有 `FILE_UNCHANGED_STUB`：同一范围文件没有变化时，不重复回灌全文，而是告诉模型使用之前的读取结果。

`Grep` 工具的关键合同：

- 基于 ripgrep，但模型调用的是 `Grep`，不是 Bash 里的 `rg`。
- schema 暴露 `pattern`、`path`、`glob`、`type`、`output_mode`、上下文行、大小写、`head_limit`、`offset`、`multiline`。
- 默认 `output_mode` 是 `files_with_matches`，避免一开始就输出大量正文。
- 默认 `head_limit = 250`，只有显式传 `0` 才无限制。
- 输出会带分页信息，模型能继续用 `offset` 翻页。
- `files_with_matches` 会按修改时间排序，优先暴露近期相关文件。
- 搜索超时作为真实失败传播，不把未完成搜索伪装成无匹配。
- 同样声明只读、并发安全。

Claude Code 的执行层还把工具分为并发安全和非并发安全：`Grep`、`Glob`、`FileRead` 可以并行；写入和 Bash 类高风险工具串行。这说明成熟 agent 不是靠“多读几次”提升准确性，而是靠工具合同、并发分区、分页和明确失败语义提升读取效率。

### 3. 两种方案对本项目的取舍

本项目不应照搬 Codex 的 shell-first，因为我们已经有 `read_file`、`search_text`、文件状态权威和前端投影层。继续让模型绕到 terminal 读/搜，会削弱权限、投影、读记录和任务状态统计。

本项目也不应完全照搬 Claude Code 的绝对路径策略。Claude Code 是本机 CLI 工具，绝对路径方便权限匹配；本项目有 workspace、任务投影和前端展示，继续使用项目相对路径更适合 UI 和跨端协议。但必须在 runtime 内部规范化为绝对路径，并把 workspace root、路径规范和拒绝规则清楚投影给模型。

推荐方向：

- 借 Claude Code 的 dedicated tool contract：读、搜、列文件必须是模型可见的一等能力。
- 借 Claude Code 的 `offset` / `limit`、行号、分页、上限、只读、并发安全、未变化 stub、权限拒绝和错误分类。
- 借 Codex 的执行纪律：优先快速搜索、并行只读、不要 Python 大段读、写后不要无意义重读。
- 不借 Codex 的 shell-first 作为主路径；terminal 只保留给测试、构建、命令行验证和专用工具无法表达的操作。
- 不借 Claude Code 的“默认鼓励整文件读取”作为唯一策略；本项目应该根据任务状态在小文件整读和大文件目标窗口之间动态选择。

### 4. 本项目读工具目标合同

建议将 `read_file` 的模型可见合同升级为：

```json
{
  "tool": "read_file",
  "read_only": true,
  "concurrency_safe": true,
  "required": ["path"],
  "optional": {
    "start_line": "1-based positive integer",
    "line_count": "positive integer",
    "read_intent": "edit_target | verify_behavior | understand_api | locate_symbol | inspect_dependency | recover_failure"
  },
  "path_policy": "Use project-relative paths shown by search/list results. Runtime normalizes to an absolute path inside the workspace.",
  "output_contract": {
    "content": "line-numbered text window",
    "start_line": "first returned line",
    "end_line": "last returned line",
    "total_lines": "file total lines",
    "has_more": "whether later lines exist",
    "next_start_line": "next readable line when has_more is true",
    "content_sha256": "hash of returned content window",
    "file_unchanged": "true when exact requested range is unchanged since the last read and content is omitted"
  }
}
```

`search_text` 的模型可见合同应升级为：

```json
{
  "tool": "search_text",
  "read_only": true,
  "concurrency_safe": true,
  "required": ["query"],
  "optional": {
    "path": "project-relative directory or file",
    "glob": "file glob",
    "output_mode": "content | files_with_matches | count",
    "context": "lines before and after match",
    "case_sensitive": "boolean",
    "head_limit": "default bounded result count",
    "offset": "pagination offset"
  },
  "output_contract": {
    "matches": "bounded results with line numbers when available",
    "applied_limit": "present when truncated",
    "applied_offset": "present when paginated",
    "recommended_read_windows": "specific read_file windows derived from hits"
  }
}
```

### 5. 读工具链路的正确闭环

目标链路应固定为：

```text
list/search 定位候选
-> read_file 读取任务相关窗口
-> file_state_authority 记录 path、range、hash、intent、mtime
-> task_state 评估目标证据是否足够
-> 如果足够，投影非阻塞 read_stop_advisory
-> 模型自行选择 edit/write/verify 或继续读取
-> 写入后记录 write event，并使旧 read cache 失效
-> 验证失败时按失败位置重新 search/read
```

系统不能硬堵 agent，也不能把内部状态词投影成正文；系统只能提供事实、资源、限制、建议和边界控制。是否继续读、是否开始编辑、是否收口，仍由模型基于当前任务判断。

### 6. 必须补齐的结构能力

读工具精准化不是单个工具参数问题，应补齐这些结构能力：

- `read_file` 增加 read cache：同一路径、同一范围、同一 mtime/hash 未变化时返回 `file_unchanged`，不重复塞正文。
- `read_file` 增加 `read_intent`，让后续任务状态能区分“为了编辑读”“为了验证读”“为了恢复失败读”。
- `search_text` 增加 `recommended_read_windows`，把匹配行转换成可直接执行的读取窗口。
- 工具目录投影 `read_only`、`concurrency_safe`、`path_policy`、`output_contract`，让模型知道哪些工具可以批量并行。
- prompt 中明确：读/搜/list 优先用 dedicated tools；terminal 不作为常规读搜路径。
- 动态状态增加 `read_stop_advisory`，但它必须是非阻塞观察，不是系统强制终止。
- 写入成功后使相关 read cache 失效；验证失败后允许重新读取失败相关窗口。
- 对读取失败统一分类：参数、路径、权限、工具、环境、合同，不能只给模糊错误文本。

### 7. 结构测试要求

本项目禁止语义测试，因此读工具优化应只做结构/合同测试：

- schema 投影包含 required、optional、enum、default、read_only、concurrency_safe。
- `read_file` 同范围未变化时返回结构化 `file_unchanged`，不返回全文。
- 写入同文件后再次读取不会错误命中旧 cache。
- `search_text` 命中结果能生成 `recommended_read_windows`，窗口不越界。
- 大结果必须有 `applied_limit` / `applied_offset` 或等价分页字段。
- prompt 文本中不存在鼓励 terminal 替代 dedicated read/search 的规则。
- projection 层不把 `read_stop_advisory`、系统控制词、工具观察硬编码词当作正文输出。

## 七、实施计划

### 阶段 1：修正能力合同

文件范围：

- `backend/prompt_library/tool_prompts.py`
- `backend/prompt_library/rules.py`
- `backend/prompt_library/environment_lifecycle_prompts.py`
- `backend/harness/loop/task_executor.py`
- `backend/agent_system/identity.py`（仅在决定支持裸名 alias 时修改）

动作：

- 删除 todo prompt 中“active 项”的歧义表达。
- 统一使用 `in_progress`。
- 所有可调用子 agent ID 改为 canonical ID。
- 探索 advisory 不再输出不可执行短名。

### 阶段 2：增强工具 catalog 投影

文件范围：

- `backend/harness/runtime/tool_catalog_manifest.py`
- `backend/harness/runtime/assembly.py`
- 相关结构测试

动作：

- 展开 schema summary。
- 确保 enum/default/required/optional 都可见。
- 对 `agent_todo`、`write_file`、`spawn_subagent` 增加稳定摘要。

### 阶段 3：增强读工具精准投影

文件范围：

- `backend/runtime/tool_runtime/read_file_window.py`
- `backend/runtime/tool_runtime/native_tools.py`
- `backend/runtime/tool_runtime/tool_result_envelope.py`
- `backend/runtime/memory/file_state_authority.py`
- `backend/harness/runtime/dynamic_context/task_state_projector.py`
- `backend/harness/runtime/dynamic_context/tool_result_projector.py`

动作：

- 增加或投影 `read_intent`。
- 增加 `target_coverage`。
- 增加 `read_stop_advisory`。
- `search_text` 增加 recommended read windows。

### 阶段 4：结构测试

只做结构/合同测试，不做语义测试。

建议新增或调整测试：

- prompt 不包含 `status: active` 作为 todo 指导。
- prompt 不包含裸 `codebase_searcher` 作为可调用 ID。
- tool catalog 暴露 `agent_todo.items[].status` enum。
- tool catalog 暴露 `write_file.allow_overwrite`。
- subagent prompt 中可调用 ID 与 runtime policy 一致。
- read projection 能输出 next read / stop read / edit readiness 三类结构字段。

## 八、当前篮球任务的归因

当前篮球任务不是没有开启 TaskRun。监控显示它已经是持续任务，并处于 running。

真正问题是：

```text
任务执行中反复 read/search
-> agent_todo 调用因 schema 不匹配失败
-> spawn_subagent 调用因 target_agent_id 不匹配失败
-> 模型回退到继续 read/search
-> file_state 显示 write_event_count = 0
-> 任务无法进入稳定写入、验证和收口阶段
```

因此，收口异常是结果，不是根因。根因是能力合同断裂和读取策略缺少“足够则行动”的任务级判断。

## 九、验收标准

完成优化后，应满足：

- 模型可见能力与 runtime 实际可执行能力一致。
- todo 工具不会因 `active/id` 这类字段误导而失败。
- 子 agent 调用使用 runtime 允许的 canonical ID。
- `write_file.allow_overwrite` 在模型可见工具合同中明确存在。
- 连续读取后，系统向模型提供“继续读 / 停止读 / 转入编辑或验证”的结构化观察。
- 读工具不再推动模型无目标爬全文，而是帮助模型精准定位、最小读取、证据闭环。
- 边缘控制只提供资源和安全边界，不替模型做语义决策，不把硬编码状态词投影成 assistant 正文。
