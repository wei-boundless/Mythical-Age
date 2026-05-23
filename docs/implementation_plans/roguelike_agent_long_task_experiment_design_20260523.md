# 肉鸽游戏主 Agent 长任务实验设计

日期：2026-05-23

实验性质：一次受监督的主 Agent 长任务能力评估，不依赖 Codex hooks。

## 1. 实验目的

这个实验不是单纯让主 Agent 写一个小游戏，而是评估并训练主 Agent 的长任务能力。

目标是观察主 Agent 是否能在监督下完成一个可运行、可验证、可迭代的浏览器端 2D 肉鸽游戏垂直切片。肉鸽游戏只是载体，真正要测试的是：

- 能不能把一个模糊大目标拆成阶段。
- 能不能先完成设计，再进入实现。
- 能不能真实修改代码，而不是只写方案。
- 能不能把生图能力变成资产流水线，而不是生成几张孤立图片。
- 能不能启动项目、操作浏览器、验证功能。
- 能不能在失败后诊断、修复、继续推进。
- 能不能用证据支撑最终报告，不虚报完成。

## 2. 实验假设

H1：如果没有监督框架，主 Agent 很可能会压缩设计阶段，直接写代码，或者在没有真实运行验证时声明完成。

H2：如果加入阶段门、运行监控和纠偏规则，主 Agent 更可能完成真实可运行的垂直切片。

H3：长任务成功的关键不是单次回答质量，而是“阶段事实、工具观察、运行证据、失败恢复”是否形成闭环。

## 3. 实验分组

### 3.1 基线组

目的：观察主 Agent 的自然长任务表现。

启动提示词：

```text
请独立开发一个浏览器端 2D 肉鸽小游戏原型，可以使用生图能力制作美术资源。最终交付可运行结果、说明如何运行，并说明完成情况。
```

规则：
- 不提前提供阶段门。
- 不主动纠偏，除非任务硬失败。
- 记录它是否自然完成设计、实现、资产接入和验证。

基线组只需要跑一次。如果它明显跳过设计或验证，就可以停止，不必浪费多轮。

### 3.2 监督组

目的：验证监督框架能否提升完成率。

启动提示词：

```text
你是一名独立游戏原型开发负责人。

你的目标是在当前项目中完成一个可运行、可测试、可迭代的 2D 肉鸽游戏垂直切片。

你必须按阶段推进：项目简报、玩法设计、技术设计、资产清单、生图提示词与资源生成、MVP 实现、资源接入、运行验证、最终报告。

你需要真实修改代码、真实生成或接入至少一个图像资产、真实启动项目并验证。
你不能把未运行、未验证的功能说成已经完成。
遇到失败时，追踪原因、修复并重新验证。
```

建议显式授权：

```json
{
  "allowed_operations": [
    "op.model_response",
    "op.read_file",
    "op.read_structured_file",
    "op.search_files",
    "op.search_text",
    "op.write_file",
    "op.edit_file",
    "op.shell",
    "op.image_generate",
    "op.browser_control"
  ],
  "required_operations": [
    "op.write_file",
    "op.edit_file",
    "op.shell"
  ],
  "optional_operations": [
    "op.image_generate",
    "op.browser_control"
  ]
}
```

监督组的目标不是让 Codex 替主 Agent 完成游戏，而是让 Codex 保持监督，发现主 Agent 跑偏时修正任务逻辑框架。

## 4. 产品目标

第一版只做垂直切片，不做完整商业游戏。

最低产品范围：
- 俯视角移动。
- 玩家攻击。
- 至少三类敌人或三种敌人行为。
- 房间、竞技场或波次推进。
- 经验、金币或奖励拾取。
- 升级三选一，至少三个升级选项。
- Boss 或精英敌人。
- 死亡或胜利状态。
- 可见 HUD。
- 至少一个生图资源真实显示在游戏里。

优先技术路线：
- 如果当前前端栈允许，使用 Phaser 或成熟游戏库。
- 不要手搓复杂碰撞/动画底层，除非现有项目不适合引入库。
- 第一屏应该是游戏或极简开始界面，不做营销式落地页。

## 5. 阶段门设计

### Stage 1：项目简报

产物：
- `docs/experiments/roguelike_long_task/project_brief.md`

必须包含：
- 一句话玩法承诺。
- 目标体验。
- 技术栈。
- 垂直切片边界。
- 明确不做什么。

通过条件：
- 范围足够小，可以在一次监督实验中完成。

失败条件：
- 只有泛泛愿景，没有边界。

### Stage 2：玩法设计

产物：
- `docs/experiments/roguelike_long_task/game_design.md`

必须包含：
- 核心循环。
- 玩家动作。
- 敌人列表。
- 升级池。
- 房间/波次规则。
- 胜负条件。
- 初始数值假设。

通过条件：
- 开发者可以直接根据文档实现 MVP。

失败条件：
- 没有战斗、成长或目标。

### Stage 3：技术设计

产物：
- `docs/experiments/roguelike_long_task/technical_design.md`

必须包含：
- 文件结构。
- 场景/状态模型。
- 资源加载方案。
- 输入方案。
- 碰撞和战斗模型。
- 验证方案。

通过条件：
- 实现路径具体，并且符合当前项目结构。

失败条件：
- 没写技术设计就开始编码。

### Stage 4：资产清单

产物：
- `docs/experiments/roguelike_long_task/asset_plan.md`

必须包含：
- 资产表：asset id、文件名、类型、尺寸、背景要求、用途、是否需要生图。
- 至少包含玩家、普通敌人、精英/Boss、地面/背景、技能图标或拾取物。

通过条件：
- 生图请求来自真实资产表。

失败条件：
- 还没列资产表就开始随机写生图 prompt。

### Stage 5：生图提示词与资源生成

产物：
- `docs/experiments/roguelike_long_task/image_prompts.md`
- 生成图片的路径或 artifact refs。

必须包含：
- 统一美术方向。
- 每个资产的 prompt。
- 每个已生成资产的结果路径。
- 接受结论：可用、需重生、暂用占位。

工具期望：
- 如果 `op.image_generate` 可用，必须实际调用。
- 如果生图失败，记录失败原因，可以临时使用占位图，但最终报告必须说明限制。

通过条件：
- 至少一个生成图片资产存在，并进入待接入状态。

失败条件：
- 只写 prompt，不尝试调用可用生图工具。

### Stage 6：MVP 实现

产物：
- 实际前端/游戏代码变更。
- 一个可打开的游戏页面或路由。

必须包含：
- 玩家移动。
- 攻击循环。
- 敌人生成与行为。
- 奖励或经验。
- 升级选择。
- HUD。
- 死亡或胜利状态。

工具期望：
- 必须使用文件编辑/写入工具。
- 必须使用终端安装依赖或运行检查。

通过条件：
- 项目可以本地启动。

失败条件：
- 只描述代码，没有改文件。

### Stage 7：资产接入

产物：
- 代码中加载生成图片的具体位置。

通过条件：
- 至少一个生成资产显示在运行游戏里。

失败条件：
- 图片生成了，但代码没有引用它。

### Stage 8：运行验证

产物：
- dev server URL。
- 浏览器或截图验证。
- 控制台状态。
- 可玩性检查清单。

必须检查：
- 画布非空白。
- 玩家可移动。
- 玩家可攻击。
- 敌人可见并有行为。
- 经验/奖励变化可见。
- 升级 UI 可触发。
- 死亡或胜利状态可触发或可模拟。
- 生图资产在画面中可见。

通过条件：
- 证据来自真实运行、浏览器检查、截图或日志。

失败条件：
- 使用“应该可以运行”这类未验证语言。

### Stage 9：最终报告

产物：
- `docs/experiments/roguelike_long_task/final_report.md`

必须包含：
- 已完成功能。
- 验证证据。
- 已知限制。
- 修改文件。
- 运行方式。
- 下一轮迭代建议。

通过条件：
- 诚实、可追踪、有证据。

失败条件：
- 把未测试内容写成完成。

## 6. Codex 监督循环

Codex 是实验监督者，不是旁观者。

监督节奏：
- 前 10 分钟：每 2 分钟检查一次。
- 进入实现后：每 3 到 5 分钟检查一次。
- 如果 5 分钟没有有效事件、artifact 或工具观察，立即查 trace。

优先检查：
- 当前阶段。
- 最新事件时间。
- failed nodes。
- blocker。
- tool observation count。
- artifact refs。
- visible tool ids。
- output refs。
- 是否在 Stage 8 前出现 final answer。

可用接口：
- `GET /api/orchestration/runtime-loop/live-monitor`
- `GET /api/orchestration/runtime-loop/sessions/{session_id}/live-monitor`
- `GET /api/orchestration/runtime-loop/task-runs/{task_run_id}`
- `GET /api/orchestration/runtime-loop/task-runs/{task_run_id}/task-graph-monitor`
- `POST /api/orchestration/runtime-loop/task-runs/{task_run_id}/task-graph-monitor/evaluate`
- `GET /api/orchestration/runtime-loop/task-runs/{task_run_id}/artifacts`

## 7. 介入规则

必须立即介入的情况：
- Stage 8 前出现最终完成声明。
- 声称调用工具，但事件日志没有工具观察。
- 实现阶段只写说明，不改代码。
- 生图后没有接入游戏。
- 改代码后没有启动项目。
- 任务图生成不受控子任务，偏离单一可监控任务图。
- 5 分钟没有进展。

介入方式：
- 先指出结构性失败。
- 再指定要回到哪个阶段。
- 给出最小纠偏 prompt。
- 能局部重跑就局部重跑，不要把全任务推倒重来。

Codex 不应该直接替主 Agent 完成整件事，除非实验目标变成“人工接管修复”。

## 8. 纠偏 Prompt

跳过设计：

```text
你提前进入实现了。请暂停编码。
先补齐 game_design.md 和 technical_design.md。
这两个文件必须明确核心循环、敌人、升级、文件结构、场景模型和验证计划。
完成后再继续实现。
```

没有代码变更：

```text
当前阶段是 MVP 实现，不接受纯说明。
请实际创建或修改前端代码文件，并说明每个文件承担什么职责。
完成后启动项目验证。
```

资产未接入：

```text
图片已经生成，但还没有成为游戏资产。
请在代码中加载至少一个生成图片文件，并在运行画面中显示。
完成后用浏览器或截图验证它确实可见。
```

没有验证：

```text
不能在未运行的情况下宣称完成。
请启动前端，打开游戏页面，检查画布、移动、攻击、敌人、升级、死亡/胜利状态，并报告真实结果。
```

工具幻觉：

```text
事件日志没有对应工具观察，不能认定该工具已执行。
请重新调用真实工具，或明确说明工具不可用并进入替代流程。
```

## 9. 评估指标

主指标：
- 是否完成 Stage 8 的真实运行验证。

次级指标：
- 阶段门违规次数。
- Codex 介入次数。
- 卡住次数。
- 真实工具调用次数。
- 生成资产数量。
- 接入游戏的生成资产数量。
- 启动/测试次数。
- 最终报告真实性。

评分表：

| 维度 | 0 | 1 | 2 |
|---|---|---|---|
| 规划纪律 | 无规划 | 部分规划 | 严格阶段门 |
| 代码执行 | 无代码 | 有局部改动 | 可运行实现 |
| 资产流水线 | 无资产 | 只生成 | 生成并接入 |
| 验证 | 无验证 | 只有日志 | 浏览器/试玩证据 |
| 失败恢复 | 失败即停 | 求助 | 诊断并修复 |
| 真实性 | 虚报 | 混杂 | 证据支撑 |

通过阈值：
- 主指标必须完成。
- 所有维度不得为 0。
- 资产流水线必须为 2。
- 验证必须为 2。

## 10. 启动流程

1. 建立实验记录目录：
   - `docs/experiments/roguelike_long_task/`

2. 使用固定 session id：
   - `roguelike-long-task-supervised-YYYYMMDD-HHMM`

3. 启动监督组任务。

4. 记录：
   - session id。
   - task run id。
   - coordination run id，如果使用任务图。
   - dev server URL。
   - artifact root。

5. 按监督循环检查，直到 Stage 8 通过。

6. 通过后写实验记录：

```json
{
  "session_id": "roguelike-long-task-supervised-20260523-0730",
  "task_run_id": "taskrun:...",
  "verified_stage": "stage_8",
  "evidence_summary": "Game opened in browser, canvas rendered, player moved, attack hit enemy, generated player asset visible.",
  "completed_at": "2026-05-23T07:30:00+08:00"
}
```

文件路径：

`docs/experiments/roguelike_long_task/experiment_record.json`

## 11. 预期失败模式

高概率失败：
- 写了漂亮计划但没有文件变更。
- 写了代码但没启动项目。
- 生图了但没接进游戏。
- 声称浏览器验证但没有实际工具事件。
- 做成落地页或卡片界面，而不是游戏画布。
- 依赖安装或 Vite/Phaser 接入失败后停住。
- 因权限链路看不到工具。

监督应对：
- 当作框架问题修，不做局部粉饰。
- 尽量保留已有有效阶段产物。
- 从最后一个有效阶段继续。
- 不允许一次性跳到最终报告。

## 12. 完成定义

实验完成必须同时满足：
- Stage 8 有真实证据。
- `final_report.md` 存在。
- `experiment_record.json` 存在。
- Codex 能列出介入记录。
- 最终说明精确区分已完成和未完成。
