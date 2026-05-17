# 142-agent主装配链语义分层与结果级Follow-up修复计划

日期：2026-05-17

## 1. 问题定义

60 轮真实情景测试暴露的问题不是单点 RAG 回答错误，而是主装配链把不同强度的语义信号混在一起：

1. 当前轮明确输入，例如“切到 employees.xlsx”“查今天黄金价格”。
2. 历史恢复出来的对象绑定，例如上一轮或更早的 PDF、表格。
3. 结果级 follow-up，例如“只基于刚才这前五名员工”。
4. 会话级投影写回，例如 active/committed object、result handle、summary refs。

当前系统把历史 `bound_pdf_path` / `bound_dataset_path` 放进了 `explicit_inputs`，导致配方选择阶段把“会话里曾经处理过某个对象”误判成“本轮明确要处理这个对象”。这会让模型本来理解正确的请求，被装配层强行掰到错误 recipe。

正确终态：

- 当前轮明确语义优先于历史绑定。
- 历史绑定只作为 follow-up 候选，不能单独抢路由。
- 结果级 follow-up 优先使用 result/subset/task_summary refs，而不是退回全对象重跑。
- 主 agent 普通长任务继续非图化；TaskGraph 只用于显式多 agent 图任务。
- 不恢复模板机制，不新增重型机制，只修现有主装配链的信号分层和消费顺序。

## 2. 已确认的问题链路

### 2.1 绑定恢复过早变成显式输入

`backend/understanding/task_understanding.py` 的 `_normalize_active_bindings()` 会把 active/committed PDF 和 dataset 合并成：

- `bound_pdf_path`
- `bound_dataset_path`
- `binding_source`

这一步本身可以保留，因为理解层需要知道会话上下文。但问题发生在下一段。

`backend/context_management/resolver.py` 的 `_explicit_inputs()` 会把 `bound_pdf_path` / `bound_dataset_path` 一起写进 `explicit_inputs`。于是后续层无法区分：

- 用户本轮显式给了 `employees.xlsx`
- 系统从旧会话槽里恢复出一个 PDF

### 2.2 配方选择把旧 PDF 放在显式表格和实时搜索前

`backend/tasks/execution_shape_resolver.py` 当前判断顺序中，PDF 条件包含：

```text
explicit_inputs.get("bound_pdf_path")
```

而且 PDF 判断在 dataset 与 realtime search 前面。结果是：

- 本轮显式要求 `employees.xlsx`，但旧 `bound_pdf_path` 存在，选成 `runtime.recipe.pdf_analysis`。
- 本轮要求天气、黄金价格、最新信息，但旧 PDF/dataset 存在，可能被拉回本地对象 recipe。

60 轮测试中的 `turn-12-main.json` 就是典型证据：用户明确切到 `employees.xlsx`，`capability_requests` 也是 `dataset_analysis`，但 `selected_recipe_id` 是 `runtime.recipe.pdf_analysis`。

### 2.3 active_subset 只被识别，没有成为执行级合同

`task_understanding.py` 能识别：

```text
followup_target_kind = active_subset
followup_scope = active_subset
```

但 `backend/tasks/assembly_support.py` 的 `_execution_intent_from_context()` 只把 bundle ordinal follow-up 提升成特殊执行意图。`active_subset` 会落回 `single_task`。

这会造成两个问题：

- “只基于刚才前五名”没有硬约束到 result/subset handle。
- 回答正确时更多依赖上下文摘要碰巧可用，而不是执行链保证正确。

### 2.4 投影写回会放大错误路由

`backend/context_management/projection.py` 和 `backend/orchestration/runtime_loop/task_run_loop.py` 会把执行结果继续写回 active context。若前面 recipe 选错，后面 active object 和 task summary 也可能被错误刷新，从而污染下一轮。

所以这不是“某一轮答错”，而是“错误路由会进入会话记忆并持续影响后续轮次”。

## 3. 修正原则

### 3.1 Restore 不等于 Decide

恢复层可以提供候选，但不能替当前轮做决策。

- `committed_pdf` / `committed_dataset` 是候选。
- `active_pdf` / `active_dataset` 是较强候选。
- 本轮显式路径、明确能力请求、明确 follow-up 语言才是决策信号。

### 3.2 explicit_inputs 只放当前轮显式输入

`explicit_inputs` 不再承载历史 `bound_*`。

它只应该包含：

- `explicit_pdf_path`
- `explicit_dataset_path`
- `explicit_workspace_path`
- 当前轮 `tool_input`
- 当前轮 `capability_requests`
- 当前轮明确的 `followup_target_kind` / `followup_scope`

历史绑定继续进入 `resolved_bindings`，并保留 `source=session_state`、`confidence`、`metadata.slot_name`。

### 3.3 历史绑定必须通过 follow-up 语义才能生效

`bound_pdf_path` 只有在本轮语言像 PDF follow-up 时才能触发 PDF recipe。

`bound_dataset_path` 只有在本轮语言像 dataset follow-up 时才能触发表格 recipe。

如果本轮有显式 dataset path、显式 PDF path、实时查询能力请求，应直接覆盖历史绑定。

### 3.4 结果级 follow-up 优先于对象级 follow-up

当用户说：

```text
只基于刚才这前五名员工，不要回到全表重算
```

系统必须进入结果级 follow-up，而不是“dataset_analysis + 全表路径”。

优先级：

1. `active_subset_handle_id`
2. `active_result_handle_id`
3. `task_summary_refs`
4. 必要时才回退到 active object

### 3.5 普通长任务不图化

本修复不把自然长任务改成 TaskGraph。

主 agent 可自然搜索、读文件、调用子 agent、综合收口。TaskGraph 只用于显式多 agent 图任务。

## 4. 目标设计

### 4.1 信号强度分层

主装配链按以下强度消费信号：

| 层级 | 来源 | 可以做什么 | 不允许做什么 |
| --- | --- | --- | --- |
| 当前轮显式信号 | 用户本轮路径、能力请求、route、tool_input | 直接决定 recipe | 无 |
| 当前轮 follow-up 信号 | active_subset、active_object、bundle_ordinals | 选择结果级或对象级 follow-up | 跳过 refs 直接使用旧对象 |
| active 会话候选 | active_pdf、active_dataset、active_result_handle | 在 follow-up 语义匹配时参与决策 | 单独抢 recipe |
| committed 会话候选 | committed_pdf、committed_dataset | 作为弱候选或歧义提示 | 单独抢 recipe |
| 投影摘要 | task_summary_refs、bundle_summary_refs | 支撑最终综合与后续 follow-up | 替代当前轮显式输入 |

### 4.2 新的主装配顺序

固定执行顺序：

1. `analyze_task_understanding`
   - 识别当前轮显式输入、能力请求、follow-up 类型。
   - 可读取 active bindings，但只标记为上下文候选。

2. `CurrentTurnResolver`
   - `explicit_inputs` 只写当前轮显式输入。
   - `resolved_bindings` 保留历史绑定，并标记来源和置信度。
   - `followup_target_refs` 写入 result/subset/task refs。

3. `TaskIntentContract`
   - bundle 仍为 `bundle_task`。
   - `active_subset` 提升为 `result_followup` 或 `subset_followup`。
   - `active_dataset` / `active_pdf` 提升为 `object_followup`。
   - 普通请求保持 `single_task`。

4. `ExecutionShapeResolver`
   - 先处理显式多 agent bundle。
   - 再处理 realtime/latest/search 能力请求。
   - 再处理本轮显式 PDF/dataset/workspace path。
   - 再处理 result/subset follow-up。
   - 最后才处理对象级 follow-up。
   - 历史 `bound_*` 不能单独触发 recipe。

5. Runtime 执行
   - result/subset follow-up 优先读取 refs/summary。
   - 明确“不回到全表重算”时禁止全对象重算。

6. Projection 写回
   - 只在 recipe 与当前轮意图一致、执行成功时刷新 active object。
   - result/subset follow-up 保留 subset/result handle，不覆盖成旧 PDF 或旧 dataset。

7. Final answer
   - 综合时消费 `task_summary_refs`、result handle、subset handle。
   - 不把工具名、内部 recipe、raw MCP 调用泄漏给用户。

### 4.3 配方选择优先级

新的 recipe 优先级：

```text
bundle_task
  -> runtime.recipe.bundle

latest/search/weather/gold capability
  -> runtime.recipe.information_search

explicit_dataset_path or explicit dataset route
  -> runtime.recipe.structured_data_analysis

explicit_pdf_path or explicit PDF route
  -> runtime.recipe.pdf_analysis

active_subset / result_followup
  -> result/subset follow-up path

active_dataset follow-up with dataset wording
  -> runtime.recipe.structured_data_analysis

active_pdf follow-up with PDF wording
  -> runtime.recipe.pdf_analysis

direct_rag / knowledge lookup
  -> runtime.recipe.knowledge_retrieval

workspace/tool lanes
  -> existing workspace/tool recipes
```

说明：实时搜索放在历史对象绑定前面，是因为“今天”“最新”“黄金价格”“天气”这类请求天然要求外部实时性，不能被本地旧对象抢走。

## 5. 文件级执行清单

### 5.1 `backend/understanding/task_understanding.py`

目标：

- 保留 active/committed binding 的识别。
- 不再让 `bound_*` 表示“本轮显式输入”。
- 给 `active_subset`、`active_dataset`、`active_pdf` 输出清晰的 `followup_target_kind` 和 `followup_scope`。

具体动作：

- 检查 `_normalize_active_bindings()` 输出字段。
- 如需新增字段，只新增轻量诊断字段，例如 `binding_source`、`bound_dataset_source`、`bound_pdf_source`。
- 不新增模板注册或任务模板机制。

完成标准：

- 明确 dataset path + 旧 PDF 时，理解层仍输出 dataset capability。
- “只基于刚才”稳定输出 `active_subset`。
- PDF follow-up 仍能输出 `active_pdf`。

### 5.2 `backend/context_management/resolver.py`

目标：

- 修正 `_explicit_inputs()`，禁止把 `bound_pdf_path` / `bound_dataset_path` 放入 `explicit_inputs`。
- 历史绑定只进入 `resolved_bindings`。
- follow-up refs 要能携带 result/subset/task summary。

具体动作：

- 从 `_explicit_inputs()` 的 key 白名单移除：
  - `bound_dataset_path`
  - `bound_pdf_path`
  - `bound_pdf_mode`
  - `bound_pdf_section`
  - `bound_pdf_pages`
- 如果当前轮是 PDF follow-up，PDF 页码/section 可作为 follow-up 参数保留，但不能伪装成本轮显式 PDF path。
- `_resolved_bindings()` 保留 active/committed/session state binding。
- `followup_target_refs` 优先记录 `active_subset_handle_id`、`active_result_handle_id`、相关 `task_summary_refs`。

完成标准：

- `current_turn.explicit_inputs` 只体现本轮用户明确输入。
- `resolved_bindings` 仍可用于 follow-up 和审计。

### 5.3 `backend/tasks/assembly_support.py`

目标：

- 把 result/subset follow-up 提升到执行意图层。

具体动作：

- `_execution_intent_from_context()` 增加：
  - `active_subset` -> `subset_followup`
  - `active_dataset` / `active_pdf` -> `object_followup`
- `_intent_requested_outputs()` 对 `subset_followup` 增加 `task_summary_refs`、`result_handle_refs` 或等价现有输出。
- diagnostics 保留 `followup_target_kind`，便于测试追踪。

完成标准：

- “只基于刚才前五名”不再是普通 `single_task`。
- bundle ordinal follow-up 行为不变。

### 5.4 `backend/tasks/execution_shape_resolver.py`

目标：

- 修正 recipe 决策顺序。
- `bound_*` 不再单独触发 PDF/dataset recipe。

具体动作：

- 引入本地辅助判断，不新增大机制：
  - `has_explicit_pdf`
  - `has_explicit_dataset`
  - `has_realtime_capability`
  - `followup_target_kind`
  - `has_pdf_followup`
  - `has_dataset_followup`
- 将 realtime/search/latest 判断移到历史对象绑定判断前。
- dataset/PDF recipe 只接受：
  - 当前轮显式路径；
  - 当前轮明确 route/skill/modality；
  - 当前轮 follow-up target 与对象类型匹配。
- 删除或改造 `explicit_inputs.get("bound_pdf_path")` / `explicit_inputs.get("bound_dataset_path")` 作为直接 route 条件。

完成标准：

- stale PDF + explicit dataset -> structured data recipe。
- stale PDF/dataset + weather/gold/latest -> information search recipe。
- stale PDF + active dataset subset follow-up -> subset/dataset follow-up，不进 PDF recipe。

### 5.5 `backend/context_management/projection.py`

目标：

- 避免错误 recipe 的结果继续污染 active context。
- result/subset follow-up 不覆盖原始对象绑定。

具体动作：

- `projection_from_bound_answer()` 与 file work projection 检查 selected recipe / task_kind 是否与当前轮意图一致。
- active subset 的 projection 保留：
  - `active_result_handle_id`
  - `active_subset_handle_id`
  - `active_work_item`
  - `task_summary_refs`
- 不因为最终文本存在就盲目写回旧 `bound_*`。

完成标准：

- turn-13 类 follow-up 后，active subset handle 仍存在。
- turn-14 类综合总结不会清空 active_dataset 或丢失 summary refs。

### 5.6 `backend/orchestration/runtime_loop/task_run_loop.py`

目标：

- 让 final synthesis 和强制收口真正消费 result/subset/task summary refs。

具体动作：

- 检查 `_forced_synthesis` 相关逻辑，避免只拼接 summaries。
- 当 execution_intent 是 `subset_followup` 时，注入明确约束：
  - 只使用指定 subset/result refs。
  - 用户禁止重算时不能回到全表。
- terminal projection 前确认当前轮 recipe 与投影类型一致。

完成标准：

- “不要回到全表重算”成为 runtime 约束，而不是 prompt 期望。

### 5.7 测试文件

需要新增或调整：

- `backend/tests/context_management_current_turn_regression.py`
- `backend/tests/task_understanding_regression.py`
- `backend/tests/main_agent_natural_delegation_regression.py`
- `backend/tests/skill_runtime_regression.py`
- 必要时新增 `backend/tests/execution_shape_resolver_regression.py`
- 60 轮场景相关检查：`backend/tests/system_eval/long_scenarios.py`

## 6. 回归测试矩阵

### 6.1 显式表格覆盖旧 PDF

输入：

```text
现在切到 knowledge/E-commerce Data/employees.xlsx。找出薪资最高的前五名员工。
```

历史：

```text
committed_pdf = 2025年AI治理报告.pdf
committed_dataset = inventory.xlsx
```

期望：

- `explicit_inputs.explicit_dataset_path = employees.xlsx`
- `selected_recipe_id = runtime.recipe.structured_data_analysis`
- 不选 `runtime.recipe.pdf_analysis`

### 6.2 active subset 不回全表

输入：

```text
只基于刚才这前五名员工，按部门归类，不要回到全表重算。
```

期望：

- `followup_target_kind = active_subset`
- `execution_intent = subset_followup`
- 使用 `active_subset_handle_id` 或 `task_summary_refs`
- 不全表重算
- 不选旧 PDF recipe

### 6.3 最新信息覆盖本地对象

输入：

```text
今天黄金价格怎么样？
北京今天天气怎么样？
帮我查 OpenAI API 最新更新。
```

历史：

```text
active_pdf 非空
active_dataset 非空
```

期望：

- `selected_recipe_id = runtime.recipe.information_search`
- 回答时间语义基于当前日期 `2026-05-17`
- 不使用旧的 `2025-05-11` 语义

### 6.4 PDF follow-up 仍然可用

输入：

```text
这份报告第三页讲了什么？
```

历史：

```text
active_pdf = report.pdf
```

期望：

- `followup_target_kind = active_pdf`
- `selected_recipe_id = runtime.recipe.pdf_analysis`
- PDF 页码参数保留

### 6.5 Dataset follow-up 仍然可用

输入：

```text
按仓库展开一下缺口情况。
```

历史：

```text
active_dataset = inventory.xlsx
```

期望：

- `followup_target_kind = active_dataset`
- `selected_recipe_id = runtime.recipe.structured_data_analysis`

### 6.6 多结果综合不丢 refs

输入：

```text
把刚才员工前五名和库存缺口结果合并成一个经营摘要。
```

期望：

- `used_task_summary_refs` 非空或等价结果 refs 非空。
- 不清空 active_dataset。
- 不把任一旧 PDF 误选为主 recipe。

## 7. 实施阶段

### 阶段一：锁住信号分层

范围：

- `task_understanding.py`
- `resolver.py`
- 相关 current turn tests

目标：

- `explicit_inputs` 只保留当前轮显式信号。
- 历史对象只进入 `resolved_bindings`。

验收：

- 单元测试证明旧 PDF 不再出现在 `explicit_inputs`。
- 显式 dataset path 不被旧 PDF 盖掉。

### 阶段二：修正执行意图和 recipe 选择

范围：

- `assembly_support.py`
- `execution_shape_resolver.py`
- execution shape tests

目标：

- active subset 成为执行级合同。
- realtime/latest/search 优先于历史对象绑定。
- bound object 只在 follow-up 语义匹配时触发对象 recipe。

验收：

- turn-12 类请求选择 structured data。
- turn-13 类请求选择 subset/result follow-up。
- weather/gold/latest 请求选择 information search。

### 阶段三：修正投影和最终收口

范围：

- `projection.py`
- `task_run_loop.py`
- file work / runtime loop tests

目标：

- 成功执行后才写回 active context。
- result/subset follow-up 保留 handle 与 summary refs。
- final synthesis 不靠碰巧上下文，而靠 refs 合同。

验收：

- active subset follow-up 不回全表。
- 多结果综合使用 summary refs。
- 错误 recipe 不再污染后续 active context。

### 阶段四：重跑真实情景

范围：

- 60 轮真实情景测试。

目标：

- 不只看通过/失败，还检查语义结构：
  - recipe 是否正确；
  - refs 是否正确；
  - 回答是否遵守当前轮约束；
  - 是否泄漏内部工具名；
  - 是否使用错误日期或旧对象。

验收：

- turn-12/13/14/15/16 相关问题消失。
- 新增回归测试全部通过。

## 8. 不允许的修法

1. 不通过扩大关键词列表单独补 turn-12。
2. 不把普通长任务图化来绕开主装配链问题。
3. 不恢复模板注册表或模板协议。
4. 不把开发说明写进 agent prompt 伪装成任务指令。
5. 不通过测试专用假数据或硬编码响应绕过验证。
6. 不保留无用旧链路作为兼容借口。
7. 不让 `bound_pdf_path` / `bound_dataset_path` 继续出现在 `explicit_inputs` 并参与直接 recipe 选择。

## 9. 风险与控制

### 9.1 风险：普通 follow-up 变弱

例如用户说“继续展开一下”，历史里同时有 PDF 和 dataset。

控制：

- 若只有一个 active object，按 active object follow-up。
- 若 PDF 和 dataset 都 active 且语言不明确，进入歧义处理或要求澄清。
- committed object 不参与抢占。

### 9.2 风险：旧测试依赖 bound 出现在 explicit_inputs

控制：

- 这类测试应更新为检查 `resolved_bindings`。
- 如果旧测试表达的是“历史绑定可追踪”，就不应继续断言它是 explicit。

### 9.3 风险：result/subset follow-up 缺少可执行数据

控制：

- 优先使用 handle。
- handle 不可用时使用 task summary refs。
- refs 与 summary 都不可用时，明确降级并说明无法保证“只基于刚才结果”，不能偷偷回全表。

## 10. 最终判断

可以把当前问题理解为：

```text
大模型很多情况下理解对了，但主装配链把历史恢复信号当成当前轮显式决策信号，导致系统层把它掰错。
```

修复重点不是让模型“更聪明”，而是让系统尊重当前轮语义：

- 当前轮显式输入决定主路由。
- 历史绑定只作为 follow-up 候选。
- 结果级 follow-up 必须走 result/subset refs。
- 投影只在正确执行后写回。

这套修正保持现有框架，不引入新模板、不泛化图任务、不牺牲主 agent 自然长任务能力。
