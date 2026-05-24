# Disable Vibe Coding Runtime Route Plan

日期：2026-05-24

## 目标

把 `vibe_coding` 从当前 runtime 路由和执行 recipe 中退出去。它可以继续作为后端静态资产保留，包括 prompt/profile/worker blueprint/规划文档，但不能被显式按钮、语义任务 profile、recipe builder 或 runtime loop 触发为独立运行模式。

## 原则

- 不删除静态资产：`storage/prompt_library`、`storage/orchestration`、worker blueprint 中的 vibe coding 配置先保留。
- 不保留半触发路径：显式 `vibe` / `vibe_code` / `coding` 等别名不能再产出 `interaction_mode=vibe_coding`。
- 代码类任务退回 `professional_mode`：`code_fix_execution`、`frontend_app_delivery`、`regression_test_design` 等任务仍应能走 professional runtime，而不是断路。
- runtime 判断中不再把 `runtime.recipe.vibe_coding` 当 professional task run recipe。

## 改动计划

1. `backend/orchestration/interaction_mode_policy.py`
   - 从 runtime interaction modes 中移除 `vibe_coding`。
   - 显式 vibe/coding 别名改为归一到 `professional_mode`。
   - `TaskGoalProfile.material_policy.runtime_mode == "vibe_coding"` 不再返回 vibe mode，而是转为 professional。
   - 删除 `_policy_for_mode()` 里的 `VIBE_CODING_MODE` 分支。

2. `backend/task_system/planning/execution_recipe_builder.py`
   - `runtime.recipe.vibe_coding` 不再进入统一 interaction-mode recipe 分支。
   - `professional_modes` 只保留 `professional_mode`。
   - `_interaction_mode_title()` 和 `_needs_agent_todo()` 不再识别 vibe mode。

3. `backend/runtime/unit_runtime/loop.py`
   - `_is_professional_task_run_recipe()` 不再接受 `vibe_coding` / `runtime.recipe.vibe_coding`。

4. 关联 runtime 边界辅助
   - `backend/runtime/unit_runtime/sandbox_policy.py`
   - `backend/runtime/professional_runtime/runtime_policy.py`
   - `backend/runtime/model_gateway/model_response.py`
   - `backend/runtime/memory/trace_reader.py`
   - 测试支撑 stub 中的 runtime mode 集合。

5. 测试更新
   - 原先断言 vibe routing 的测试改为断言回退 professional。
   - prompt/static asset 相关测试保持不动，确保静态资产仍可管理。

## 验证

- 运行 interaction mode、understanding route、professional run、query runtime 相关聚焦测试。
- 全局搜索确认 runtime 代码不再把 `vibe_coding` 当可执行 interaction mode 或 recipe。

