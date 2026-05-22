# Task Run Stop Finalization Guard Plan

## 背景

图任务运行中出现已停止分支继续落盘、继续唤醒下游节点的问题。根因是 `stop_task_run` 只把状态和 checkpoint 标记为 aborted，但已经在后台运行的线程完成后仍会进入 `TaskRunFinalizer.upsert_finished_task_run`，并用旧线程结果覆盖最新状态、物化产物、推进 coordination。

## 修复目标

1. 已经被 stop/rewind/scheduler invalidation 标记为终止的 task run，后续旧线程 finalization 必须被硬拦截。
2. 拦截点必须位于 artifact materialization 和 coordination resume 之前。
3. 保留一条可审计事件，说明 finalization 被抑制的原因。
4. 回归测试必须证明不会写 artifact、不会创建 agent result、不会返回 continuation。

## 实施步骤

1. 在 `TaskRunFinalizer.upsert_finished_task_run` 入口读取最新 `TaskRun` 和事件流，判断是否需要抑制旧线程 finalization。
2. 命中抑制条件时写入 `task_run_finalization_suppressed` 事件，保留最新权威状态，不进行产物物化、不写完成结果、不恢复 coordination。
3. 对仍处于 pending/running 的 agent run 做收口，stop 类抑制标记为 killed，invalidation 类抑制标记为 failed。
4. 增加 focused regression test，验证 stopped task run 的 completed finalization 不能产生文件和下游 continuation。
5. 运行相关测试后再恢复真实图任务。

## 非目标

- 不移除 `parent_graph_id`、`GraphUnit` 等运行时锚点。
- 不手动伪造小说产物。
- 不改写当前写作图 prompts 或前端编辑器结构。
