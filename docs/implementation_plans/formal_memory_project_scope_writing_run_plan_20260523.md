# 正式记忆项目作用域与写作续跑修复计划

## 问题

《洪荒时代》写作图已经能完成设计子图，但章节子图在 `volume_plan` 前被正式记忆读取阻塞。根因不是写手能力，而是正式记忆库默认按子图 `task_run_id` 隔离，导致设计子图提交的 baseline 不能被章节子图读取。同时首卷尚未产生的动态记忆、正文记忆被配置为必读，造成空库即失败。

## 目标

- 同一作品项目内的写作正式记忆必须跨父子图、跨子运行可见。
- 不同项目之间必须保持隔离，不能用 durable 全局记忆污染作品。
- baseline 必须阻塞缺失；首轮动态/正文记忆可以为空，后续由提交节点持续扩展。
- 写手节点保持 `memory_search` 自主检索，且输出预算统一不低于 65536。

## 实施步骤

1. 在正式记忆服务里支持动态项目作用域：当仓库声明 `project_scoped` 且未写死 `scope_id` 时，由 runtime 提供的 `project_id` 决定有效仓库 id。
2. 在协调 runtime 的 formal memory sync/select/write 入口注入当前项目 id；项目 id 从 `pending_inputs`、checkpoint diagnostics、root task_run diagnostics 中解析。
3. 在写作图配置中把 baseline、mutable、manuscript、artifact_index、issue_ledger 声明为 project-scoped；读边区分 baseline 必读和动态/正文首轮可空。
4. 修改 `memory_search`：传入 `task_run_id` 时，除了 run-scoped 记录，也搜索该 task run 所属 project-scoped 记录。
5. 把写作 agent 的 profile 下限统一到 65536，并补回归测试。

## 验证

- 跑 formal memory 作用域测试、memory_search 测试、写作图配置测试。
- 重新注册写作图配置。
- 真实启动/续跑任务，推进到 `chapter_draft`，确认写手请求中只允许 `memory_search` 且预算为 65536。
