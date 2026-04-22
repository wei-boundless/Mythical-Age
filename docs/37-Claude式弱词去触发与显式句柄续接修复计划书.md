# Claude式弱词去触发与显式句柄续接修复计划书

> 目的：针对当前系统把“那、再、呢”这类泛指词误当成结构化续接触发器，进而触发 `history_fallback` 误绑旧 `.xlsx`、拖偏主链的问题，基于当前项目真实代码状态，重新设计一套“强信号触发 + 显式句柄续接 + 恢复层降权”的修复方案。  
> 本文不是调几个关键词的补丁清单，而是一份围绕续接协议重排的专项计划书。

---

## 1. 先给结论

这次问题的核心，不是模型“理解错了一个词”，而是我们把本来只能作为自然语言衔接词的弱信号，升级成了结构化工具续接信号。

当前错误链路是：

`“那 / 再 / 呢”`
-> `QueryContinuationResolver.promote_structured_query()`
-> 把当前轮升级成 `structured_data_analysis`
-> `StructuredBindingResolver.resolve()`
-> `history_fallback`
-> 从历史里捡到旧 dataset
-> 主链被拖到 `.xlsx`

这条链路违反了之前 docs 一直强调的几条原则：

- 当前轮真相必须优先于恢复态
- 恢复层只能恢复，不能裁决
- 主线程不能靠模糊文本去猜 task-local owner
- follow-up 必须尽量走显式句柄，而不是走弱词启发

所以本轮修复目标很明确：

1. 去掉“弱词 => structured follow-up”的主路径
2. 把结构化续接收敛到“显式句柄 / 强对象信号 / 已确认 binding owner”
3. 让 `history_fallback` 退回成最后兜底，而不是主绑定入口
4. 明确 planner、follow-up、binding、runtime 各自只做什么，不再互相越权

---

## 2. Claude Code 给我们的直接启发

这次我已经对照本地 Claude Code 源码做过核实，结论可以直接定下来：

### 2.1 Claude Code 没有把弱泛指词当成结构化续接触发器

在本地源码中，没有发现类似下面这种链路：

- 检测“那 / 再 / 呢”
- 直接推定“继续刚才那个结构化对象”
- 再从历史里绑定某个 `.xlsx` / dataset

能确认到的 `.xlsx` 只出现在文件扩展名常量里，而不是续接/绑定子系统里。

### 2.2 Claude Code 的续接更接近两类机制

第一类：显式 worker handle

- `SendMessage`
- `to = agent ID`
- `<task-id>` 本身就是续接主键

第二类：显式 session resume

- `--continue`
- `--resume`
- `session id`

它的设计重心是：

- 续接谁，要么有显式句柄
- 恢复哪段对话，要么有显式 session
- 而不是靠当前轮出现一个模糊代词，就把某个历史对象重新激活

### 2.3 能借鉴的不是“Claude 的某个关键词表”，而是它的纪律

对我们真正有价值的是这三条纪律：

1. handle-first  
   先找显式 owner，再谈续接。

2. restore-not-decide  
   恢复层补上下文，不决定当前轮真相。

3. weak-language-is-not-ownership  
   “那 / 再 / 呢”这类自然衔接词，不足以代表结构化对象所有权切换。

---

## 3. 当前项目里的真实问题链

这部分只描述当前代码现状，不做理想化假设。

### 3.1 `continuation_resolver` 越权升级了结构化路由

文件：

- `backend/query/continuation_resolver.py`

当前 `promote_structured_query()` 中，`followup_markers` 包含：

- `再`
- `那`
- `呢`

这意味着：

- 只要消息够短
- 又没有被更高优先级路由抢走
- 历史里出现过 dataset

当前轮就可能被提前提升成 `structured_data_analysis`。

这一步的问题不在于“词表是否完整”，而在于：

> 它把语言衔接信号误当成了结构化对象续接信号。

### 3.2 `binding_resolver` 把历史兜底变成了事实绑定

文件：

- `backend/query/binding_resolver.py`

当前逻辑里，只要已经进了 structured 路由：

- 先看 `tool_input.path`
- 再看显式路径
- 再看语义默认
- 最后走 `StructuredDataCatalog.resolve_dataset_path_from_history()`

最后这一段会直接生成：

- `source="history_fallback"`
- `confidence=0.55`

问题不是它“不该存在”，而是：

> 在前面的 structured 提升本身就是弱词触发时，这个 fallback 被错误地抬成了绑定 owner。

### 3.3 `followup_resolver` 和 `continuation_resolver` 没有清晰分工

文件：

- `backend/query/followup_resolver.py`
- `backend/query/continuation_resolver.py`

现在两者同时在做“续接判断”，但职责边界不够硬：

- `followup_resolver` 偏向显式 task / binding handle
- `continuation_resolver` 偏向文本/历史推断

但一旦 `followup_resolver` 没命中，系统就会自然滑回“弱文本 + 历史猜测”。

结果就是：

- 句柄链没有命中
- 系统却没有停在“普通问答/普通规划”
- 而是被弱启发式硬推到了结构化工具

### 3.4 `planner` 允许 continuation promotion 先于 binding owner 确认

文件：

- `backend/query/planner.py`

当前 `_build_execution()` 的顺序是：

1. `analyze_query_understanding()`
2. `continuation_resolver.resolve()`
3. `binding_resolver.resolve()`
4. `tool_input_resolver.resolve()`

问题是：

- structured promotion 发生在 binding owner 明确之前
- binding resolver 只能被动接这个已升级的 route
- 后面即便没有显式 owner，也已经进入结构化通道

这会让“路由升级”先于“对象确认”。

### 3.5 `history_fallback` 没有前置保护条件

当前系统缺少一条硬门：

> 只有当前轮已经存在足够强的结构化对象信号时，才允许历史层参与 dataset 补全。

现在的实际情况更像是：

- 先弱词触发 structured
- 再让历史给这个 structured 路由找对象

顺序反了。

---

## 4. 这次修复必须遵守的设计原则

下面这些不是建议，而是硬约束。

### 4.1 弱词不能拥有结构化对象的所有权

“那、再、呢、继续、然后”这类词，只能代表：

- 对话还在继续
- 用户可能在承接前文

不能单独代表：

- 继续某个 dataset
- 继续某个 pdf
- 继续某个 tool binding

### 4.2 结构化续接必须满足“对象先行”

只有以下几类信号，才有资格推动结构化续接：

1. 显式对象
   - 文件名
   - 扩展名
   - “这个表 / 那张表 / 刚才那个表”这类明确对象短语

2. 显式句柄
   - `task_ref`
   - `binding_ref`
   - 已确认的 `binding_owner_task_id`

3. 强结构化操作语义
   - `top N`
   - 排名
   - 按列分组
   - 汇总
   - 筛选
   - 这些操作本身已经明显指向表格/数据分析

如果没有这些对象信号，不能只凭“那 / 再 / 呢”进入结构化工具。

### 4.3 恢复层只能在“已明确结构化语境”下补对象

`history_fallback` 不是罪魁祸首，但它只能在下面前提下启用：

- 当前轮已经确定是结构化问题
- 且当前轮只缺对象，不缺类型

反过来，如果当前轮连“是不是结构化问题”都还不确定，就绝不能让历史层来帮它定性。

### 4.4 显式句柄优先于文本启发

优先级必须稳定为：

1. 显式 file / task / binding handle
2. 显式对象短语
3. 强结构化操作语义
4. 当前轮普通理解
5. 恢复层兜底

不能再出现：

- 弱文本启发先升级路由
- 历史兜底再补对象
- 最后反过来污染主线程

### 4.5 不通过继续追加 patch 解决

这次不接受下面这种修法：

- 在十几个地方分别加黑名单词
- 在 runtime 末端再补一个“如果像误绑就撤回”
- 在 prompt 里加一句“不要乱理解‘那’”

本轮要求的是：

- 调整链路顺序
- 缩小模块职责
- 删除越权判断

---

## 5. 目标架构

本轮修完之后，structured continuation 的目标结构应当是：

### 5.1 第一层：Follow-up Handle Layer

职责：

- 识别当前轮是否在显式续接某个既有 task / binding owner

允许输出：

- `task_ref`
- `compound_subset`
- `binding_ref`

不允许输出：

- 伪造新的 dataset binding
- 仅凭弱词决定 structured route

### 5.2 第二层：Strong Structured Intent Layer

职责：

- 只根据当前轮显式对象或强结构化操作，判断是否是结构化分析请求

允许信号：

- 文件名/扩展名
- 明确“表/数据表/数据集”
- 排名、分组、汇总、筛选、top N、按列分析

禁止信号：

- `那`
- `再`
- `呢`
- 单独的“继续”

### 5.3 第三层：Binding Resolution Layer

职责：

- 在“已经确认是结构化请求”的前提下，为其补足 dataset owner

解析顺序：

1. prebound tool input
2. explicit path
3. binding owner task
4. explicit object phrase
5. current-turn semantic default
6. guarded history fallback

关键变化：

- `history_fallback` 必须是 guarded fallback
- 必须依赖前置的强结构化确认

### 5.4 第四层：Runtime Consumption Layer

职责：

- 当 `binding_ref` 命中时，直接走 owner task 局部续接
- 不再回到普通 planner fresh route 重新猜

这层的重点不是新加很多结构，而是保证：

- 句柄命中后不丢失
- 没命中时也不要由弱词把请求硬推到 structured 路由

---

## 6. 分阶段实施方案

### Phase 0：冻结错误语义入口

目标：

- 先把最危险的错误入口关掉

要做的事：

1. 从 `QueryContinuationResolver._looks_like_structured_followup()` 中移除弱词触发
2. 不再让 `再 / 那 / 呢` 成为 structured promotion marker
3. 保留真正指向表格分析的强词

本阶段完成后应满足：

- 普通承接句不会因为弱词直接变成 `structured_data_analysis`

### Phase 1：重写 structured promotion 的准入条件

目标：

- 让 `promote_structured_query()` 只在强结构化语境下触发

准入条件改成三选一：

1. 当前轮显式提到 dataset/file
2. 当前轮出现明确表格对象短语
3. 当前轮包含强结构化分析操作

禁止：

- 只因消息短
- 只因历史里有过 dataset
- 只因出现“继续/再/那”

### Phase 2：给 `history_fallback` 加前置门

目标：

- 把历史兜底从“主绑定入口”降成“缺对象时的最后兜底”

需要新增一条明确判断：

- 只有 `understanding` 已被强信号判定为 structured
- 且当前轮不存在显式反向语义
- 且当前轮不是纯总结/表达重写/管理层压缩

才允许 `history_fallback`

重点：

- `history_fallback` 不再参与“是否 structured”的裁决
- 它只参与“structured 已确定后的对象补全”

### Phase 3：把对象短语解析和弱词彻底分开

目标：

- 明确哪些短语是对象指向，哪些只是衔接语气

对象短语例子：

- 这个表
- 那张表
- 刚才那个表
- 这个数据表
- 这份表格

弱词例子：

- 那
- 再
- 呢
- 然后

要求：

- 对象短语必须是完整片段
- 不能降解成单字匹配

### Phase 4：统一 planner 中“先定对象，再补输入”的顺序约束

目标：

- 防止 planner 先被 continuation 升级，再被 binding fallback 接管

要落实的顺序纪律：

1. 先尝试显式 follow-up handle
2. 再判断当前轮是否具备强结构化语义
3. 再做 binding resolve
4. 最后才做 tool input resolve

这里不一定要求大改调用顺序，但至少要保证语义上：

- route promotion 依赖强结构化确认
- binding fallback 不能反向决定 route

### Phase 5：补齐回归测试矩阵

目标：

- 防止以后再把弱词重新加回去

必须覆盖的用例：

1. 弱词承接但非结构化
   - “把刚才那三类风险压成三条”
   - 不能路由到 `structured_data_analysis`

2. 明确对象承接
   - “把那个表按部门汇总”
   - 可以续接 dataset

3. 明确文件路径
   - “看 employees.xlsx 前十条”
   - 必须命中显式 dataset

4. 强结构化操作但无历史对象
   - “按部门统计人数”
   - 若无对象，宁可回普通澄清/普通路由，也不能乱绑旧表

5. 总结/改写型 follow-up
   - “把刚才那三类风险改成管理层版本”
   - 应续接 task/result，不应续接 dataset binding

### Phase 6：删除旧错误假设

目标：

- 收尾清理，防止以后又从旁路复活

要删除/收紧的内容：

1. continuation 里基于单字弱词的 structured marker
2. 依赖短消息长度推 structured follow-up 的隐含前提
3. 没有强结构化前提时的裸 `history_fallback`

---

## 7. 逐文件执行清单

### 7.1 `backend/query/continuation_resolver.py`

职责调整：

- 从“弱词 + 历史”升级 structured
- 改成“强结构化信号”升级 structured

具体修改：

1. 重写 `_looks_like_structured_followup()`
2. 删除单字弱词：
   - `再`
   - `那`
   - `呢`
3. 区分三组信号：
   - 显式 dataset/object
   - 强结构化分析操作
   - 禁止单独触发的弱衔接词
4. 必要时新增私有帮助函数，而不是继续把所有词塞进一个 tuple

删除点：

- 不再保留“弱词命中即可 structured”的逻辑

### 7.2 `backend/query/binding_resolver.py`

职责调整：

- 从“只要是 structured 就可以直接历史补”
- 改成“只有强结构化上下文成立时才允许 fallback”

具体修改：

1. 为 `history_fallback` 增加 guard 条件
2. 把“显式对象短语”和“弱衔接词”彻底分开
3. 如果当前轮更像改写/总结/压缩，而不是分析表格，则不允许 fallback 绑旧表

删除点：

- 裸 `history_fallback`

### 7.3 `backend/query/planner.py`

职责调整：

- 保证 structured promotion 和 binding resolve 的顺序语义正确

具体修改：

1. 检查 `_build_execution()` 中 continuation -> binding -> tool_input 的链路
2. 明确 `binding_resolver` 不能反向替 continuation 决定 route
3. 如有必要，在 plan 构建时增加“structured 判定来源”字段，便于后续 guard

目标：

- planner 不再把“弱词造成的假 structured”送进后续 binding 链

### 7.4 `backend/query/followup_resolver.py`

职责调整：

- 继续只做显式 handle / object reference 解析
- 不向弱词让步

具体修改：

1. 保持 `binding_ref` 的显式对象解析
2. 检查对象短语匹配是否存在过宽模式
3. 明确：这里识别“那个表”，但不识别单独“那”

目标：

- 把对象指向与语气衔接彻底拆开

### 7.5 `backend/query/tool_input_resolver.py`

职责调整：

- 只消费上游已确认的 binding
- 不重新承担 dataset 事实裁决

具体修改：

1. 检查没有 `path` 时的 fallback 行为
2. 如果当前 execution 没有强 binding owner，不要在这里补出历史 dataset
3. 确保它只是 input filler，而不是 owner decider

### 7.6 `backend/query/runtime.py`

职责调整：

- 继续让 `binding_ref` 命中后优先走局部续接
- 且在没命中句柄时，不让弱 continuation 偷偷把请求拖进 structured tool

具体修改：

1. 检查 `_stream_binding_followup()` 所依赖的 owner task 获取逻辑
2. 确认 `binding_ref` 命中后不会回落到 fresh planner 重新猜对象
3. 确认普通 planner 路径不会因弱 structured promotion 再次污染主线程

### 7.7 `backend/tests/...`

需要新增或重写的回归测试：

1. `continuation_resolver` 单测
2. `binding_resolver` 单测
3. planner 集成测试
4. 长场景回归

重点断言：

- 弱词不再触发 structured route
- `history_fallback` 只有在强结构化前提下才会生效
- “刚才那三类风险”不会绑定到 `employees.xlsx`

---

## 8. 推荐实施顺序

严格按这个顺序做，避免再出现边改边偏：

1. 先改 `continuation_resolver`
2. 再改 `binding_resolver`
3. 再审 `planner`
4. 然后收紧 `tool_input_resolver`
5. 最后跑测试并清理旧分支

原因：

- 根因入口在 continuation
- 最危险的误绑放大器在 binding fallback
- planner 和 tool input 是承接层，不应先动

---

## 9. 验收标准

本轮完成后，至少要满足下面这些标准：

### 9.1 行为标准

1. “把刚才那三类风险压成适合管理层汇报的三条”
   - 不得路由到 `structured_data_analysis`
   - 不得绑定任何历史 `.xlsx`

2. “把那个表按部门汇总”
   - 如果最近存在明确 dataset owner，可续接

3. “employees.xlsx 按部门汇总”
   - 必须命中显式 dataset

4. “再看一下”
   - 不能仅凭这句话进入 structured tool

### 9.2 结构标准

1. structured promotion 不再依赖单字弱词
2. `history_fallback` 不再参与 route 定性
3. 显式对象和语气弱词彻底拆分
4. `tool_input_resolver` 不再偷偷重建历史 dataset owner

### 9.3 维护性标准

1. 不新增一堆补丁分支
2. 不用 prompt 文案替代链路修复
3. 修改后逻辑应比当前更短、更硬、更容易解释

---

## 10. 这份计划书和现有计划的关系

这份计划书是对下面几份计划的收束补强：

- `docs/33-Claude式结构化数据绑定修复计划书.md`
- `docs/34-Claude式Follow-up句柄续接修复计划书.md`
- `docs/36-Claude式统一续接主链修复计划书.md`

它不推翻之前的方向，只修正一个之前没有被钉死的前提：

> 我们以前默认“自然语言续接提示”可以帮助找到结构化对象；  
> 现在要改成“只有显式对象/显式句柄/强结构化语义，才有资格进入结构化续接链”。

换句话说，之前的方向没有错，但这里有一个关键纪律漏掉了：

> 弱衔接词不是 binding owner。

---

## 11. 下一步执行要求

如果按这份计划开始实施，执行时必须遵守三条工程纪律：

1. 每改一层，就删掉对应旧假设  
   不能新逻辑接上了，旧弱词入口还留着。

2. 每改一层，都加最小回归测试  
   不接受“先都改完再看会不会坏”。

3. 以理顺链路为目标，不以堆补丁为目标  
   如果一个改法需要多处打补丁，优先怀疑方向错了。

本计划书对应的正确实施口径是：

- 先收紧入口
- 再收紧 fallback
- 再统一 owner
- 最后收尾删旧逻辑

