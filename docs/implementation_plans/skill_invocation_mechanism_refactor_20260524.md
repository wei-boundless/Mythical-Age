# Skill 调用机制重构计划

## 背景判断

当前实现不属于成熟 Agent 的 skill 调用机制，而是“后端预选 skill + 运行时注入”的混合结构。

主要结构问题：

1. 后端在主模型执行前通过 `SkillPolicyResolver` 预选 `active_skill`，替模型做了 skill 判断。
2. 任务系统还保留 `default_skill_refs -> SkillRuntimeView` 的硬编码影子映射，模型看到的不是真实 skill registry。
3. `active_skill` 会直接影响 `required_operations` 装配，导致 skill 既是说明，又是前置权限开关，迫使后端代选。
4. prompt 层把 skill 当成“已选中的附加职责”，而不是“模型可见的候选能力目录”。

这会直接破坏主模型的理解职责，使 skill 机制退化成后端路由器。

## 目标结构

重构后必须满足：

1. 后端不再预选 `active_skill`。
2. 后端只提供“模型可见的候选 skill 目录”。
3. 候选 skill 来自真实 `SkillRegistry`，不再使用硬编码影子 skill 视图。
4. 每个 skill 必须对模型清楚声明：
   - 它是什么职责
   - 什么时候使用
   - 不该在什么场景使用
   - 依赖哪些 operation
5. 运行时工具边界仍由系统控制，但不再依赖后端先猜一个 skill。
6. skill 相关 prompt 应该帮助模型自主判断，而不是告诉模型“你已经被分配了这个 skill”。

## 实施原则

1. 删除旧壳，不保留“预选 active_skill”兼容逻辑。
2. 不为某个任务类型做 skill 特化修补。
3. 不保留 `default_skill_refs -> 影子 SkillRuntimeView` 这种中间层。
4. skill 的来源以 `SkillRegistry` 为准。
5. 任务装配只保留“候选 skill 列表”和“这些 skill 的 operation 依赖并集”。

## 实施步骤

1. 重构 task/runtime skill 视图来源
   - 删除 `runtime_contracts.py` 中硬编码 `_skill_view` 映射。
   - 新增从 `SkillRegistry` 构建 `SkillRuntimeView` 的通用函数。

2. 重构任务装配
   - `build_task_execution_assembly_bundle` 不再接收或产出 `active_skill`。
   - 任务装配阶段只生成 `skill_runtime_views` 与 `selected_skill_ids`。
   - `required_operations` 由候选 skill 的 `requires_operations` 合并，但不再依赖某个被后端选中的单 skill。

3. 拆除 runtime_chain 里的 skill 预选
   - 删除 `_resolve_skill_frame` 和 `_skill_frame_payload` 在主链路中的调用。
   - 主运行时只传递候选 skill 目录，不再传递 `active_skill`。

4. 重构 prompt 装配
   - `assemble_runtime_prompt_contract` 与 `build_prompt_selection_context` 去除 `active_skill` 依赖。
   - prompt 中保留 skill 目录可见性，但语义改为“可参考能力 / use_when”而不是“当前已启用 skill”。

5. 修正 orchestration / soul 投影链
   - 运行时可见 `visible_skill_ids` 仍保留。
   - 删除 `active_skill_name` 诊断依赖。

6. 修正至少一个真实 skill 文案
   - 把 `image-prompt-design` 调整成模型可直接理解的职责说明，强调 use_when / 非适用场景 / 必需工具。

7. 回归验证
   - 修正受影响单测。
   - 增加至少一个回归测试，确认 runtime 不再产出 `active_skill`，且候选 skill 目录仍进入运行时上下文。

## 完成标准

满足以下条件才算完成：

1. 主链路不再出现后端预选 `active_skill`。
2. skill 视图不再来自硬编码映射。
3. 模型上下文中仍能看到 skill 目录与可见 skill id。
4. operation requirement 仍能从候选 skill 正确汇总。
5. 相关回归测试通过。
