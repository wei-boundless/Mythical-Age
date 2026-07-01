# 搜索工具体系优化计划书

状态：Phase 1 常态搜索链路已落地；多层 orchestrator / lifecycle / frontend 深化继续按本计划推进  
日期：2026-07-01  
范围：`capability_system.tools`、`capability_system.capabilities.codebase_search`、`prompt_library`、`harness.runtime`、`runtime.tool_runtime`、`frontend/src/components/chat`  
原则：多层搜索，不用单一机制包打天下；搜索只定位证据，`read_file` 才建立 exact evidence；工具指引必须让 agent 能执行，而不是描述内部实现。

## 0. 问题定义

当前搜索工具已经比原始文本解析链路更强：`WorkspaceSearchService` 统一了路径、正文和 glob 的底层召回，`codebase_search` 已开始消费结构化结果。但这仍只是第一步。

真正缺失的是一套完整的搜索工具体系：

- agent 不只需要“能搜到”，还需要知道“应该用哪一层搜”“搜完下一步读哪里”“什么时候该纠正查询”“什么时候负结果不可信”。
- 后端不应把路径搜索、正文搜索、符号搜索、glob 和 codebase specialist 包成一个万能搜索机制。
- prompt / tool manifest / dynamic context / frontend 展示必须共享同一套搜索认知契约，否则 agent 会继续把搜索片段当证据、把重复搜索当推进、把 incomplete 当 no match。

正确终态：

```text
Search Intent
-> Search Layer Selection
-> Layer-Specific Retrieval
-> Evidence Candidate Normalization
-> Candidate Read Window
-> Exact Read / Verification
-> Feedback And Query Correction
-> Lifecycle Recording
-> Frontend Evidence Window Display
```

本轮已落地的基础能力：

- `codebase_search` 已接入 path / symbol / text / glob 多源合流。
- `python_symbol_search` 作为独立 AST symbol layer 输出 `symbol_match`。
- `WorkspaceSearchService` 已支持 `include_default_search_excludes`，让 orchestrator 区分系统默认 roots 和用户显式 roots。
- 普通 codebase search 默认不搜索 `docs` 和 backend design docs；只有文档意图或显式 roots 才进入文档范围。
- `path_match` 在 ranker 中降级为 locator candidate，不再吃正文 required/query 加分，不在宽泛概念查询里压过 symbol/definition。
- `CodebaseEvidence.to_dict()` 已输出 `recommended_read_window`，前端和 agent 可直接看到下一步读窗。

## 1. 当前源码报告

### 1.1 已有底层能力

- `backend/capability_system/tools/workspace_search_service.py`
  - 已成为路径关键词、正文搜索、glob 搜索的共享 service。
  - 已支持 path scoring、keyword cross search、recommended read windows、fallback diagnostics。
- `backend/capability_system/tools/tool_units/python_ast_tools.py`
  - 已有 `python_symbol_search`、`python_code_outline`、`python_parse_check`。
  - 符号搜索基于 Python 官方 `ast`，应作为独立 symbol layer。
- `backend/capability_system/capabilities/codebase_search/runtime.py`
  - 已有 path / glob / text / slice / rank / evidence refs 的 specialist pipeline。
  - 已接入 `symbol_search_meta` 和 `symbol_match` 后，应成为多源合流 orchestrator。

### 1.2 已有 prompt/tool 指引

- `backend/prompt_library/tool_prompts.py`
  - 已说明已知路径直接 read，不知道位置才 search。
  - 已说明 `search_text.paths` 只能放文件，`roots` 放目录。
  - 已说明 `recommended_read_windows` 只是 candidate windows。
- `backend/harness/runtime/tool_catalog_manifest.py`
  - 已给 `read_file/search_files/search_text/glob_paths` 写 usage hints 和 output facts。
  - 还缺少“多层搜索选择契约”和“失败后纠偏契约”。
- `backend/prompt_library/rules.py`
  - 已有 locator-only 原则：`codebase_search/search_text/summary/code_structure` 不能替代 exact read evidence。

### 1.3 已有上下文与前端入口

- `backend/harness/runtime/dynamic_context/tool_result_projector.py`
  - `code_structure_map` 已压缩为 candidate-only 文件、slice、read_request。
- `backend/harness/runtime/dynamic_context/manager.py`
  - 已投影 `recommended_read_windows`。
- `frontend/src/components/chat/ToolTrace.tsx`
  - 已有 `search_results` 结构化展示入口，但目前更偏文本解析结果。
  - 还没有把 search layer、confidence、searched roots、read window、next read action 作为一等 UI。

## 2. 成熟架构标准

参考 Claude Code / Codex 外显工程能力，本项目应采用以下不变量：

- `rg` 是强大的高召回 primitive，不是完整 agent 搜索产品。
- Claude Code 式专用 `Glob/Grep` 工具优点是边界清晰、输出可分页、可区分 no match / timeout / error。
- Codex 式 shell/rg 弹性适合作为补充路径，但主链路不能依赖模型每次解析 shell 输出。
- 符号定位应走 AST / language server / index，不应长期由文本 grep 冒充。
- 搜索结果只能产生 locator facts；当前 exact evidence 必须由 read tool 或系统注入的 exact artifact 建立。

## 3. 搜索认知契约

这是写给 agent 的核心契约，后续应进入 tool guidance / manifest / worker prompts：

```text
你使用搜索工具时，是在定位当前任务所需的工作区证据。
搜索不会替你决定任务目标，也不会给你编辑权限。

如果路径已经明确，直接读取、检查或列出该路径；不要重新搜索已知路径。
如果只知道文件名、模块名或路径片段，先用路径搜索。
如果知道通配符范围，使用 glob。
如果要找类、函数、方法或 Python 顶层符号，优先使用 symbol search 或 codebase_search 的符号层。
如果要找报错文本、配置键、提示词正文、文档标题或跨文件概念，使用正文搜索。
如果你需要综合定位代码关系，使用 codebase_search，让它合流路径、符号和正文候选。

搜索命中只是候选窗口。
在做修改、逐行判断、最终裁决或引用代码前，必须读取候选窗口的当前 exact content。

如果搜索结果 truncated、timeout、fallback、permission_error 或 searched_roots 不覆盖目标范围，你只能说搜索不充分，不能说项目里不存在。
如果搜索结果噪声高，先收窄 roots/glob/paths，或切换搜索层，不要重复同一个宽泛查询。
```

## 4. 多层搜索体系

### 4.1 Path Layer

职责：

- 根据文件名、目录名、模块名、路径片段找候选文件。
- 使用 phrase、compact identifier、exact stem、basename terms、generic term penalty。

禁止：

- 不读取文件正文。
- 不推断代码语义。
- 不在宽泛概念查询里压过 symbol / definition 证据。

输出：

- `path`
- `score`
- `match_reason`
- `matched_terms`
- `searched_roots`
- `truncated/has_more`

### 4.2 Glob Layer

职责：

- 用明确通配符构造文件集合。
- 适合 `**/*.py`、`backend/**/*.md`、`*.html`。

禁止：

- 不把自然语言 query 当 glob。
- 不返回正文 preview。

### 4.3 Symbol Layer

职责：

- 使用 `python_symbol_search` 定位 Python class/function/method/import/variable。
- 未来可扩展 TypeScript AST / language server。

禁止：

- 不用正文 grep 冒充符号索引。
- 不在非 Python 文件上伪造 symbol result。

输出：

- `symbol_match`
- `kind`
- `qualname`
- `path`
- `line/column`
- `match_reason=python_ast_symbol_search`

### 4.4 Text Layer

职责：

- 使用 `rg` 做 literal/regex 高召回。
- 短语无命中时使用多关键词 AND 交叉召回。
- 用 BM25-lite、行内多词覆盖、最短关键词窗口定位排序。

禁止：

- 不把 snippet 当 exact source。
- 不对 incomplete negative result 下确定结论。

### 4.5 Codebase Search Orchestrator

职责：

- 合流 path / glob / symbol / text / git history。
- 输出 ranked findings、code_structure、recommended_read_window、limitations。
- 判断哪些候选需要下一步 `read_file`。

禁止：

- 不拥有底层文件遍历权威。
- 不解析人类可读搜索文本。
- 不把搜索片段升格为 edit authority。

## 5. 打分与排序机制

打分不是一个全局万能公式。每层只在自己的职责内评分，合流时再排序。

Path layer：

- full phrase path match 高分。
- compact identifier match 高分。
- exact stem match 最高。
- basename term match 中高分。
- generic terms 低分。
- generated/cache 路径降权。
- 长 identifier 必须满足 compact 或 basename 约束，防止泛词污染。

Symbol layer：

- exact symbol name 高分。
- exact qualname 高分。
- qualname substring 中分。
- 进入 ranker 时 evidence_kind 为 `symbol_match`。

Text layer：

- 文档必须同时包含关键词集合。
- BM25-lite 处理词频和文档长度。
- 最短关键词窗口更靠前。
- 定义行附近加权，但仍只是 locator。

Orchestrator：

- 默认证据优先级：`symbol_match > definition > path_match > call_site > config > text_match > test/doc`。
- 如果用户明确要求测试或文档，再提升 test/doc。
- 宽泛概念查询中，path_match 是候选路径，不应压过 definition / symbol。
- 分数饱和后使用 tie-breaker：复合路径文件名命中、source path、非 generated path、文件多样性。
- 默认 codebase search 要排除设计文档、构建产物、缓存、`.tsbuildinfo` 和典型生成噪声；用户显式 roots 可以重新打开对应范围。

## 6. 反馈与纠正机制

### 6.1 搜索反馈分类

每次搜索都必须产出可读反馈：

- `complete_match`：有候选且搜索范围完整。
- `candidate_only`：有候选但需要 read_file 确证。
- `no_match_complete`：范围完整且无命中。
- `no_match_incomplete`：timeout / truncated / permission / fallback 后无命中。
- `too_broad`：命中多、泛词多、top results 分散。
- `wrong_layer`：路径问题用了 text，符号问题用了 text，已知路径却搜索。
- `needs_scope_narrowing`：需要 roots/glob/paths。

### 6.2 Agent 纠偏动作

- wrong layer：切换工具层。
- too broad：收窄 roots / glob / exact phrase / symbol。
- no_match_incomplete：扩大 roots 或排除错误原因后重试。
- candidate_only：读取 top window，而不是继续同查询搜索。
- repeated same query：除非搜索范围或 query 变了，否则不重复。

### 6.3 Runtime 纠偏输入

动态上下文中只保留简短搜索状态：

```text
last_search_ref
query
search_layer
searched_roots
top_candidates
recommended_read_windows
incomplete_reason
next_repair_action
```

这些是 current locator facts，不是长期记忆。

## 7. 工具生命周期管理

### 7.1 生命周期状态

```text
declared
-> available
-> selected
-> invoked
-> observed
-> normalized
-> projected
-> consumed_by_read
-> superseded_or_closed
```

### 7.2 生命周期规则

- selected：agent 说明或隐含满足该搜索层的使用条件。
- invoked：记录 query、roots、glob、paths、limit、offset。
- observed：记录 raw backend、returncode、timeout、stderr、match count。
- normalized：生成结构化 `SearchResultEnvelope`。
- projected：只投影 locator facts / candidate windows。
- consumed_by_read：某个 candidate window 被 read_file exact 读取。
- superseded：新搜索覆盖旧搜索，或 read_file 已建立 exact evidence。
- closed：任务收口后搜索候选不再作为当前动作建议。

### 7.3 不允许

- 搜索结果长期滞留为动态尾全文。
- 每轮重复投影同一搜索候选。
- 用搜索 snippet 直接驱动 edit。
- 负结果不带完整性状态。

## 8. 后端数据模型目标

新增或统一结构：

```text
SearchQueryPlan
SearchLayerResult
SearchCandidate
RecommendedReadWindow
SearchFeedback
SearchLifecycleRecord
```

关键字段：

```text
query_id
query_text
layer: path | glob | symbol | text | orchestrated
strategy
searched_roots
filters
matches
matched_paths
recommended_read_windows
truncated
incomplete_reason
feedback
next_repair_action
locator_only=true
requires_read_file_for_exact_evidence=true
```

## 9. Prompt 与工具指引改造

### 9.1 `tool_prompts.py`

补充搜索认知契约：

- 搜索是定位，不是裁决。
- 多层搜索选择规则。
- 失败纠偏动作。
- 禁止 repeated same query。
- 负结果完整性判断。

### 9.2 `tool_catalog_manifest.py`

补充每个搜索工具的：

- `search_layer`
- `wrong_layer_examples`
- `repair_actions`
- `output_facts`
- `lifecycle_state_outputs`

### 9.3 Environment Guidance

coding 环境 `tool_dispatch.md` 需要把“代码定位按目标选工具”升级为：

- path / glob / symbol / text / codebase_search 的选择表。
- “先定位，再读取，再判断”的工作流。

### 9.4 Worker Prompts

`worker.prompt.codebase_search` 应明确：

- 你是多层代码检索 specialist。
- 你不写代码，不做最终裁决。
- 你返回 evidence matrix、read windows、limitations、repair suggestions。

## 10. 前端窗口展现优化

### 10.1 展示目标

前端不应只展示搜索输出文本，而应展示：

- 搜索层：path / glob / symbol / text / codebase_search。
- 查询和范围：query、roots、glob、paths。
- 完整性：complete、truncated、timeout、fallback。
- 候选窗口：path、start_line、line_count、match_line。
- 下一步动作：一键或显式展示 `read_file` 参数。
- 证据状态：locator-only / exact-read-confirmed。

### 10.2 UI 结构

搜索结果卡片建议拆成：

```text
Header: tool + layer + strategy + status
Scope: searched_roots / filters
Candidates:
  path
  line
  evidence_kind
  score/reason
  matched_terms
  read window command
Feedback:
  incomplete_reason
  next_repair_action
```

### 10.3 展示规则

- locator-only 用中性视觉，不标成“已读证据”。
- recommended read window 是主操作，不是隐藏在 raw text 里。
- truncated/timeout 显示为警示状态。
- no match incomplete 与 no match complete 用不同文案。
- codebase_search findings 优先展示 `recommended_read_window` 和 `code_structure.files[].slices[]`。

## 11. 文件级执行清单

后端：

```text
backend/capability_system/tools/workspace_search_service.py
backend/capability_system/tools/search_result_models.py
backend/capability_system/tools/tool_units/search_files_tool.py
backend/capability_system/tools/tool_units/file_system_tools.py
backend/capability_system/tools/tool_units/python_ast_tools.py
backend/capability_system/capabilities/codebase_search/models.py
backend/capability_system/capabilities/codebase_search/providers.py
backend/capability_system/capabilities/codebase_search/query_planner.py
backend/capability_system/capabilities/codebase_search/ranker.py
backend/capability_system/capabilities/codebase_search/runtime.py
backend/harness/runtime/tool_catalog_manifest.py
backend/harness/runtime/dynamic_context/tool_result_projector.py
backend/harness/runtime/dynamic_context/manager.py
backend/runtime/tool_runtime/native_tools.py
```

Prompt：

```text
backend/prompt_library/tool_prompts.py
backend/prompt_library/rules.py
backend/prompt_library/worker_prompts.py
backend/prompt_library/prompt_assets/environment_guidance/coding/tool_dispatch.md
backend/prompt_library/prompt_assets/environment_guidance/coding/tool_observation_recovery.md
backend/prompt_library/prompt_assets/environment_guidance/coding/verification_gate.md
```

前端：

```text
frontend/src/components/chat/ToolTrace.tsx
frontend/src/components/chat/PublicTimelineActivity.tsx
frontend/src/lib/projection/chronological/accumulator.ts
frontend/src/lib/projection/reducer.ts
frontend/src/lib/api/types.ts
```

## 12. 分阶段计划

### Phase 1: 契约与模型

- 新增 `SearchResultEnvelope` / `SearchCandidate` / `SearchFeedback`。
- 统一 `search_files/search_text/glob_paths/python_symbol_search/codebase_search` 的 locator-only 字段。
- 完成后所有搜索输出都能区分 complete / incomplete。

### Phase 2: 多层 Orchestrator

- `codebase_search` 明确合流 path / glob / symbol / text。
- `ranker` 保持 evidence kind 排序，不让 path hit 在概念查询中压过 symbol/definition。
- findings 输出 `recommended_read_window`。

### Phase 3: Prompt 指引

- 更新 `TOOL_LOCAL_SEARCH_GUIDANCE`。
- 更新 tool catalog manifest usage hints。
- 更新 coding guidance 和 codebase_search worker prompt。

### Phase 4: 反馈与生命周期

- 动态上下文投影 `SearchFeedback` 和 `SearchLifecycleRecord`。
- 同一 query + same scope + same result hash 不重复投影。
- read_file 消费某个 window 后关闭或 supersede 对应 candidate。

### Phase 5: 前端展示

- `ToolTrace.tsx` 识别结构化搜索 envelope。
- 展示候选窗口和 read_file 参数。
- 区分 locator-only / exact evidence。
- 展示 incomplete negative result 的纠偏建议。

## 13. 验证策略

不新增回归测试文件。按项目规则使用编译、静态扫描、真实工具 smoke 和前端实际浏览检查。

后端 smoke：

```text
PromptSetResolver cycle diagnostics
dynamic tail policy
workspace search service read window
same_fact_slot_same_content_hash_already_visible
```

期望：

- `PromptSetResolver` 由 symbol layer 命中 `prompt_set_resolver.py`。
- `dynamic tail policy` 由 text cross layer 命中 `context_system/segments/policy.py` 等源码策略文件，path-only 脚本/测试不应压过源码定义。
- `workspace search service read window` 命中 `workspace_search_service.py` 并给出 read window。
- 长 identifier 精确命中真实定义或引用，不泛化到大量 `fact` 文件。

前端 smoke：

- 启动固定端口前后端。
- 运行一次搜索工具调用。
- 检查 ToolTrace 是否展示 layer、scope、status、candidate windows、read action。
- 检查 truncated/timeout/no_match 文案是否区分。

## 14. 禁止事项

- 不把一个搜索机制包装成万能能力。
- 不把搜索 snippet 当 exact evidence。
- 不让 path hit 在宽泛概念查询中压过 symbol/definition。
- 不在多个 adapter 里复制搜索排序算法。
- 不把失败搜索投影成确定不存在。

## 15. Phase 1 执行记录（2026-07-01）

### 15.1 已落地目标

本阶段优先打磨成熟 coding agent 的常态搜索路径：

```text
search_text / rg-like locator search
-> read_file exact content
-> 判断 / 回答 / 修改
```

落地原则：

- 常态搜索不默认升级到 `codebase_search`，除非任务需要跨层综合。
- `search_text` 的 snippet 和 match 行只作为 locator，不作为 exact evidence。
- `read_file` 是 exact evidence 的权威来源。
- 动态尾和反馈上下文不能把 `has_more`、coverage gap、candidate window 投影成命令式“下一步必须读取”。
- 搜索结果路径必须和 `read_file` 使用同一个 canonical workspace-relative 契约。

### 15.2 动态尾与反馈收缩

已从动态尾 / 任务状态投影中移除命令式下一步读取信号：

- `backend/harness/runtime/bound_task_context.py`
- `backend/harness/runtime/dynamic_context/evidence_index_cursor.py`
- `backend/harness/runtime/dynamic_context/evidence_acquisition_horizon.py`
- `backend/harness/runtime/dynamic_context/task_state_projector.py`
- `backend/runtime/memory/evidence_delta_summary.py`

语义调整：

- `next_suggested_read` 不再作为 task file projection、cursor rehydration 或 boundary state 暴露。
- missing range 改为 coverage gap diagnostic，不再生成 `read_required_before_exact_claim`。
- `candidate_read_windows` 只保留为搜索候选，不进入“必须执行”的控制语义。

### 15.3 常态搜索默认排除

已优化 `backend/capability_system/tools/workspace_search_service.py`：

- 对 `roots=["backend"]` 这类宽泛源码根也启用默认搜索排除。
- 默认排除 design docs、runtime cache、sandbox、生成噪声等路径。
- 用户显式搜索被排除文档路径时仍可打开对应范围。

直接 smoke 结果：

- `PromptSetResolver` / `PromptSet` 查询返回源码候选。
- `dynamic tail policy` 查询返回源码策略文件，不被 design docs 淹没。
- 随机无命中 marker 返回 `no_match_complete`。
- 显式 `roots=["backend/runtime/context_management/design_docs"]` 仍可搜索设计文档。

### 15.4 工具路径契约修复

主 agent 实测暴露的问题：

```text
search_text 返回：backend/prompt_library/models.py
read_file 错误解析：D:/AI应用/langchain-agent/backend/backend/prompt_library/models.py
```

根因：

- 部分 runtime/session 绑定把 `workspace_root` 写成项目内 `backend` 目录。
- `FileGateway` 对 `repo.managed_project.project_workspace` 信任该根作为 repository root。
- 因此项目相对路径 `backend/...` 会被再次拼到 `backend` 根下。

修复文件：

- `backend/harness/runtime/assembly.py`
  - `_normalize_workspace_root()` 使用 `ProjectLayout.from_backend_dir(...).project_root` 规范为 canonical project root。
- `backend/runtime/tool_runtime/tool_executor.py`
  - sandbox policy / workspace policy 读取入口统一经过 `_canonical_project_workspace_root()`。
- `backend/harness/loop/single_agent_turn.py`
  - single-turn sandbox scope 和 artifact project root 统一输出 canonical project root。
- `backend/harness/loop/task_executor.py`
  - task-run workspace root 统一输出 canonical project root。

该修复把“工作区根”规范化放在 runtime/tool 边界 authority 上，而不是让 `read_file`、`search_text`、`FileGateway` 各自猜路径。

### 15.5 验证记录

编译验证通过：

```text
python -m py_compile backend/harness/runtime/assembly.py backend/runtime/tool_runtime/tool_executor.py backend/harness/loop/single_agent_turn.py backend/harness/loop/task_executor.py backend/runtime/tool_runtime/native_tools.py backend/capability_system/tools/workspace_file_service.py backend/capability_system/tools/workspace_search_service.py
```

直接工具 smoke 通过：

- 输入旧形态 policy：`workspace_root = D:\AI应用\langchain-agent\backend`
- 工具边界规范化结果：`D:\AI应用\langchain-agent`
- `read_file("backend/prompt_library/models.py")` 返回 `status=ok`
- `search_text("PromptSet", roots=["backend"])` 返回 `backend/...` 路径后，直接 `read_file` 首个候选成功。

主 agent CLI smoke 通过：

- 会话：`session-2bf09cb46aab4ec1`
- run：`strun:134df7db61ac40beaf5f50d0a873386c`
- 任务：定位 `PromptSet` 继承解析入口并判断循环检测。

事件回放确认工具序列：

```text
search_text query=PromptSet
read_file path=backend/prompt_library/models.py
read_file path=backend/prompt_library/prompt_set_resolver.py
read_file path=backend/prompt_library/descriptor_resolver.py
```

所有 `read_file` 均为 `done`，没有再出现 `backend/backend/...` 双重路径。

主 agent 行为评价：

- 顺手点：先用 `search_text` 定位，再读 exact 文件；没有先调用重型 `codebase_search`。
- 顺手点：没有因为搜索结果 `has_more` 或候选范围而反复读取无关整文件。
- 顺手点：最终回答基于 `read_file` 读取的 exact 文件内容。
- 待继续优化：`search_text` 本次耗时约 17 秒，后续需要继续优化 `rg` 参数、默认 roots、head limit 和 candidate 去重策略。

### 15.6 下一阶段约束

后续继续推进时必须保持：

- `codebase_search` 是深度网络型检索/整合层，不替代常态 `search_text -> read_file`。
- 动态尾只能提供路标式系统状态，不生成命令式下一步。
- 搜索 lifecycle 只记录 current locator facts；被 exact read 消费后应 supersede 或关闭候选。
- frontend 只能把 locator candidate 显示为候选，不能显示成已确认源码证据。
- 不用 prompt 话术弥补后端结构缺失。
- 不让前端只展示 raw text 而隐藏 recommended read windows。

## 15. 2026-07-01 精简算法落地记录

本轮把原先偏重的“全层并跑”收缩为 `Intent-Gated Adaptive Cascade`：

```text
query
-> high-signal path gate
-> high-signal symbol gate
-> phrase / identifier text search
-> keyword AND prefilter by rg --files-with-matches
-> BM25-lite rank on reduced candidate files
-> ranked SearchCandidate / recommended_read_window
```

落地原则：

- 外部仍是一个 `codebase_search(query, roots?)` 主入口，不要求 agent 手动选择所有算法。
- path 层只在原始 query 带路径、文件名或标识符信号时运行；纯自然语言概念不猜文件名。
- symbol 层只在纯符号查询或混合查询中出现 CamelCase / qualified symbol 时运行；小写下划线模块名优先交给 path/text。
- 纯小写 snake_case 或长 identifier 默认不跑 AST symbol；它们由 path/text 处理，避免无命中时全库 AST 扫描。
- 纯符号查询如果 AST symbol 命中充分，可以提前跳过 text。
- 混合查询中的 symbol 命中降级为 `symbol_locator`，不能压过满足语义关键词的正文候选。
- glob 默认不跑，只有显式通配符或特定数据集模式才跑。
- git history 默认不跑，只有提交、历史、变更记录意图才跑。
- search result 继续保持 locator-only；`read_file` 才建立 exact evidence。

已落地文件：

```text
backend/capability_system/tools/workspace_search_service.py
backend/capability_system/capabilities/codebase_search/models.py
backend/capability_system/capabilities/codebase_search/providers.py
backend/capability_system/capabilities/codebase_search/file_slicer.py
backend/capability_system/capabilities/codebase_search/ranker.py
backend/capability_system/capabilities/codebase_search/runtime.py
backend/capability_system/capabilities/codebase_search/report.py
```

烟测结果：

```text
workspace_search_service dynamic tail policy:
  旧路径：keyword AND 逐文件扫描约 1746 个文件
  新路径：rg files-with-matches 预过滤到 43 个文件
  实测：约 0.35s

codebase_search("dynamic tail policy"):
  path skipped, glob skipped, git skipped
  text_queries_used=["dynamic tail policy"]
  实测：约 0.43s

codebase_search("workspace search service read window"):
  path skipped, symbol skipped, text phrase only
  实测：约 0.35s

codebase_search("workspace_search_service read window"):
  path used, symbol skipped, text identifier+phrase
  实测：约 1.4s

codebase_search("PromptSetResolver"):
  path used, symbol used, text skipped by sufficient symbol candidate
  实测：约 0.14s

codebase_search("PromptSetResolver cycle diagnostics"):
  path used, symbol used as locator, text also runs
  实测：约 0.24s

codebase_search("definitely_no_such_search_marker_20260701"):
  path used, symbol skipped, text exact
  旧实测：约 5.5s
  新实测：约 1.27s
```

仍需后续阶段处理：

- `SearchResultEnvelope` 已定义，但还未作为所有搜索工具的统一外层返回。
- 动态上下文还需要用 query/scope/result hash 做 consumed/superseded，避免重复候选反复投影。
- 前端 ToolTrace 还需要展示 layer、status、read window 和 locator-only/exact evidence 区分。

## 16. 搜索指令面收缩原则

多层搜索是系统能力，不应成为 agent 必须背诵的工具菜单。

目标指令面：

```text
已知路径 -> 直接 read_file / path_exists / stat_path / list_dir
未知代码位置 -> 先用 rg-like 常态搜索收敛候选
明确覆盖场景 -> 才直接使用 search_files / glob_paths / python_symbol_search
复杂跨层关系或多轮不能收敛 -> 升级 codebase_search / agent:codebase_searcher
搜索候选 -> 需要精确判断时 read_file
```

保留专用工具的原因不是让 agent 手动拼算法，而是给自适应路由、窄范围复查和已知场景提供低成本入口：

- `search_text`：常态 rg-like 入口，处理正文关键词、短语、错误文本、配置键、跨文件概念，也支持 roots/paths/glob 收窄。
- `search_files`：专用路径层，只处理文件名或路径关键词。
- `glob_paths`：专用 glob 层，只处理显式通配符。
- `python_symbol_search`：专用符号层，只处理 Python class/function/method 等符号定位。
- `codebase_search` / `agent:codebase_searcher`：升级路径，承接跨层定位、概念组合、复杂排序和代码关系检索。

已同步收缩：

```text
backend/prompt_library/tool_prompts.py
backend/prompt_library/io_capability_prompts.py
backend/prompt_library/rules.py
backend/prompt_library/worker_prompts.py
backend/prompt_library/prompt_assets/environment_guidance/coding/tool_dispatch.md
backend/harness/runtime/tool_catalog_manifest.py
backend/capability_system/tools/tool_units/search_files_tool.py
backend/capability_system/tools/tool_units/file_system_tools.py
```

## 17. 返璞归真后的主线重定向

2026-07-01 CLI 主 agent 实测暴露了两个比单点算法更核心的问题：

- 主 agent 的可见工具面没有 `codebase_search`，所以“未知代码位置优先自适应代码库搜索”的契约对主 agent 不可执行。模型只能手动拼 `search_files/search_text/read_file`。
- `tool_followup` 的 evidence delta 把 `read_file` 窗口覆盖率、`has_more`、`next_suggested_read` 投成了强下一步压力，导致模型把用户目标从“定位 PromptSet 继承解析并判断循环检测”偏移成“把 models.py 读完整”。这说明反馈层越权改写了搜索任务。

因此，后续不再以“继续调某个搜索算法”为主线，而是回到成熟 agent 的三层搜索能力：

```text
搜索认知契约
-> 工具算法与统一入口
-> 系统反馈与纠偏
```

### 17.1 第一层：搜索认知契约

契约层只负责让 agent 知道如何判断搜索，不替 agent 重新定义目标。

必须建立的 agent-facing 契约：

```text
你使用搜索是在获取当前用户目标所需的工作区证据。
搜索工具不能改变用户目标；工具反馈只能说明候选、范围、置信度和下一步可选动作。

已知路径时，直接 read_file/path_exists/stat_path/list_dir。
未知代码位置时，优先使用当前可见的自适应代码库搜索入口。
只有明确场景才直接使用专用工具：文件名/路径关键词用 search_files，显式通配符用 glob_paths，已知范围内正文关键词用 search_text。

搜索结果是 locator，不是 exact evidence。
需要逐行判断、修改、裁决或引用代码时，读取候选窗口。
读取窗口是否足够，由当前 claim 需要的行范围决定，不由“是否读完整文件”决定。
```

契约层禁止：

- 不允许把 `has_more=true` 翻译成“必须继续读完整文件”。
- 不允许把 `recommended_read_window` 翻译成“必须执行的命令”。
- 不允许因为文件未完整覆盖就否定当前窗口对当前 claim 的可用性。
- 不允许反馈层根据旧任务、旧摘要或 coverage 状态改写当前用户目标。

### 17.2 第二层：工具算法与统一入口

工具层应让主 agent 有一个顺手、成熟、低负担的搜索入口。

成熟 coding agent 的常态不是把所有搜索都交给一个重型智能检索器，而是用少数稳定 primitive 反复闭环：

```text
rg-style search -> read exact content -> refine query or answer
```

这更接近 Codex 的常态工作方式：`rg` 负责快速高召回定位，内容读取负责建立当前证据。搜索算法应该增强这两个动作，而不是让 agent 在一堆工具和搜索理论之间做选择。

目标工具面：

- 主 agent 的常态工具心智收缩为两个动作：`search_workspace`（当前实现可由 `search_text/search_files/glob_paths` 承担 rg-like 检索）和 `read_file`（精确内容获取）。
- `search_text` 应升级为最顺手的 rg-like 常态入口：支持正文检索、文件候选、roots、paths、glob、分页、状态边界和推荐读取窗口。
- `search_files/glob_paths/python_symbol_search` 仍保留，但定位为专用模式：路径关键词、显式通配符、符号定位。
- `codebase_search` 保留为升级路径：当一次任务需要跨层关系、符号+正文融合、复杂排序、或主 agent 连续两轮 primitive 搜索仍无法收敛时才使用；它不应成为每个未知位置任务的默认第一步。
- `codebase_search` 内部继续使用 intent-gated cascade：path、glob、symbol、text、git history 按意图触发，不全层并跑。
- 所有搜索工具最终归一到同一类 candidate envelope：`source_layer`、`evidence_kind`、`matched_terms`、`score_components`、`searched_scope`、`status`、`limitations`、`recommended_read_window`。

算法原则：

- 默认策略是简单、快速、可预测：先用 rg-like primitive 找少量高信号候选，再读候选窗口。
- 多层合流是升级能力，不是常态成本；只有 primitive 搜索不足以定位时才进入 orchestrator。
- 多关键词交叉检索是 text layer 的默认能力之一，但只在语义上需要 AND 覆盖时启用。
- 符号问题优先 AST / symbol layer；文本 grep 不能冒充符号索引。
- path hit 是定位线索；在概念查询中不能压过 symbol/definition/text evidence。
- negative result 必须携带搜索边界。范围不完整时只能返回 `no_match_incomplete`，不能给“项目里不存在”的结论。
- 搜索排序要可解释，至少暴露命中层、匹配词、范围和为何推荐该 read window。

### 17.3 第三层：系统反馈与纠偏

反馈层只做状态校准，不做目标决策。

正确反馈：

```text
本次搜索在哪些层运行
哪些层因为意图不匹配被跳过
搜索范围是否完整
候选是否只是 locator
下一步可选 read windows
当前 claim 是否已有足够 exact read evidence
```

错误反馈：

```text
文件还有未读行 -> 必须继续读
搜索候选存在 -> 必须读取全部候选
旧任务摘要提过读完整代码 -> 当前 turn 继续读完整代码
某次 no match 被 timeout/truncated 影响 -> 结论是不存在
```

反馈层需要从“文件覆盖率中心”改为“claim coverage 中心”：

- 对于定位类任务，只要相关定义/函数/调用窗口已经 exact visible，就可以回答定位结论。
- 对于编辑类任务，只要求编辑范围和依赖上下文 exact visible。
- 对于架构审查类任务，可以继续扩大读取范围，但必须由当前 claim 需要触发，而不是由 `total_lines` 缺口触发。
- `first_missing_range` 只能作为诊断事实，不能作为默认行动义务。

### 17.4 执行顺序调整

新的执行顺序覆盖第 12 节原阶段优先级：

1. **主路径返璞归真**：把主 agent 搜索心智收缩为 rg-like search + exact read，减少工具菜单负担。
2. **契约收口**：更新 `tool_guidance`、`tool_catalog_manifest`、coding environment guidance、evidence alignment rule，明确“读窗口足够性按 claim 判断”。
3. **反馈降权**：修改 `tool_result_projector` / evidence delta / read-resource-state 投影，把 `has_more`、`first_missing_range`、`next_suggested_read` 从 imperative 降为 optional recovery hint。
4. **常态搜索算法增强**：优先优化 `search_text` 的 rg-like 能力、关键词交叉、候选窗口、分页、负结果边界和重复查询抑制。
5. **统一搜索 envelope**：让 `search_files/search_text/glob_paths/python_symbol_search/codebase_search` 共享 locator-only 输出语义和纠偏字段。
6. **前端生命周期**：展示 search lifecycle、运行层、跳过层、范围完整性、candidate windows、locator-only/exact evidence 状态。
7. **升级路径接线**：把 `codebase_search` 做成可见但低频的高级工具或 worker 能力，补齐 native catalog、tool schema、operation authorization、tool runtime 分发和 UI 名称。
8. **真实 agent 验证**：用 CLI 让主 agent 在新会话中完成未知代码定位任务，观察它是否先用 rg-like 搜索收敛候选、再读取必要窗口；复杂任务再升级到 `codebase_search`，且不被 `has_more` 拉偏。

### 17.5 验收标准

- 主 agent 在普通未知代码定位任务中能自然执行 `rg-like search -> read_file` 闭环，而不是并行乱拼多个宽泛搜索。
- 主 agent 只有在 primitive 搜索无法收敛、需要跨层关系或复杂排序时才升级到 `codebase_search`。
- 如果用户问的是“定位并判断某个实现入口”，agent 只读取相关窗口，不会因为文件未完整覆盖而改写成“读完整文件”。
- `search_text` 作为常态 rg-like 入口必须足够顺手：快、可分页、能收窄 scope、能给 read window、能区分 incomplete negative。
- 搜索无命中时，回答必须区分 complete negative 和 incomplete negative。
- 搜索反馈能帮助 agent 纠偏，但不能替 agent 做新的任务目标决策。
- 前端能看见搜索生命周期，而不是只看一串 raw text。

## 18. 双轨搜索体系：常态搜索与网络型深度搜索

搜索体系应分成两条轨道，不能混成一个工具：

```text
常态搜索轨道：低成本、高频、短闭环
网络型深度搜索轨道：高预算、低频、任务图化、大规模整合
```

### 18.1 常态搜索轨道

常态搜索用于 coding agent 每天最常见的定位、阅读、修改前确认。

目标形态：

```text
SearchPrimitive(search_text / rg-like)
-> CandidateWindow
-> read_file exact window
-> claim coverage check
-> answer / edit / refine query
```

常态搜索的技术重点：

- `search_text` 要成为默认顺手入口，底层用 `rg` 的速度和范围控制，不把 agent 逼进复杂工具选择。
- 返回结果必须短、准、可继续：top files、top line hits、recommended read windows、searched scope、complete/incomplete 状态。
- 支持多关键词交叉检索，但作为 rg-like 搜索内部能力，不要求 agent 手动组合多次查询。
- 支持 query refinement：同一 query + same scope + same result hash 不重复投影；scope 或关键词改变才算新搜索。
- `read_file` 消费候选窗口后，应把对应 candidate 标记为 consumed/superseded，避免后续动态尾反复提示同一窗口。

常态搜索不负责：

- 不做大规模 source graph。
- 不负责多来源冲突裁决。
- 不负责生成综合报告。
- 不替 agent 制定新任务。

### 18.2 网络型深度搜索轨道

网络型深度搜索用于大规模检索整合。它不是“更强的 search_text”，而是一个带控制力的搜索 runtime。

适用场景：

- 用户要求跨大量文件、文档、网页、memory、任务记录或工具结果做综合调查。
- 单轮 rg-like 搜索无法收敛，需要多跳查询、证据归并和冲突裁决。
- 需要比较多个候选实现、多个来源版本、多个历史状态。
- 需要产出 evidence packet、source graph、claim matrix、open questions 和后续读取计划。

不适用场景：

- 已知路径读取。
- 单一符号或单一错误文本定位。
- 明确文件范围内的简单正文搜索。
- 普通编辑前确认。

### 18.3 网络型深度搜索的系统形态

目标 runtime：

```text
SearchGoal
-> SearchGraphPlan
-> QueryNode[]
-> RetrieverNode[]
-> EvidenceCandidate[]
-> Read/Fetch Expansion
-> ClaimGraph
-> ConflictResolution
-> EvidencePacket
-> ParentAgent Integration
```

核心对象：

- `SearchGoal`：原始用户目标、范围、时效性、允许来源、预算。
- `SearchGraphPlan`：多跳查询图，不是一次查询列表；每个节点有目的、停止条件和依赖。
- `QueryNode`：一个可执行查询，可面向 workspace、web、memory、docs、git 或 artifact。
- `EvidenceCandidate`：locator-only 候选，携带来源层、置信度、范围完整性、去重 key。
- `Read/Fetch Expansion`：只对高价值候选读取 exact content 或 fetch source。
- `ClaimGraph`：把证据归并到 claim，而不是堆 raw snippets。
- `EvidencePacket`：给父 agent 的可复核输出，包括 positive/negative findings、source refs、limitations、open questions。

### 18.4 控制力要求

网络型深度搜索必须有强控制边界：

- 预算控制：max_queries、max_fetches、max_reads、max_tokens、max_time。
- 停止条件：enough_evidence、query_exhausted、scope_incomplete、budget_exhausted、conflict_unresolved。
- 去重策略：同一 source hash、same claim、same URL/path、same line window 不重复扩展。
- 分层权限：workspace search、web search、fetch_url、memory read、git history 分别授权。
- 失败语义：timeout/truncated/no permission 只能产生 incomplete limitation，不能产生确定否定。
- 父子边界：deep search agent 返回 evidence packet，不替父 agent 做最终产品决策。

### 18.5 与现有系统的融合点

项目已有基础：

- `backend/capability_system/capabilities/deepsearch/` 已有 web deepsearch capability、distillation 和 evidence packet builder。
- `backend/harness/loop/specialist_runtime_router.py` 已能把 `runtime_kind == "search_agent"` 路由到 deepsearch capability。
- `backend/agent_system/profiles/runtime_profile_registry.py` 已有 `web_research_agent` / `runtime.template.deepsearch` 的 runtime config。
- `backend/capability_system/capabilities/codebase_search/` 已有本地 codebase search 的 candidate/evidence envelope 基础。

目标不是新建一套孤立系统，而是把它们统一到一个 `network_search_runtime` 语义下：

```text
workspace_search nodes
web_search/fetch nodes
memory_search nodes
git_history nodes
artifact_search nodes
claim_distillation nodes
evidence_packet builder
```

`deepsearch` 继续作为 web/network 子能力；`codebase_search` 作为 workspace 高级子能力；常态 `search_text + read_file` 作为主 agent 高频路径。

### 18.6 两阶段实施策略

第一阶段只优化常态搜索，不启动网络型大改：

1. 收缩 agent 搜索契约到 `rg-like search -> read_file`。
2. 优化 `search_text` 输出 envelope、分页、candidate windows、negative status。
3. 修正动态反馈，避免 `has_more` 和 coverage 缺口改写目标。
4. 用 CLI 主 agent 实测普通代码定位任务。

第二阶段设计并落地网络型深度搜索：

1. 设计 `SearchGraphPlan` / `EvidenceCandidate` / `ClaimGraph` / `EvidencePacket` 统一模型。
2. 把现有 `deepsearch` 和 `codebase_search` 接为 graph retriever 节点。
3. 建立预算、停止条件、去重、冲突归并和父子 agent integration。
4. 前端展示 search graph、source graph、claim matrix、limitations 和可继续节点。
5. 用大规模任务实测：跨源码+文档+历史记录定位架构事实，并验证 parent agent 不被搜索 runtime 抢走最终决策权。

### 18.7 架构底线

- 常态搜索必须轻，不被网络型深度搜索拖慢或复杂化。
- 网络型深度搜索必须强，不退化成“多搜几次再总结”。
- 两条轨道共享 evidence envelope，但不共享控制策略。
- agent 的最终语义决策权仍在父 agent；搜索 runtime 只提供证据、限制和候选路径。
