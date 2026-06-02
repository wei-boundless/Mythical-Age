# Agent Progress UI Intelligence Optimization Plan - 2026-06-02

## 1. Problem Statement

当前主聊天里的运行进展 UI 没有传达“高水平 agent 正在可靠推进任务”的感觉。截图暴露的问题不是单纯样式问题，而是运行事件、语义投影和前端呈现之间的结构错位：

- UI 以 runtime event 为单位展示，用户看到的是日志，而不是任务推进。
- `Agent 判断`、`调用工具`、`观察结果` 三类卡片彼此割裂，缺少“判断 -> 行动 -> 证据 -> 下一步”的连续闭环。
- 工具结果没有语义翻译，例如 `path_exists ... false` 被直接显示，用户无法判断这是正常发现、失败还是阻塞。
- 文案重复且低信息密度，例如“已同步最新进展”“工具调用已完成，正在根据结果继续”大量出现，削弱了推进感。
- 当前步骤、目标、风险、证据、下一步没有固定位置，用户需要在多张卡片中自己拼上下文。
- 前端视觉层级平均，旧事件和当前关键判断权重接近，导致界面生硬、迟缓。

目标不是“更花哨”，而是让 UI 表达出 agent 的决策能力、执行节奏、证据意识和可靠收口。

## 2. Current Runtime/UI Flow

真实链路如下：

```text
backend/harness/loop/task_executor.py
  -> 记录 step_summary_recorded、task_tool_observation_recorded 等 runtime events

backend/harness/runtime/session_timeline.py
  -> _progress_entries(events)
  -> 将单个 event 投影为 progress_entries

frontend/src/lib/runtimeVisibilityProjection.ts
  -> 将流式事件投影为 RuntimeProgressEntry

frontend/src/components/chat/RuntimeRunSummary.tsx
  -> compactStepViews()
  -> 按 kind 分成 tool / observation / model / stage
  -> 渲染成当前截图里的卡片式进展

frontend/src/app/globals.css
  -> runtime-run-summary 样式
```

当前最大问题在 `session_timeline.py` 和 `RuntimeRunSummary.tsx`：它们仍把“事件”当作主要展示对象。成熟 agent 的进展 UI 不应该展示事件本身，而应该展示事件合成后的工作单元。

## 3. Design Direction

产品类型：agent runtime progress console。

用户角色：正在等待 agent 完成任务的人，需要快速判断“它是否在推进、推进到哪、有没有风险、证据是什么”。

主对象：一个正在运行或已完成的 task run。

页面层级：聊天消息内的嵌入式运行摘要，不是完整监控台。

设计方向：

- 稠密、克制、工作台风格，不做营销式 hero，不做大面积装饰。
- 当前状态必须强于历史日志。
- 技术细节默认收起，但可追踪。
- 文案像高级助手的工作汇报，不像系统日志。
- 视觉动效服务于“正在快速处理”，不能制造噪声。

`ui-ux-pro-max` 检索建议给了叙事式进展、进度指示和层次感方向；但其 glassmorphism、奢侈字体建议不适合本项目的工具型工作台，应拒绝。最终采用“高密度操作台 + 清晰阶段叙事 + 微动效”的方向。

## 4. Target Information Architecture

主聊天里的每个运行摘要分三层。

### 4.1 Mission Strip

固定在摘要顶部，始终显示：

- 当前任务目标：例如“创建 calculator.html 并验证路径可用”。
- 当前阶段：规划 / 检查 / 写入 / 验证 / 收口 / 等待确认 / 受阻。
- 当前动作：一句自然语言，不超过 42 个中文字符。
- 运行状态：进行中 / 等待 / 已完成 / 受阻。
- 简短进度：例如 `2/5 验证路径`，不能伪造百分比。

Mission Strip 是用户第一眼判断“它在干什么”的位置。

### 4.2 Work Unit Stream

把多个 runtime events 合成一个工作单元，例如：

```text
确认 artifact 路径
状态：已完成
判断：目标文件尚未存在，但工作区路径有效。
行动：检查 storage/task_environments/general/workspace/.../calculator.html
证据：path_exists 返回“未存在”
下一步：创建目录并写入 calculator.html
```

一个 work unit 可以包含：

- model judgment
- tool call
- observation
- derived evidence
- next action

用户不应该看到三张分裂卡片，而应该看到一个有闭环的工作单元。

### 4.3 Technical Trace Drawer

技术细节默认收起：

- 原始 tool name
- raw command/path/query
- raw result preview
- event id / task run id
- refs

它服务调试，不服务普通阅读。主进展 UI 不再暴露 `false`、内部 id、英文状态、被截断路径等裸值。

## 5. Backend Presentation Model

新增一个明确的展示模型，建议命名：

```text
backend/harness/runtime/progress_presenter.py
```

不要让前端自己从 event 列表猜 UI 语义。后端 presenter 负责把 runtime trace 合成为可展示的工作单元。

### 5.1 Proposed Output Shape

在 `SessionRuntimeAttachment` 中新增主展示字段：

```json
{
  "progress_presentation": {
    "mission": {
      "goal": "创建 calculator.html 并验证路径可用",
      "phase": "检查路径",
      "state": "running",
      "current_action": "确认目标文件是否已存在",
      "next_action": "创建目录并写入 calculator.html",
      "progress_label": "路径检查"
    },
    "work_units": [
      {
        "unit_id": "workunit:path-check",
        "kind": "inspect_path",
        "title": "确认 artifact 路径",
        "state": "completed",
        "judgment": "目标文件尚未存在，路径检查本身成功。",
        "action": "检查 calculator.html 是否已存在。",
        "evidence": [
          {
            "label": "path_exists",
            "summary": "文件不存在，这是预期发现。",
            "status": "negative_evidence",
            "technical_value": "false"
          }
        ],
        "next_action": "创建目录并写入 HTML 文件。",
        "risk": "",
        "technical_trace_refs": ["rtevt:...", "toolobs:..."]
      }
    ],
    "technical_trace": [
      {
        "event_id": "rtevt:...",
        "event_type": "task_tool_observation_recorded",
        "tool_name": "path_exists",
        "raw_preview": "false"
      }
    ]
  }
}
```

### 5.2 Authority Rules

- `task_executor.py` 继续记录真实事件，不负责 UI 合成。
- `session_timeline.py` 只组装 attachment，不直接做复杂叙事。
- `progress_presenter.py` 负责展示语义合成。
- `RuntimeRunSummary.tsx` 负责渲染，不再反推业务含义。
- `progress_entries` 只作为 technical trace 的原始材料，不再是主 UI 权威，也不作为旧样式降级链路。

这能避免前端和后端各自猜“这个 event 是什么意思”。

## 6. Event-To-WorkUnit Aggregation Rules

### 6.1 Grouping

按以下优先级归并事件：

1. `action_request_ref`
2. `observation_ref`
3. `runtime_invocation_packet_ref`
4. 邻近时间窗口 + step index

一个 model action 后跟随的 tool call 和 observation，应合成同一个 work unit。

### 6.2 Suppression

以下内容不得进入主 UI：

- `已同步最新进展。`
- `工具调用已完成，正在根据结果继续。`
- `task_execution_packet_compiled`
- heartbeat / waiting heartbeat
- runtime packet / taskrun id / internal module path
- raw JSON
- bare boolean: `true` / `false`
- English internal status: `working` / `ready_to_finish`

这些只能进入 technical trace。

### 6.3 Semantic Translation

工具结果需要按工具类型翻译：

- `path_exists=false` -> “目标文件不存在，下一步需要创建。”
- `path_exists=true` -> “目标路径已存在，可进入读取或覆盖判断。”
- `search_text` 命中 -> “已找到关键证据：...”
- `search_text` 未命中 -> “未找到关键文本，需要补充实现或换关键词验证。”
- `write_file` 成功 -> “文件已写入：...”
- `terminal` 成功 -> “命令执行完成，输出摘要：...”
- `terminal` 失败 -> “命令失败，需要修正命令或路径。”

关键点：负向证据不等于失败。`false` 要表达成判断结果，而不是裸结果。

## 7. Frontend Component Target

重写 `RuntimeRunSummary.tsx` 的呈现结构，而不是继续堆卡片。

### 7.1 Component Split

建议拆成：

```text
RuntimeRunSummary.tsx
  RuntimeMissionStrip
  RuntimeCurrentFocus
  RuntimeWorkUnitList
  RuntimeEvidencePill
  RuntimeTechnicalTraceDrawer
```

### 7.2 Visual Behavior

- 当前 work unit 使用更强层级：左侧活跃线、微脉冲点、清晰标题。
- 已完成 work unit 压缩成一行，显示关键证据。
- 当前判断和下一步在同一张 work unit 内显示。
- 工具调用用小型证据 chip，不再作为独立主卡片抢权重。
- 主 UI 不显示 `Tool Call / Observation / Agent` 这种英文 lane label。
- 技术 trace 使用 `details` 或折叠面板，默认关闭。
- 运行中用 150-300ms 微动效，遵守 `prefers-reduced-motion`。

### 7.3 Copywriting Rules

文案必须符合：

- 每条主进展都回答“这一步为什么推进任务”。
- 每条观察结果都说明“结果意味着什么”。
- 下一步必须是动作，不是状态。
- 不出现“正在根据结果继续”这类无信息句。
- 不出现“处理 path_exists”这种开发式表达。
- 不出现裸英文状态。

示例替换：

```text
坏：调用工具 正在使用 path_exists 处理 storage/...
好：确认目标文件是否已存在

坏：观察结果 false
好：目标文件尚未创建，路径检查成功；下一步写入 calculator.html。

坏：状态 working
好：正在检查路径
```

## 8. CSS Direction

改动文件：

```text
frontend/src/app/globals.css
```

原则：

- 不再给每个 event 一个完整 bordered card。
- 使用紧凑的 timeline/work unit 布局。
- 当前单元高亮，历史单元降噪。
- 颜色不做单一蓝色主题：主色保持中性深墨，运行态用蓝，证据成功用绿，风险用琥珀，失败用红。
- 卡片半径不超过 8px。
- 不使用 emoji 图标，继续用 lucide。
- 路径和命令用 monospace chip，限制行宽并支持复制/展开。
- 移动端只显示 Mission Strip + 当前 work unit，历史折叠。

## 9. Implementation Plan

### Phase 1 - Backend Presenter

文件：

- `backend/harness/runtime/progress_presenter.py`
- `backend/harness/runtime/session_timeline.py`
- `backend/tests/session_runtime_timeline_regression.py` 或新增 `backend/tests/runtime_progress_presenter_regression.py`

任务：

- 定义 `build_progress_presentation(events, task_run, monitor)`。
- 将 step summary、tool observation、terminal event 合成为 work units。
- 翻译常见工具结果。
- 抑制空泛 runtime 句。
- 在 attachment 中输出 `progress_presentation`。

验收：

- `path_exists false` 不在主 presentation 裸露，转成“文件不存在，下一步创建”。
- model judgment + tool observation 合成同一个 work unit。
- `已同步最新进展。` 不进入 work units。
- technical trace 仍保留 raw preview。

### Phase 2 - Frontend Data Types

文件：

- `frontend/src/lib/api.ts`
- `frontend/src/lib/store/types.ts`

任务：

- 增加 `RuntimeProgressPresentation` 类型。
- `SessionRuntimeAttachment` 支持 `progress_presentation`。
- 保留 `progress_entries` 作为 technical trace 输入，不再作为主 UI 来源。

验收：

- 类型测试通过。
- 没有将 raw progress entry 当主 UI 渲染的路径。

### Phase 3 - RuntimeRunSummary Rewrite

文件：

- `frontend/src/components/chat/RuntimeRunSummary.tsx`
- `frontend/src/components/chat/RuntimeRunSummary.test.ts`

任务：

- 以 `progress_presentation` 为主输入。
- 渲染 Mission Strip、Current Focus、Work Unit List、Technical Trace。
- 删除 `Tool Call / Observation / Agent` 英文 lane。
- 删除以 event kind 为主的卡片流。
- 没有 `progress_presentation` 时只显示最小状态摘要和 technical trace，不恢复旧日志式主 UI。

验收：

- 截图场景中主 UI 显示“确认 artifact 路径”，不是“调用工具/path_exists/false”三段日志。
- 当前步骤明显高亮。
- 技术 trace 默认收起。
- 所有按钮有清晰 hover/focus。

### Phase 4 - Styling And Motion

文件：

- `frontend/src/app/globals.css`

任务：

- 新增 `.runtime-mission-strip`、`.runtime-work-unit`、`.runtime-evidence-pill`、`.runtime-technical-trace`。
- 删除或停用旧 `.runtime-run-summary__item--tool/observation/model` 的主视觉逻辑。
- 增加运行中微动效和 reduced motion。
- 移动端压缩布局。

验收：

- 375px、768px、1440px 无文字溢出。
- 当前动作和下一步不会互相遮挡。
- 长路径不撑破卡片。

### Phase 5 - Live Verification

必须真实运行：

- 启动固定后端 `127.0.0.1:8003`。
- 启动固定前端 `127.0.0.1:3000`。
- 用真实任务触发：
  - path_exists false 场景
  - write_file 场景
  - search_text 命中/未命中场景
  - tool error 场景
  - completed closeout 场景
- 用 Playwright/Edge 截图检查。

验收标准：

- 用户第一眼能知道当前任务目标、当前阶段、下一步。
- 主 UI 不再出现裸 `false`。
- 主 UI 不再出现 `已同步最新进展。`。
- 主 UI 不再像 runtime event log。
- 技术 trace 可展开，且能找到原始证据。

## 10. Test Plan

Backend:

```powershell
python -m pytest backend/tests/runtime_progress_presenter_regression.py backend/tests/harness_runtime_facade_regression.py::test_task_executor_wait_heartbeat_does_not_repeat_visible_step_summary -q
```

Frontend:

```powershell
cd frontend
npm test -- --run src/components/chat/RuntimeRunSummary.test.ts src/lib/runtimeVisibilityProjection.test.ts
```

Visual:

```powershell
cd frontend
npm run dev
```

Then inspect `http://127.0.0.1:3000` against the fixed backend `http://127.0.0.1:8003/api`.

## 11. Non-Goals

- 不改 graph UI。
- 不改 image generation bypass。
- 不改模型调用策略。
- 不把 UI 文案优化写进 agent prompt 里硬逼模型输出更多废话。
- 不通过增加更多事件卡片解决问题。

## 12. Main Risks

1. **过度合成导致丢失调试证据**  
   处理：主 UI 合成，technical trace 保留原始事件。

2. **前端本地猜语义再次膨胀**  
   处理：后端 presenter 作为唯一展示语义权威。

3. **旧测试保护日志式 UI**  
   处理：删除或重写保护 `Agent 判断 / 调用工具 / 观察结果` 分裂展示的旧测试，改为保护 work unit 闭环。

4. **模型 public_action_state 本身质量不稳定**  
   处理：presenter 不能无脑相信模型文案，需要用工具证据校正展示语义。

## 13. Final Acceptance Criteria

这次优化完成后，同类截图应呈现为：

```text
正在检查路径
目标：创建 calculator.html 并验证可用

当前判断
目标文件尚未存在，工作区路径有效。

刚完成
确认 artifact 路径
证据：path_exists 返回“未存在”
下一步：创建目录并写入 calculator.html

技术日志（默认收起）
path_exists storage/task_environments/general/workspace/.../calculator.html -> false
```

用户感受到的应该是：

- agent 知道自己在做什么；
- 每一步都有判断依据；
- 工具结果被理解了；
- 任务在快速推进；
- 出问题时能清楚说明风险和恢复路径。
