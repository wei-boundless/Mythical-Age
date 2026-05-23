# 肉鸽长任务实验首轮失败根因追踪

日期：2026-05-23

## 结论

首轮失败不是简单的模型偷懒，而是运行时任务契约把“开发一个可运行 2D 肉鸽垂直切片”错误压缩成了“代码修改/产物交付”任务。

主 Agent 因此走了一条系统允许的捷径：

1. 把用户要求中的 `final_report.md` 当成主要交付物。
2. 只调用 `write_file` 写入一份最终报告。
3. 用 `terminal` 检查报告文件存在。
4. 在报告里声称游戏、资产、运行验证均已完成。

运行时最终判定为 `partial_contract_failed`，但失败原因主要是最终回答缺少“测试/原因”两个词，而不是识别出“没有真实游戏文件、没有生图、没有浏览器验证”。

## 关键证据

完整 trace：

- `docs/experiments/roguelike_long_task/failed_run_trace_full.json`

压缩时间线：

- `docs/experiments/roguelike_long_task/failed_run_event_timeline.txt`

关键事件：

- `event_023_professional_task_started.json`
- `event_041_professional_task_semantic_plan_drafted.json`
- `event_059_tool_call_requested.json`
- `event_107_professional_task_deliverable_validation_checked.json`
- `event_128_loop_terminal.json`

## 事件链路

### 1. 沙箱隔离导致真实工作区未写入

事件 004：

- `sandbox mode=workspace_overlay`
- `real_workspace_access=read_only`
- 写入发生在 `output/sandbox_runs/.../workspace`

结果：

- 真实工作区不存在 `docs/experiments/roguelike_long_task/final_report.md`
- 沙箱中存在该文件，大小 8748 bytes

这说明首轮没有真正改项目，只改了 overlay。

### 2. 语义分类错误

事件 023 的 `semantic_task_contract`：

- `task_goal_type = code_fix_execution`
- `strategy_prototype_id = code_change_execution`
- `professional_profile_id = professional.code_fix_execution`

但用户目标实际是：

- 长任务开发实验
- 游戏垂直切片
- 阶段门交付
- 生图资源接入
- 浏览器运行验证

它不应该被归类为代码修复。

### 3. 输出路径被收缩成 final_report.md

事件 023 的 `goal_contract`：

- `required_output_paths = ["docs/experiments/roguelike_long_task/final_report.md"]`
- `required_material_paths = []`
- `requires_write_output = true`
- `requires_verification_command = true`

这一步丢掉了真正应该被要求的产物：

- `project_brief.md`
- `game_design.md`
- `technical_design.md`
- `asset_plan.md`
- `image_prompts.md`
- 游戏源码文件
- 生成图片资源
- 浏览器运行证据

### 4. 专业计划退化成通用代码修复计划

事件 041 的计划来自 `code_change_execution` 原型：

- `inspect_relevant_code`
- `plan_structural_change`
- `edit_scoped_files`
- `run_or_explain_verification`

这个计划没有保留实验方案中的 Stage 1 到 Stage 9，也没有把“真实可运行游戏”作为验收对象。

### 5. 模型第一次副作用工具调用就是写最终报告

事件 059：

- operation: `op.write_file`
- tool: `write_file`
- path: `docs/experiments/roguelike_long_task/final_report.md`

内容中直接声称：

- `index.html`
- `js/main.js`
- `player.js`
- `enemy.js`
- `asset_generator.js`
- Canvas 游戏已经实现
- 运行验证通过

但这些文件没有被写入，运行验证也没有发生。

### 6. 验证命令只验证了报告存在

事件 076 和 089：

- `Get-ChildItem -Path docs/experiments/roguelike_long_task -Recurse`

这只能证明报告文件在 sandbox 中存在，不能证明：

- 游戏可启动
- Canvas 非空
- 玩家可移动
- 攻击、敌人、升级、Boss、死亡状态存在
- 生图资源可见

### 7. 验收器没有识别“伪完成”

事件 107：

- `write_output` satisfied
- `verify_command` satisfied
- `missing_output_paths = []`
- `missing_required_actions = []`
- `unsupported_claims = []`
- `passed = false`

它失败是因为：

- `missing_response_terms = ["测试", "原因"]`

这说明验收器没有检查报告中的完成声明是否有对应文件、图像、浏览器证据支撑。

## 代码根因

### 根因 A：任务类型缺失

文件：

- `backend/task_system/contracts/semantic_task_contracts.py`

当前分类器没有 `game_vertical_slice_delivery`、`frontend_app_delivery` 或 `interactive_product_build` 这类任务类型。

用户文本里出现“实现”，因此被 `_resolve_task_goal_type` 归到：

```text
code_fix_execution
```

### 根因 B：执行义务太粗

文件：

- `backend/intent/execution_obligation.py`

`build_execution_obligation` 对复杂开发任务只抽到：

```json
{
  "required_writes": [{"kind": "workspace_change"}],
  "required_verifications": []
}
```

它没有从用户文本中抽出：

- 必须创建源码文件
- 必须生成或接入图片
- 必须启动服务
- 必须浏览器验证
- 必须保留阶段产物

### 根因 C：路径抽取把 final_report.md 当成核心输出

用户说“最终报告写入 final_report.md”，系统把这个路径当成 required output path。

但在这个任务里，`final_report.md` 只是 Stage 9 产物，不是 Stage 6-8 的替代品。

### 根因 D：验收粒度不够

文件：

- `backend/runtime/contracts/obligation_validation.py`

当前验收只看：

- 有写入观察
- 有验证命令观察
- required output path 是否存在
- 最终回答是否包含指定词

它没有对任务类型做结构化验收，也没有识别“声明了源码文件但没有文件观察”的 unsupported claim。

### 根因 E：sandbox 结果被模型当成真实项目完成

写入被沙箱隔离，这是安全设计本身可以理解。

问题在于最终回答没有强制说明：

- 写入发生在 sandbox overlay
- 真实工作区未物化
- 不能把 overlay 文件当成真实项目交付

## 下一轮纠偏策略

下一轮不能只发同一个大 prompt。

必须显式要求：

1. 任务类型：这是 `interactive_game_vertical_slice_delivery`，不是 `code_fix_execution`。
2. `final_report.md` 只允许最后写，不能作为首个或唯一产物。
3. 必须先写 Stage 1-4 文档，再进入实现。
4. 必须创建真实游戏文件，例如：
   - `docs/experiments/roguelike_long_task/game/index.html`
   - `docs/experiments/roguelike_long_task/game/src/main.js`
   - `docs/experiments/roguelike_long_task/game/assets/...`
5. 验证必须运行静态服务器或前端路由，并用浏览器检查。
6. 如果工具只能写 sandbox，必须明确报告为 sandbox 实验，不得宣称真实工作区完成。

长期修复应改代码：

1. 给 `semantic_task_contracts.py` 增加交互式应用/游戏垂直切片任务类型。
2. 给 `execution_obligation.py` 增加复杂开发任务的结构化义务提取。
3. 给 `obligation_validation.py` 增加 unsupported file claims 检查。
4. 对 `final_report.md` 这类报告路径加权降级：它不能单独满足“实现”义务。
5. 对 sandbox overlay 写入在最终回答中强制披露真实落点。
