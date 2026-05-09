# 能力驱动意图识别与 Skill-Tool-MCP 统一路由重构计划书

日期：2026-05-09

## 目标

把当前“理解层硬编码分类 + Skill/Tool/MCP 注册层二次匹配 + Template 层三次分类”的分裂结构，重构为：

1. `能力注册层` 成为能力识别的唯一真相源。
2. `理解层` 只负责抽取基础信号，不再维护大段任务类型分支。
3. `Skill / Tool / MCP` 共用一套候选匹配框架。
4. `bounded_agent` 只作为最终兜底，而不是理解层未覆盖时的默认主路径。
5. 路由、能力、模板三层的分类口径统一，避免同一请求被三次不同逻辑解释。
6. 候选识别、执行授权、模板装配三层职责严格分开，不允许互相吞并真相。

## 现状结论

当前系统已经具备能力注册、能力契约、能力候选、模板装配、运行时授权这些必要部件，但这些部件没有被组织成一条统一主链，而是三套半独立分类同时存在。

### 1. 理解层自己做第一套分类

当前 [task_understanding.py](d:/AI应用/langchain-agent/backend/understanding/task_understanding.py) 直接维护如下直达分支：

- 结构化数据
- PDF
- Skill 编写
- 工作区读文件
- 工作区搜索
- 联网查询
- FAQ
- 知识库问答

没有命中时，直接落到：

```text
route_hint = "agent"
execution_posture = "bounded_agent"
```

这意味着：

1. 理解层本身在决定任务类别。
2. 新增一种能力时，往往需要回到这里补分支。
3. 一旦落入 `bounded_agent`，后续 Skill Policy 不再参与。

### 2. Skill Policy 自己做第二套分类

当前 [skill_policy.py](d:/AI应用/langchain-agent/backend/capability_system/skill_policy.py) 已经具备一套结构化匹配能力，使用：

- `preferred_skill`
- `capability_requests`
- `task_kind`
- `source_kind`
- `modality`
- `routing_hints`
- `examples`

来选择 Skill。

但它有两个结构性限制：

1. 只能在理解层已经给出 `task_kind/source_kind/modality/capability_requests` 后再参与。
2. 一旦 `execution_posture == "bounded_agent"`，直接跳过。

也就是说，Skill 注册信息不是第一层识别依据，而是第二层补充依据。

### 3. Tool Registry 自己做第三套分类

当前 [tool_registry.py](d:/AI应用/langchain-agent/backend/capability_system/tool_registry.py) 也维护一套候选逻辑，使用：

- `capability_tags`
- `supported_modalities`
- `route_hints`
- `safe_for_auto_route`

来选择 Tool。

但这套逻辑只在 `query_understanding` 的特定 route family 内运行：

- `tool`
- `workspace_read`
- `workspace_path_search`
- `workspace_text_search`
- `realtime_network`

因此 Tool 候选不是统一识别层的一部分，而是 route 已经被理解层决定后的局部选择器。

### 4. Template Registry 又做第四套分类

当前 [template_registry.py](d:/AI应用/langchain-agent/backend/tasks/template_registry.py) 会根据：

- `route_hint`
- `execution_posture`
- `preferred_skill`
- `source_kind`
- `modality`
- `capability_requests`

再选一次模板。

这导致真实链路变成：

```text
用户话语
-> task_understanding 分类
-> query_understanding 组装
-> skill/tool 选择
-> template 再分类
-> runtime assembly
```

其中：

- 理解层定义一套任务类别
- Skill Policy 再解释一次能力类别
- Template 再解释一次执行类别

这三层并没有单一权威源。

## 现有配置现状

### Skill 注册层现状

当前 `SKILLS_REGISTRY.json` 中有 4 个 skill：

- `rag-skill`
- `pdf-analysis`
- `structured-data-analysis`
- `skill-creator`

这些 Skill 已经具备较完整的结构化字段：

- `supported_modalities`
- `supported_task_kinds`
- `supported_source_kinds`
- `capability_tags`
- `preferred_route`
- `forbidden_routes`
- `routing_hints`
- `examples`
- `activation_policy`
- `context_mode`
- `route_authority`

结论：

Skill 注册层已经有足够多的机器可用信号，可以参与前置识别，而不是只做后置补选。

### Tool 注册层现状

当前 `TOOLS_REGISTRY.json` 与 [tool_definitions.py](d:/AI应用/langchain-agent/backend/capability_system/tool_definitions.py) 中，Tool 已具备：

- `display_name`
- `operation_id`
- `capability_tags`
- `supported_modalities`
- `safety_tags`
- `route_hints`
- `safe_for_auto_route`
- `runtime_visibility`
- `prompt_exposure_policy`
- `resource_exposure_policy`
- `is_read_only`
- `is_destructive`
- `is_concurrency_safe`

结论：

Tool 注册层也已经具备候选匹配所需的结构字段。

### 运行授权层现状

当前 `agent_runtime_profiles.json` 中主会话 Agent `agent:0` 允许：

- `op.mcp_retrieval`
- `op.mcp_pdf`
- `op.mcp_structured_data`
- `op.read_file`
- `op.search_files`
- `op.search_text`
- `op.web_search`
- `op.fetch_url`
- `op.write_file`
- `op.edit_file`
- `op.shell`

阻断：

- `op.python_repl`

同时 Tool 定义中又存在：

- `runtime_visibility = main_runtime`
- `runtime_visibility = agent_internal`

结论：

当前系统已经有“候选能力”和“最终授权能力”的分层，只是理解层没有复用这层结构，而是自己先做了硬编码决策。

## 根问题

根问题不是某个 Skill 的 `description` 不够好，也不是某个 `routing_hints` 少写了几条，而是当前能力识别结构违背了“单一注册源 + 分层过滤”的原则。

具体表现为：

1. 能力识别入口不在能力注册层，而在 `task_understanding.py`。
2. Skill / Tool / Template 分别维护自己的分类口径。
3. `bounded_agent` 出现得太早，导致注册层无法参与纠偏。
4. `preferred_route`、`route_authority`、`activation_policy` 这些字段没有真正成为统一路由协议的一部分。

## 设计原则

本次重构遵循两组原则：

### A. 来自 `docs/设计原则`

1. 单一来源
   - 能力注册必须有唯一真相源，过滤逻辑叠加在注册层之上。
   - 必须存在唯一候选入口模块，Skill / Tool / MCP 不允许在不同层各自重新扫注册表。
2. 分层过滤
   - 先注册，后过滤，再授权，而不是先硬分类再补路由。
3. 能力发现与权限判定分离
   - 候选能力识别不等于允许执行。
   - `allowed_operations / blocked_operations` 只能影响“是否可执行”，不能抹掉“它本来是不是合理候选”。
4. Markdown/frontmatter 能力配置应承担结构化职责
   - Skill 的注册字段必须参与机器决策，不只是给人看。
   - 命中率问题优先回到 Skill/Tool/MCP 注册契约修正，而不是优先往理解层补特判。

### B. 来自当前项目约束

1. 不保留无意义兼容层
   - 新结构成为主链路后，旧的重复分类逻辑应逐步清除。
2. 少做补丁式修改
   - 不继续在 `task_understanding.py` 无限制扩展 if/else。
3. 先解决结构，再做局部体验优化
   - 先统一路由权威，再谈每个能力的细节命中率。

## 原则到现有代码的约束映射

为了保证本计划书不是“原则口号”，这里把设计原则直接映射到当前代码责任边界。

### 1. 单一注册源 -> 候选入口唯一

对应原则：

- `09-工具系统设计.md` 的单一注册源
- `25-架构模式总结.md` 的唯一注册入口 + 分层过滤

落地约束：

1. `task_understanding.py` 不再直接产出 Skill/Tool/MCP 结论。
2. `skill_policy.py`、`tool_registry.py`、MCP catalog 不再在各自层级单独成为“第一识别入口”。
3. 全系统只能由 `capability_candidate_matcher.py` 统一读取注册契约并产生候选。

### 2. 能力发现与权限判定分离 -> 不得把未授权伪装成未识别

对应原则：

- `16-权限系统.md` 的“规则链只决定 allow / ask / deny，不重写对象事实”
- `25-架构模式总结.md` 的“权限管线是后置防线，不是识别器”

落地约束：

1. `agent_runtime_profiles.json`、`allowed_operations`、`blocked_operations` 只能影响执行阶段。
2. 若某能力命中但未授权，diagnostics 必须保留：
   - 它为什么是候选
   - 它为什么不能执行
3. 禁止因为当前 runtime profile 不允许，就在候选阶段静默删掉该能力。

### 3. 注册契约驱动机器判断 -> 优先修注册，不优先补理解层特判

对应原则：

- `24-Skill-Plugin开发实战.md` 的 frontmatter/注册字段作为机器契约
- `15-MCP-协议实现.md` 的“多来源配置统一收敛后再消费”

落地约束：

1. Skill 命中差，优先修：
   - `supported_task_kinds`
   - `supported_source_kinds`
   - `capability_tags`
   - `routing_hints`
   - `examples`
2. Tool 命中差，优先修：
   - `operation_id`
   - `capability_tags`
   - `supported_modalities`
   - `route_hints`
3. MCP 命中差，优先修 MCP unit/catalog 的结构字段，不先给 `task_understanding.py` 加专用分支。

### 4. 模板层消费裁决结果 -> 模板层不再自建语义真相

对应原则：

- `25-架构模式总结.md` 的“注册 -> 过滤 -> 使用”分层

落地约束：

1. `template_registry.py` 只能根据 `CapabilityResolution` 选模板。
2. 不允许模板层再根据 `route_hint/source_kind/modality` 自己重新推导“这其实是什么任务”。
3. 模板无法承接时，应暴露为模板问题，而不是倒推成理解失败。

## 目标模块分层

重构后必须形成下面四个明确模块边界，实施时不允许职责回流。

### A. Signal Extraction 层

责任模块：

- [task_understanding.py](d:/AI应用/langchain-agent/backend/understanding/task_understanding.py)

只负责：

- 文本归一化
- 路径 / URL / 文件类型 / freshness / binding / workspace intent 信号抽取

明确不负责：

- 判定这是哪个 Skill
- 判定应该走哪个 Tool
- 判定是否进入 bounded_agent

### B. Capability Candidate Matching 层

责任模块：

- 新增 [capability_candidate_matcher.py](d:/AI应用/langchain-agent/backend/understanding/capability_candidate_matcher.py)

只负责：

- 从 Skill / Tool / MCP 注册契约生成统一候选集合

明确不负责：

- 权限判断
- 模板选择
- 最终执行姿态裁决

### C. Capability Arbitration 层

责任模块：

- 新增 `capability_resolution.py`
- `query_understanding.py` 改为消费该层结果，而不是自己补 route 分支

只负责：

- 候选排序
- 选择主候选
- 产出统一 `execution_posture`
- 记录未入选原因与未授权原因

明确不负责：

- 重新扫注册表
- 静默吞掉未授权候选

### D. Template Selection / Runtime Authorization 层

责任模块：

- [template_registry.py](d:/AI应用/langchain-agent/backend/tasks/template_registry.py)
- 运行时 profile / operation gate

只负责：

- 消费 `CapabilityResolution`
- 选择装配模板
- 判定 operation 是否允许执行

明确不负责：

- 重写能力类别
- 把模板不支持伪装成识别失败

## 现有代码的退位清单

下面这些旧职责在实施时必须被削弱或移除，否则结构不会真正收敛：

1. [task_understanding.py](d:/AI应用/langchain-agent/backend/understanding/task_understanding.py)
   - 退出“主分类器”角色
   - 删除大多数 `_build_direct_*_task` 的主路径职责
2. [skill_policy.py](d:/AI应用/langchain-agent/backend/capability_system/skill_policy.py)
   - 退出“第二套识别器”角色
   - 保留为 Skill 候选解释/排序输入，或并入统一裁决层
3. [tool_registry.py](d:/AI应用/langchain-agent/backend/capability_system/tool_registry.py)
   - 退出“特定 route family 才参与”的局部识别器角色
   - 其候选逻辑必须前移进入统一候选层
4. [template_registry.py](d:/AI应用/langchain-agent/backend/tasks/template_registry.py)
   - 退出“再猜一次任务类型”的角色

## 硬性验收约束

计划实施完成后，以下断言必须同时成立，否则视为计划未严格遵循设计原则：

1. 新增一个 Skill，主要通过注册字段就能参与候选，不需要先改 `task_understanding.py`。
2. 一个能力即使未授权，也能在 diagnostics 里看到“已识别但不可执行”。
3. `bounded_agent` 只能在“没有高置信候选胜出”时出现，不能作为理解层默认出口。
4. `template_registry.py` 不再独立维护一套与能力候选平行的任务分类真相。
5. Skill / Tool / MCP 三类能力的候选来源都能追溯到同一入口模块。

## 目标结构

重构后主链路应变为：

```text
用户话语
-> Signal Extraction
-> Capability Candidate Matching
-> Capability Arbitration
-> Template Selection
-> Runtime Authorization
-> Execution
```

并且必须满足以下硬约束：

1. 全系统只有一个候选生成入口。
2. 候选生成结果在进入授权层之前，不得被权限配置提前删改。
3. Template 层只能消费能力裁决结果，不能重新定义候选真相。

### 1. Signal Extraction

由理解层只抽取基础信号，不直接选能力。

建议保留的信号包括：

- 是否显式文件路径
- 是否显式 URL
- 是否本地知识范围
- 是否页码/章节引用
- 是否 workspace 读取意图
- 是否 workspace 搜索意图
- 是否联网/最新/实时要求
- 是否能力系统编写意图
- 是否写入/修改/生成意图
- 当前 active bindings

该层只产出：

- `signals`
- `source anchors`
- `interaction intent`

不直接产出具体 `preferred_skill`。

### 2. Capability Candidate Matching

引入统一能力候选层，并且规定它是全系统唯一候选入口。

建议新增：

- `backend/understanding/capability_candidate_matcher.py`

由它统一扫描：

- Skills
- Tools
- MCP Units

Skill / Tool / MCP 不允许在理解层、模板层、装配层各自再次直接扫描注册表做平行候选。

每个候选统一输出：

- `candidate_type`: `skill | tool | mcp`
- `candidate_name`
- `operation_id`
- `match_reasons`
- `specificity`
- `safety_class`
- `activation_policy`
- `route_authority`

其中：

- Skill 候选来自 `SKILLS_REGISTRY.json`
- Tool 候选来自 `TOOLS_REGISTRY.json`
- MCP 候选来自 local mcp registry / capability catalog

该层只回答一件事：

```text
哪些已注册能力可以解释当前请求
```

它不负责决定：

- 现在是否允许执行
- 最终选哪个模板
- 是否需要人工确认

### 3. Capability Arbitration

新增统一裁决层，负责：

1. 在多个候选之间排序。
2. 把候选能力映射为统一执行姿态：
   - `direct_rag`
   - `direct_mcp`
   - `builtin_tool_lane`
   - `task_runtime`
   - `bounded_agent`
3. 记录为什么没有选中其它候选。

这里才允许使用：

- `route_authority`
- `preferred_route`
- `safe_for_auto_route`
- `runtime_visibility`

但这里仍然不得做的事：

1. 不得因为某个 operation 当前未授权，就把候选能力从候选集合中删除。
2. 不得把“未授权”伪装成“未识别到候选能力”。
3. 只能把未授权记录为：
   - `not_executable`
   - `authorization_denied`
   - `requires_confirmation`
   - `runtime_visibility_blocked`

也就是说，裁决层可以决定“最终激活哪个候选能力”，但不能用授权失败覆盖识别真相。

### 4. Template Selection

Template 层不再自己重新解释请求语义，而只消费裁决结果。

也就是说：

- Template 只根据统一 `resolved_capability` 和 `execution_posture` 选模板。
- 不再直接依赖散落的 `route_hint == "pdf"` 之类规则作为主判据。
- 不允许重新扫描 Skill / Tool / MCP 注册表生成第二套候选能力。
- 不允许把“模板无法承接”反推回“理解层没识别到能力”。

## 数据结构重构建议

### 新增 `CapabilitySignalFrame`

建议放在 `backend/understanding/`：

```text
message
normalized_message
source_signals
intent_signals
binding_signals
structural_signals
```

### 新增 `CapabilityCandidate`

统一表示 Skill / Tool / MCP 候选：

```text
candidate_type
name
display_name
operation_id
preferred_route
route_authority
supported_task_kinds
supported_source_kinds
supported_modalities
capability_tags
match_score
match_reasons
safety_summary
runtime_visibility
```

### 新增 `CapabilityResolution`

统一表示最终裁决：

```text
selected_candidate
execution_posture
route
preferred_skill
tool_name
operation_ids
fallback_used
diagnostics
```

## 分阶段实施

### 第一阶段：抽离能力候选层

目标：

在不打断现有运行链的情况下，把 Skill / Tool / MCP 统一候选能力先建出来。

动作：

1. 新增 `capability_candidate_matcher.py`
2. 读取 Skill / Tool / MCP 注册表，产出统一候选对象
3. 让现有 `query_understanding` 挂上 `candidate_capabilities`
4. 暂不删除旧分支，只做并行观测
5. 规定后续所有新能力候选逻辑只能进入该模块，不允许在别处新开平行入口

完成标准：

1. 每次请求都能看到候选能力列表。
2. 候选列表能覆盖现有 `rag/pdf/structured_data/workspace/web` 主路径。
3. Skill / Tool / MCP 候选格式统一。

### 第二阶段：理解层降级为信号提取层

目标：

让 `task_understanding.py` 不再承担主分类职责。

动作：

1. 保留路径、URL、binding、freshness、本地知识等信号提取。
2. 删除大部分 `_build_direct_*_task` 的一级决策职责。
3. 把“这是 pdf / dataset / workspace / skill-authoring”改为候选匹配层判断。
4. 明确规定：命中率问题优先修注册契约，不优先补理解层特判。

完成标准：

1. `task_understanding` 不再直接决定大多数 `preferred_skill`。
2. 新增 Skill 不需要优先修改 `task_understanding.py` 才能参与识别。
3. 同类能力的匹配行为优先由注册字段驱动，而不是理解层分支驱动。

### 第三阶段：统一裁决层替换现有 route 分支

目标：

让 `query_understanding.py` 不再只是“读取 task_understanding 结果后补 tool”，而是消费统一候选并完成裁决。

动作：

1. 新增 `capability_resolution` 过程。
2. 替换 `route in {"rag","pdf","structured_data"}` 这种硬编码分支。
3. 把 `bounded_agent` 改为“无高置信候选时才启用”。
4. 未授权能力仍保留在候选与裁决诊断中，不允许被静默抹除。

完成标准：

1. `skill-creator`、`rag-skill`、`pdf-analysis`、`structured-data-analysis` 都通过统一候选裁决命中。
2. Tool 自动路由也改为同一裁决框架。
3. 能力识别失败与能力未授权失败可以在 diagnostics 中明确区分。

### 第四阶段：Template 选择改消费裁决结果

目标：

消除 Template 层的重复解释。

动作：

1. `template_registry.py` 改为优先读取 `capability_resolution`
2. 缩减 `route_hint / preferred_skill / source_kind` 的重复分支
3. 把模板匹配原因改成“来自能力裁决”而不是“再次猜”
4. 禁止 Template 层重新构造第二套候选能力

完成标准：

1. Template 层不再维护与理解层平行的分类真相。
2. 同一个请求的 route / skill / template 原因链一致。

### 第五阶段：清理旧兼容逻辑

目标：

移除重复分类与长期无意义兜底。

动作：

1. 清理旧 `_build_direct_*_task` 中已被候选层替代的逻辑
2. 清理 Template Registry 的旧 heuristic fallback 分支
3. 将 `bounded_agent` 降为最终兜底并暴露 diagnostics

完成标准：

1. 主路径不再依赖三套分类并存。
2. fallback 只有一条最终入口。

## 影响文件

### 核心后端

- `backend/understanding/task_understanding.py`
- `backend/understanding/query_understanding.py`
- `backend/capability_system/skill_policy.py`
- `backend/capability_system/tool_registry.py`
- `backend/tasks/template_registry.py`
- `backend/orchestration/agent_runtime_chain.py`

### 建议新增

- `backend/understanding/capability_candidate_matcher.py`
- `backend/understanding/capability_resolution.py`
- `backend/tests/capability_candidate_regression.py`
- `backend/tests/capability_resolution_regression.py`

## 验证矩阵

### Skill 路由

- `帮我创建一个用于章节审核的 skill` -> `skill-creator`
- `检查这个 SKILL.md 是否适合给 agent 使用` -> `skill-creator`
- `从知识库里解释退款规则` -> `rag-skill`
- `这份 PDF 第三页讲了什么` -> `pdf-analysis`
- `inventory.xlsx 里销量前五有哪些` -> `structured-data-analysis`

### Tool 路由

- `打开 backend/.../task_understanding.py 给我看看源码` -> `read_file`
- `帮我搜索仓库里有哪些 task graph 文件` -> `search_files`
- `帮我联网查 OpenAI API 最新更新` -> `web_search`

### Fallback

- 普通闲聊或复杂混合模糊请求 -> `bounded_agent`
- fallback 必须带 diagnostics，说明为什么没有明确候选能力胜出

## 不允许的反模式

1. 再往 `task_understanding.py` 大量追加能力专用 if/else。
2. 让 Template 层继续维护第二套独立任务分类标准。
3. 用 `description` 文本猜测来替代结构化注册字段。
4. 把 `bounded_agent` 当成默认主路径而不是最终兜底。
5. 只改前端文案，不修后端路由权威。
6. 因为 runtime profile 未授权，就在识别层把候选能力静默删掉。
7. 因为某个 Skill 命中率不好，就优先在理解层写专用补丁，而不先修注册契约。

## 最终状态

重构完成后，系统应达到：

1. 新增一个 Skill，主要通过注册字段即可进入识别链。
2. Tool/MCP/Skill 都通过统一候选模型参与匹配。
3. 理解层、能力层、模板层共享一条一致的原因链。
4. 权限系统只负责“是否允许执行”，不再承担“这是哪类能力”的补洞职责。
5. `bounded_agent` 变成真正的最后兜底，而不是结构缺口的常态出口。
