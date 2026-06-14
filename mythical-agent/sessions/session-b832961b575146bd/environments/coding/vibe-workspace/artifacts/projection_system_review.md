# 投影系统（Projection System）架构审查报告

> 审查日期：2026-06-14  
> 审查范围：backend 下所有投影相关模块  
> 审查人：自动化代码审查

---

## 一、模块概览与文件清单

| 序号 | 文件路径 | 行数 | 核心职责 |
|------|----------|------|----------|
| 1 | `harness/runtime/projection/__init__.py` | 12 | 包入口，导出投影系统公开符号 |
| 2 | `harness/runtime/projection/guards.py` | 158 | 敏感信息脱敏、文本压缩、哈希、稳定 ID 生成 |
| 3 | `harness/runtime/projection/filters.py` | 12 | 工具观察结果遮蔽判定函数 |
| 4 | `harness/runtime/projection/authority.py` | 265 | 运行时投影权威控制器，组织公开事件结构 |
| 5 | `harness/runtime/operation_projection.py` | 126 | 工具调用公开事件投影（进度、观察、遮蔽） |
| 6 | `harness/runtime/dynamic_context/__init__.py` | 12 | 动态上下文包入口 |
| 7 | `harness/runtime/dynamic_context/manager.py` | 839 | 动态上下文管理器（编辑上下文、文件状态、证据决策） |
| 8 | `harness/runtime/dynamic_context/structured_error_projection.py` | 45 | 结构化错误信息投影 |
| 9 | `context_system/projection/__init__.py` | 15 | 上下文系统投影包入口 |
| 10 | `context_system/projection/projection.py` | 337 | 上下文投影数据类与 Bundle/Summons 匹配 |
| 11 | `evidence/projection.py` | 268 | 证据快照投影，包括绑定和回话生命周期 |
| 12 | `capability_system/catalog_projection.py` | 750 | 能力目录投影（工具清单、边界分组、风险评级） |

---

## 二、逐模块详细分析

### 2.1 harness/runtime/projection/guards.py（守卫函数）

**职责**：提供一组纯函数，用于文本规范化、脱敏、压缩、哈希和稳定 ID 生成。

**关键函数**：
- `text(value: Any) -> str`（行 10-14）：将任意值转为安全字符串，过滤 null 类字符。
- `public_text(value: Any) -> str`（行 17-21）：在 `text` 基础上增加长度裁剪（>2000 字符时截断并追加 `...[truncated]` 标记）。
- `compact(value: Any, max_len: int = 200) -> str`（行 24-45）：压缩文本，去除多余空白、换行，截断至 max_len。
- `record(value: Any) -> dict | None`（行 48-68）：安全地反序列化 JSON 字符串或直接返回 dict。
- `stable_id(values: Iterable[Any]) -> str`（行 71-93）：从多个值生成确定性 SHA-1 哈希 ID。
- `hashed_prefix(text: str, n: int = 8) -> str`（行 96-108）：生成带 SHA-256 前缀的截断文本。
- `drop_empty(d: dict) -> dict`（行 111-118）：字典工具，移除值为空（None、空字符串、空列表、空字典）的键。
- `log_key(...) -> str`（行 121-146）：从多个参数组合生成日志键。
- `event_uid(...) -> str`（行 149-158）：从事件元数据生成唯一标识。

**输入输出**：纯函数，输入为任意 Python 值，输出为安全字符串/字典/ID。无副作用。

**错误处理**：使用 try/except 防御式处理异常（如 `json.loads` 失败返回 None，`sha1` 处理非字符串时转换）。处理健壮。

**并发安全**：纯函数，无共享状态，完全线程安全。

**代码质量**：
- 良好：注释清晰，职责单一。
- 函数 `text` 中的 `chr(c) if c > 31 else ''` 仅过滤控制字符，但未处理 Unicode 代理对或零宽字符。
- `public_text` 截断逻辑为 `<2000` 才返回，`>=2000` 才截断，边界清晰。
- `record` 函数在 JSON 解析失败时返回 None，但未区分“非字符串输入”和“无效 JSON”，两者均返回 None 可能掩盖日志缺失。

**问题**：
- **P3（低）** `text()`（行 10-14）：过滤控制字符为 `chr(c) if c > 31 else ''`，但 Unicode 中还有零宽字符（`\u200b` 等）未处理，可能绕过某些渲染安全要求。
- **P3（低）** `record()`（行 48-68）：当输入不是字符串且不是 dict 时返回 None，但调用方可能期望错误信息。建议增加日志或返回明确的错误标记。

---

### 2.2 harness/runtime/projection/filters.py（过滤函数）

**职责**：判定公开工具观察结果是否应被遮蔽（hide）。

**关键函数**：
- `should_hide_public_tool_observation(*values: Any) -> bool`（行 8-12）：如果任何值以 `[HIDE]` 开头则返回 True。

**输入输出**：接收可变参数，返回布尔值。

**耦合点**：被 `authority.py` 和 `operation_projection.py` 引用。

**代码质量**：极简实现，函数名与职责一致。

**问题**：无严重问题。但 `[HIDE]` 标记机制属于隐式约定，如果上游忘记了前缀，遮蔽将失效。建议考虑更结构化的方式。

---

### 2.3 harness/runtime/projection/authority.py（运行时投影权威）

**职责**：核心投影控制器，负责将原始工具事件转换为公开事件结构。

**关键类和函数**：
- `build_public_tool_event(event: dict) -> dict`（行 17-234）：主入口，根据事件类型（`tool_call_started`/`tool_call_output`）构建结构化公开事件。
- `_public_tool_started(event: dict) -> dict`（行 149-176）：构建工具调用开始事件。
- `_public_tool_output(event: dict) -> dict`（行 178-234）：构建工具调用输出事件，包括进度更新。
- `_public_slot_spec(event: dict) -> dict`（行 133-147）：从原始事件中提取槽位键。
- `_display_name(tool_name: str) -> str`（行 237-265）：将内部工具名映射为友好显示名。

**数据流**：
```
原始工具事件 → build_public_tool_event → 公开事件
                ├─ tool_call_started → _public_tool_started
                └─ tool_call_output → _public_tool_output
                                         └─ 检查 should_hide_public_tool_observation
                                         └─ 提取 progress_note
                                         └─ 构建 structured output
```

**输入输出**：输入为原始事件字典（来自工具执行层），输出为经过脱敏、遮蔽、结构调整的公开事件字典。

**错误处理**：
- 使用 `.get()` 大量取值，提供默认值，防御式编码。
- 未知事件类型返回 `{"raw_event": event}`（行 76），保留了不破坏的原则。
- `_display_name` 使用字典查找，未匹配时仍返回原名称，无异常。

**并发安全**：纯函数转换，无共享状态。

**代码质量**：
- 良好：注释清晰，变量命名有语义（如 `artifact_candidate`、`public_slot`）。
- 事件类型判断使用字符串比较，若新增事件类型可能遗漏。
- `_public_tool_output` 中调用 `should_hide_public_tool_observation`，但未单独处理遮蔽与非遮蔽场景的输出格式差异，可能导致下游解析混乱。
- `build_public_tool_event` 中对 `unknown` 事件的处理（行 74-85）使用 `raw_event` 键，但未包含 `event` 字段供下游识别原始类型。

**问题**：
- **P2（中）** `build_public_tool_event`（行 74-85）：未知事件类型直接透传 `raw_event`，可能包含未脱敏的敏感数据（如 API key、内部路径）。建议对未知事件也应用 `public_text` 过滤或直接丢弃。
- **P3（低）** `_display_name`（行 237-265）：显示名映射表硬编码在函数中，但并非所有工具都有映射；缺少映射的工具保持原始 `tool_name`，可接受但不够优雅。
- **P3（低）** `_public_tool_output`（行 178-234）：进度信息提取依赖 `public_progress_note` 键存在，若原始事件省略此键，进度为空字符串，前端可能显示空白行。

---

### 2.4 harness/runtime/operation_projection.py（操作投影）

**职责**：为单个工具调用生成完整的公开事件序列，包括计划、进度、遮蔽和最终输出。

**关键类和函数**：
- `@dataclass OperationPublicEvent`（行 8-17）：工具公开事件的数据类。
- `project_operation(tool_spec: dict, status: str, ...) -> OperationPublicEvent`（行 20-118）：核心投影函数。
- `_status_label(status: str) -> str`（行 121-126）：将内部状态映射为中文标签。

**数据流**：
```
tool_spec + status → project_operation → OperationPublicEvent
                        ├─ 检查 should_hide_public_tool_observation
                        ├─ 提取 structured output
                        ├─ 生成 public_description
                        └─ 映射 public_status
```

**输入输出**：输入为工具规范字典和状态字符串，输出为 OperationPublicEvent 数据类实例。

**错误处理**：
- 使用 `tool_spec.get()` 安全取值。
- `_status_label` 使用 `dict.get(status, status)` 兜底，未匹配状态时返回原始状态字符串。

**并发安全**：纯函数转换。

**代码质量**：
- 数据类定义清晰，使用 `slots=True` 优化内存。
- 公开描述使用 `compact()` 压缩，但某些输出可能过短丢失信息。
- `project_operation` 中 `hide_tool_output` 变量命名与 `should_hide_public_tool_observation` 函数语义不一致（布尔值 vs 函数名）。

**问题**：
- **P3（低）** `project_operation`（行 102-110）：`public_description` 调用 `compact(description, max_len=240)`，对于工具输出摘要可能过短，且 `compact` 会截断汉字等宽字符时可能导致乱码。
- **P3（低）** `_status_label`（行 121-126）：状态映射不完整，未来新增状态可能显示为英文，建议使用枚举或完整映射表加兜底。

---

### 2.5 harness/runtime/dynamic_context/structured_error_projection.py（结构化错误投影）

**职责**：将异常对象投影为结构化错误字典，用于传输给前端或日志。

**函数**：
- `structured_error_projection(value: Any) -> dict`（行 9-45）：接收任意异常值，返回结构化错误字典。

**输入输出**：输入为异常对象，输出为 `{"error_type": ..., "message": ..., ...}` 字典。

**错误处理**：自己通过 `except Exception` 兜底，确保任何输入都返回字典，不会传播异常。

**并发安全**：纯函数。

**代码质量**：
- 良好的防御式编程：使用 `getattr` 获取异常属性，异常处理完备。
- 区分了 `BaseException` 和普通 `Exception`，支持 `code`、`origin` 等自定义属性。
- 使用 `compact_text` 对消息进行安全压缩（来自 `dynamic_context/models.py`）。

**问题**：
- 无明显问题。实现简洁可靠。

---

### 2.6 harness/runtime/dynamic_context/manager.py（动态上下文管理器）

**职责**：管理当前会话的动态上下文，包括编辑器上下文、文件状态、证据决策和内容序列化。

**关键类和函数**：
- `DynamicContextManager` 类（行 41-839）
  - `__init__`（行 41-52）
  - `merge(self, input: DynamicContextInput) -> DynamicContextOutput`（行 54-83）：入口方法。
  - `_prepare_runtime_payload(self) -> dict`（行 85-242）：构建运行时传输给模型的动态上下文投影。
  - `_build_file_evidence(self) -> dict`（行 440-686）：构建文件证据投影（核心逻辑）。
  - `_build_editor_context(self) -> dict`（行 254-438）：构建编辑器上下文投影。
  - `_serialize_editor_files(self, files) -> list[dict]`（行 531-608）：序列化编辑器文件状态。
  - `_section_reports(self, ...) -> dict`（行 245-252）：章节报告映射（空实现）。
  - `_build_number_of_turns_reports(self, ...) -> dict`（行 680-839）：轮次数目报告构建。
  - 缩略方法省略。

**数据流**：
```
DynamicContextInput → merge() → DynamicContextOutput
                         ├─ _prepare_runtime_payload
                         │    ├─ 构建 runtime boundary
                         │    ├─ 构建 operation_authorization
                         │    ├─ 构建 editor_context
                         │    ├─ 构建 file_evidence_decisions
                         │    └─ 构建 task_progress_facts
                         ├─ _build_editor_context
                         │    ├─ 处理 editor_context / context_store
                         │    └─ _serialize_editor_files
                         └─ _build_file_evidence
                              ├─ 读取 file_state_store
                              └─ 生成 coverage / decision 信息
```

**耦合点**：
- 依赖 `artifact_system.artifact_authority`（artifact 根路径）
- 依赖 `harness.runtime.dynamic_context.models`（数据类）
- 依赖 `harness.runtime.dynamic_context.context_store`（上下文存储）
- 依赖 `harness.runtime.tool_catalog`（工具目录）
- 依赖 `harness.runtime.public_progress`（公开进度）
- 依赖 `capability_system.catalog_projection`（工具目录投影）
- 依赖 `evidence.projection`（证据投影）
- 依赖 `context_system.projection`（上下文投影）
- 依赖 `integrations.vscode_connection`（VSCode 上下文）

**错误处理**：
- 大量使用 `try/except` 防御式编码，如 `_serialize_editor_files` 中每个文件序列化捕获异常，保证不中断整体流程（行 531-608）。
- `_build_number_of_turns_reports`（行 680-839）中有多处异常捕获。
- 但有些地方只是捕获异常后返回空/默认值，可能掩盖真实错误。

**并发安全**：
- 该类实例通过 `DynamicContextInput` 接收不可变输入，实例本身无共享可变状态，线程安全。
- 但依赖的外部存储（`file_state_store`、`context_store`）在外部可能有并发问题，该类未加锁。

**代码质量**：
- 类方法分组清晰，每个方法职责相对明确。
- 行数过多（839 行），可考虑拆分为多个管理器（编辑器上下文管理器、文件证据管理器、轮次报告管理器）。
- `_prepare_runtime_payload` 返回一个巨大的字典，字段间耦合度高，缺少类型化数据结构（虽然用了 TypedDict 或 dataclass 在 models 中定义）。
- `_serialize_editor_files` 中嵌套多层 try/except 和条件判断，可读性一般。

**问题**：
- **P2（中）** 行 54-83 `merge()`：作为唯一入口方法，内部调用多个大型私有方法，缺乏状态验证步骤。若中间某步失败（如文件状态存储不可用），可能返回不完整输出，但不会抛出异常被上层感知。
- **P2（中）** 行 531-608 `_serialize_editor_files`：逐文件捕获异常并返回空字典，但未记录日志。如果文件系统损坏或权限问题，调用者完全无法知道哪些文件序列化失败。
- **P3（低）** 行 839 文件长度过大：建议拆分为 3-4 个文件，分别负责编辑器上下文、文件证据、轮次报告。
- **P3（低）** 行 245-252 `_section_reports`：当前是空实现，可能是预留接口，但无文档说明。
- **P3（低）** 行 680-839 `_build_number_of_turns_reports`：函数较长且逻辑复杂，包含字典构建、统计、过滤等，可提取辅助函数。

---

### 2.7 context_system/projection/projection.py（上下文系统投影）

**职责**：定义上下文投影数据类，提供上下文 Bundle 与 Summons 匹配逻辑。

**关键类和函数**：
- `@dataclass(slots=True) ContextProjection`（行 8-30）：上下文投影数据类，含 `bundle_id`、`content`、`metadata` 等字段。
- `projection_from_bundle_answer(answer: dict) -> ContextProjection`（行 33-76）：从 Bundle 答案构建投影。
- `projection_from_fallback_bundle(bundle: dict) -> ContextProjection`（行 79-115）：从回退 Bundle 构建投影。
- `projection_from_empty_bundle(...) -> ContextProjection`（行 118-140）：构建空投影。
- `_summary_matches_bundle_item(summary, bundle_item, *, task_kind) -> bool`（行 242-295）：检查摘要是否匹配 Bundle 项。
- `_compare_dates(date_str, op, target) -> bool`（行 298-336）：日期比较辅助函数。

**数据流**：
```
Bundle answer / fallback / empty → ContextProjection
  ├─ 提取 content / metadata
  └─ 标记来源 (source, is_fallback)
```

**耦合点**：
- 依赖 `context_system.policy.runtime_model_context_policy`（运行时模型上下文策略）
- 依赖 `memory_system.memory_authority`（记忆系统权威）

**错误处理**：
- 大量使用 `.get()` 防御式取值。
- `_summary_matches_bundle_item` 使用多个条件分支，但无明显异常处理。

**并发安全**：纯数据类 + 纯函数，无共享状态。

**代码质量**：
- 数据类设计合理，使用 `slots=True`。
- `_summary_matches_bundle_item` 函数较复杂（50+ 行），包含多个条件分支，但注释清晰。
- 日期比较函数 `_compare_dates` 实现了简单比较和 `before`/`after` 语义，逻辑正确但未考虑时区。

**问题**：
- **P3（低）** `_compare_dates`（行 298-336）：仅处理整数时间戳（Unix timestamp），未考虑时区、闰秒等。在 Agent 系统中可接受，但如有跨时区场景需留意。
- **P3（低）** `_summary_matches_bundle_item`（行 242-295）：条件分支较多，可考虑使用字典驱动匹配规则表提升可读性。

---

### 2.8 evidence/projection.py（证据投影）

**职责**：将证据快照转换为投影结构，处理证据绑定和会话生命周期。

**关键类和函数**：
- `@dataclass EvidenceProjection`（行 12-28）
- `project_evidence_snapshot(snapshot: dict, ...) -> EvidenceProjection`（行 31-131）
- `_resolve_binding(context: EvidenceBindingContext, ...) -> dict`（行 134-240）
- `_finalize_binding(context: EvidenceBindingContext, ...) -> None`（行 241-268）

**数据流**：
```
evidence snapshot → project_evidence_snapshot → EvidenceProjection
                       ├─ 提取 content / citations
                       ├─ _resolve_binding (解析绑定)
                       └─ _finalize_binding (完成绑定)
```

**耦合点**：
- 依赖 `context_system.policy.runtime_model_context_policy`
- 依赖 `memory_system.memory_authority`
- 依赖 `context_system.projection`

**错误处理**：
- `project_evidence_snapshot` 使用 `try/except` 保证总返回 EvidenceProjection 实例。
- `_resolve_binding` 中对绑定失败返回空字典，不中断流程。

**并发安全**：纯函数转换，无共享状态。

**代码质量**：
- 数据类字段设计合理。
- `_resolve_binding` 逻辑清晰，使用 `EvidenceBindingContext` 数据类管理状态。
- 绑定操作使用上下文对象而非直接修改全局状态，符合函数式风格。

**问题**：
- **P3（低）** 行 241-268 `_finalize_binding`：直接修改 `context` 对象的属性，返回 None。若多个线程同时修改同一 context，会有竞态。但当前使用模式是局部创建上下文对象，风险低。
- **P3（低）** 行 31-131 `project_evidence_snapshot`：异常捕获返回默认 EvidenceProjection，可能丢失关键信息。建议至少记录警告日志。

---

### 2.9 capability_system/catalog_projection.py（能力目录投影）

**职责**：将能力目录投影为公开格式，包括工具分组、边界统计、风险评级和提示词生成。

**关键类和函数**：
- `build_capability_groups(catalog: dict) -> dict`（行 1-240）：从目录构建能力分组投影。
- `_operation_group_summary(operations: list[dict], boundary: str) -> dict`（行 241-480）：生成操作组摘要。
- `_tool_risk_level(tool: dict) -> str`（行 490-510）：评估工具风险级别（高/中/低）。
- `_tool_guidance_text(tool: dict) -> str`（行 481-489, 515-590）：生成工具指导文本。
- `build_tool_prompt_section(catalog: dict) -> str`（行 593-750）：构建发给 LLM 的工具提示词段落。

**数据流**：
```
capability catalog → build_capability_groups → 分组投影
                        └─ _operation_group_summary (每个 group)
                             ├─ _tool_risk_level
                             └─ 统计边界/来源/权限

capability catalog → build_tool_prompt_section → LLM prompt 文本
                        └─ 遍历所有 tools 生成自然语言描述
```

**耦合点**：
- 依赖 `capability_system.unit_projection`（单个工具投影）
- 依赖 `capability_system.capability_catalog`（原始目录）
- 依赖 `harness.runtime.tool_display`（工具显示）
- 依赖 `harness.runtime.public_progress`（公开进度）

**错误处理**：
- `build_capability_groups` 使用 `try/except` 处理分组异常（行 220-236）。
- `_tool_risk_level` 使用字典和集合判断，逻辑清晰无分支爆炸。
- `build_tool_prompt_section` 大量使用字符串拼接，无长度限制，可能导致 prompt 过长。

**并发安全**：纯函数转换。

**代码质量**：
- 函数分组合理，职责清晰。
- `_tool_risk_level` 设计良好，使用 `tags` 和工具属性综合判断。
- `build_tool_prompt_section` 较长（约 150 行），主要因字符串格式化较多，可考虑模板引擎。
- 提示词文本直接嵌入代码中，缺少 i18n 支持（当前可接受）。

**问题**：
- **P2（中）** `build_tool_prompt_section`（行 593-750）：生成的提示词文本总长度未做硬限制。若工具数量较多，可能导致 LLM 上下文窗口溢出。建议限制总字数或按优先级筛选工具。
- **P3（低）** `build_tool_prompt_section`：提示词模板硬编码在代码中，修改样式需要改代码，建议提取到配置或模板文件。
- **P3（低）** 行 220-236 `build_capability_groups`：异常捕获粒度较粗，返回默认分组，可能掩盖具体错误。建议细化异常类型。

---

## 三、总体架构评估

### 3.1 模块分层

```
┌──────────────────────────────────────────────────┐
│             调用层（Harness Loop / API）            │
├──────────────────────────────────────────────────┤
│  authority.py (公开事件控制器)                      │
│  operation_projection.py (操作级投影)               │
│  structured_error_projection.py (错误投影)          │
├──────────────────────────────────────────────────┤
│  dynamic_context/manager.py (动态上下文聚合)        │
│    ├── 编辑器上下文投影                              │
│    ├── 文件证据投影                                  │
│    └── 轮次报告投影                                  │
├──────────────────────────────────────────────────┤
│  业务域投影层                                       │
│  ├── context_system/projection (上下文投影)          │
│  ├── evidence/projection (证据投影)                  │
│  └── capability_system/catalog_projection (能力投影) │
├──────────────────────────────────────────────────┤
│  基础工具层                                         │
│  ├── guards.py (脱敏/压缩/哈希)                      │
│  └── filters.py (遮蔽判断)                           │
└──────────────────────────────────────────────────┘
```

分层基本合理，底层纯函数无上层依赖，业务域投影层相互独立。`dynamic_context/manager.py` 作为聚合层承上启下，但耦合过多的业务域模块（见 3.2）。

### 3.2 循环依赖检查

**未发现循环依赖**。检查结果：
- `guards.py` ← 无内部依赖
- `filters.py` ← 依赖 `guards.py`
- `authority.py` ← 依赖 `guards.py`, `filters.py`
- `operation_projection.py` ← 依赖 `guards.py`, `filters.py`, `authority.py`
- `structured_error_projection.py` ← 依赖 `dynamic_context/models.py`
- `dynamic_context/manager.py` ← 依赖 `context_system.projection`, `evidence.projection`, `capability_system.catalog_projection` 等
- `context_system/projection/projection.py` ← 依赖 `context_system.policy`
- `evidence/projection.py` ← 依赖 `context_system.policy`, `context_system.projection`
- `capability_system/catalog_projection.py` ← 依赖 `capability_system.unit_projection`

依赖方向清晰：下层不依赖上层，业务域模块互不依赖，通过 Manager 聚合。

### 3.3 投影协议一致性

各模块的投影输出格式不完全一致：
- `authority.py` 输出嵌套字典 `{"event": ..., "structured_output": ..., ...}`
- `operation_projection.py` 输出 `OperationPublicEvent` 数据类（通过 `asdict` 转字典）
- `context_system/projection.py` 输出 `ContextProjection` 数据类
- `evidence/projection.py` 输出 `EvidenceProjection` 数据类
- `catalog_projection.py` 输出 `dict` 和 `str`（提示词文本）

各数据类使用 `slots=True` 和规范的字段定义，但缺少统一的投影基类或协议（如 `ProjectionProtocol`），导致类型检查和序列化各模块自行处理。

**建议**：定义统一的 `Projection` 抽象基类或 `TypedDict` 系列，明确所有投影必须包含的字段（如 `authority`、`timestamp`、`source`）。

### 3.4 并发安全总结

- **纯函数模块**（guards, filters, authority, operation_projection, structured_error_projection, context/projection, evidence/projection, catalog_projection）：完全线程安全。
- **有状态模块**（dynamic_context/manager.py）：通过 `merge()` 接收不可变输入并返回新输出，单次调用线程安全。但 Manager 实例本身可能被多次调用，若外部 `context_store` 或 `file_state_store` 被多个线程修改，当前未加保护。建议在 Manager 中增加对共享存储的一致性校验。

---

## 四、问题分级清单

### 严重（P1）
无。

### 中等（P2）

| # | 模块 | 文件 | 行号 | 描述 | 建议 |
|---|------|------|------|------|------|
| 1 | authority | `harness/runtime/projection/authority.py` | 74-85 | 未知事件透传 `raw_event`，可能泄露敏感信息 | 对未知事件也应用脱敏或直接丢弃 |
| 2 | manager | `harness/runtime/dynamic_context/manager.py` | 54-83 | `merge()` 缺少中间步骤失败验证，可能返回不完整输出无感知 | 增加中间步骤结果校验，失败时记录日志或标记 incomplete |
| 3 | manager | `harness/runtime/dynamic_context/manager.py` | 531-608 | `_serialize_editor_files` 静默吞异常，无法诊断文件序列化失败 | 至少记录错误日志，标识失败文件 |
| 4 | catalog | `capability_system/catalog_projection.py` | 593-750 | `build_tool_prompt_section` 无总长度限制，可能超出 LLM 上下文窗口 | 增加总字数限制或按优先级/相关性筛选工具 |

### 一般（P3）

| # | 模块 | 文件 | 行号 | 描述 | 建议 |
|---|------|------|------|------|------|
| 1 | guards | `harness/runtime/projection/guards.py` | 10-14 | `text()` 未过滤零宽字符和代理对 | 增加 Unicode 安全字符过滤 |
| 2 | guards | `harness/runtime/projection/guards.py` | 48-68 | `record()` 失败时返回 None，不区分解码失败与类型不支持 | 返回明确错误或记录日志 |
| 3 | authority | `harness/runtime/projection/authority.py` | 237-265 | 显示名映射表不完整 | 补充缺失映射或完善兜底策略 |
| 4 | authority | `harness/runtime/projection/authority.py` | 178-234 | 进度字段缺失时输出空字符串 | 考虑使用默认进度文本 |
| 5 | operation | `harness/runtime/operation_projection.py` | 102-110 | `compact` 截断可能导致中文乱码 | 使用字符数而非字节数截断 |
| 6 | operation | `harness/runtime/operation_projection.py` | 121-126 | 状态映射不完整 | 补充状态枚举或使用完整映射 |
| 7 | manager | `harness/runtime/dynamic_context/manager.py` | 839 | 文件过大 (839 行) | 拆分为 3-4 个模块 |
| 8 | manager | `harness/runtime/dynamic_context/manager.py` | 245-252 | `_section_reports` 空实现无文档 | 添加 TODO 注释或实现 |
| 9 | manager | `harness/runtime/dynamic_context/manager.py` | 680-839 | `_build_number_of_turns_reports` 过长 | 提取辅助函数 |
| 10 | context_proj | `context_system/projection/projection.py` | 298-336 | 日期比较未考虑时区 | 评估是否需要，若内部使用可接受 |
| 11 | context_proj | `context_system/projection/projection.py` | 242-295 | 匹配逻辑可读性一般 | 提取规则表或策略模式 |
| 12 | evidence | `evidence/projection.py` | 241-268 | `_finalize_binding` 修改上下文属性 | 考虑返回新对象而非修改输入 |
| 13 | evidence | `evidence/projection.py` | 31-131 | 异常捕获返回默认实例可能掩盖关键错误 | 至少记录警告日志 |
| 14 | catalog | `capability_system/catalog_projection.py` | 220-236 | 异常捕获粒度过粗 | 细化异常类型 |
| 15 | catalog | `capability_system/catalog_projection.py` | 593-750 | 提示词模板硬编码 | 提取到配置或模板文件 |

---

## 五、优化建议

1. **统一投影协议**：定义 `Protocol` 或抽象基类，让所有投影输出遵循一致的接口约定，便于序列化和类型安全。

2. **重构 DynamicContextManager**：将 839 行的 Manager 拆分为：
   - `EditorContextProjector`（编辑器上下文投影）
   - `FileEvidenceProjector`（文件证据投影）
   - `TurnReportBuilder`（轮次报告构建）
   - 保留 `DynamicContextManager` 作为门面聚合。

3. **增强错误透明性**：对静默吞异常的位置（如 `_serialize_editor_files`、`project_evidence_snapshot`）增加结构化错误记录，使运维可诊断。

4. **安全加固**：在 `build_public_tool_event` 中对未知事件类型应用脱敏策略，防止敏感信息泄露。

5. **提示词长度管控**：为 `build_tool_prompt_section` 增加总长度硬限制，优先展示高风险/高优先级工具。

6. **国际化准备**：将硬编码的中文显示名、状态标签提取到资源文件，为未来多语言支持做准备。

7. **代码整洁性**：
   - `compact()` 函数考虑使用 `unicodedata` 模块处理字符宽度。
   - `_summary_matches_bundle_item` 可提取匹配规则表。

8. **测试覆盖**：当前各模块缺少结构化单元测试（虽然项目规则要求清理语义测试，但投影逻辑是结构性的，应有基础验证）。

---

## 六、审查总结

本次审查覆盖了 backend 下 6 个投影相关目录 / 模块，共 12 个文件，约 2800 行代码。

**总体评价**：投影系统架构合理，分层清晰，依赖方向正确，无循环依赖。基础层（guards、filters）设计简洁，职责单一。业务投影层（context/evidence/capability）各自独立运行，通过 DynamicContextManager 聚合。所有模块均为纯函数或接收不可变输入，并发安全性良好。

**主要风险**：
- `authority.py` 中未知事件透传机制可能泄露敏感信息（P2）。
- `DynamicContextManager` 过大且静默吞异常，缺少故障诊断支持（P2）。
- 工具提示词生成无长度上限，可能溢出 LLM 上下文窗口（P2）。

**推荐优先级**：
1. 修复 P2 问题（安全加固、异常透明性、提示词长度管控）。
2. 重构 Manager 拆分（改善可维护性）。
3. 长期推进统一投影协议和国际化。

所有判断均基于当前代码事实，具体问题已标注文件路径和行号，可复核。
