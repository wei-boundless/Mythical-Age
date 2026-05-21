# 图模块运行协议统一计划

## 背景

任务图编辑器已经取消旧层级容器心智，产品概念统一为“图模块导入、展开与运行”。底层运行协议也必须采用同一套语义，不能继续暴露旧层级字段或旧层级运行命名。

这不是单纯文案问题。协议字段会反向塑造编辑器、预检、执行包和后续图配置方式，所以需要把新输出统一为图模块语义。

## 目标

1. 新运行协议输出使用 `graph_module` / `importing_graph_id` / `linked_graph_id` / `importing_*` / `imported_*` / `graph_module_runtime_plans` / `graph_module_expansions` / `graph_module_execution_plans`。
2. 不再在标准视图、执行包、契约清单、前端类型和图模块运行诊断中输出旧层级容器字段、旧层级字段、旧嵌套字段或图模块语义下的层级字段。
3. 旧字段不再作为正式输入别名扩散。历史快照需要迁移时，应在独立迁移脚本或显式兼容入口完成，不进入当前运行协议主路径。
4. 图模块节点仍然是运行时的时序占位和导入模块壳，不是 agent，不拥有 prompt 或模型配置。
5. 测试覆盖必须验证新协议字段真实生成，旧字段不再作为新标准视图输出。

## 实施步骤

1. 后端模型层：
   - 组合图的导入关系使用 `importing_graph_id` 表达导入方图。
   - 标准视图展开结构使用 `GraphModuleExpansionSpec`。
   - `to_dict()` 输出 `graph_module_expansions`。

2. 运行编译与契约层：
   - runtime spec 对外输出 `graph_modules` 和 `graph_module_runtime_plans`，其中图模块契约统一为 `graph_module_handoff_contracts`。
   - 契约清单将模块交接契约输出为 `graph_module_handoff_contracts`。
   - 图模块运行 handle、导入运行诊断和提交包统一使用 `importing_*` / `imported_*` 字段。
   - `graph_module_runtime*`、`isolated_per_graph_module_run` 这类字段和值不再作为当前运行协议出现；图模块导入运行统一使用 `graph_module_runtime*` 和 `isolated_per_graph_module_run`。

3. API 执行包：
   - 执行包输出 `graph_modules`、`graph_module_execution_plans`、`graph_module_plan_issues`。
   - 错误码、authority、scope、对象 ID 和用户可见消息统一为图模块。

4. 前端与预检：
   - API 类型改为 `GraphModuleExpansionSpec`、`graph_module_expansions`、`graph_module_execution_plans`。
   - 组件内部变量和 inspector 命名同步为 graph module。
   - 面板展示继续用“图模块/导入图模块”，不再出现旧层级容器概念。

5. 配置脚本与测试：
   - 写作任务图生成脚本改为 `graph_module` 节点和模块导入契约命名。
   - 测试夹具改为新字段。
   - 清理旧层级容器计划文档，避免继续作为当前设计依据。

## 验收标准

1. `backend/tests/task_graph_standard_models_test.py`、`backend/tests/task_system_api_regression.py` 通过。
2. 任务图标准视图 payload 包含 `graph_module_expansions`，不包含旧层级容器展开字段。
3. 执行包 payload 包含 `graph_module_execution_plans`，不包含旧层级容器执行计划字段。
4. 前端 TypeScript 通过。
5. 任务系统相关前端测试通过。
6. 聚焦搜索确认当前源代码、写作配置和任务系统存储不再出现旧层级容器、旧层级运行协议锚点。
