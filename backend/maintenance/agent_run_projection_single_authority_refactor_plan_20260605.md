# Agent 运行反馈单一页面投影权威重构计划

日期：2026-06-05

## 背景

主会话页面当前存在多个展示判断来源：`ChatMessage` 会从公开时间线反推正文，`PublicRunActivity` 会自行压缩当前活动，`agentRunPresentation` 又保留动作到开局反馈的兜底逻辑，`runtime` 对 monitor observation 的公开映射也不完整。结果是用户会看到开局反馈重复、动作和结果时序混乱、工具观察消失、停止后仍像在运行，以及“观察结果 / 执行中 / 需要调整”等开发式标签外露。

本次重构以成熟 coding agent 的外显体验为标准：用户应自然感知 agent 已理解任务、正在执行哪一步、工具返回了什么事实、todo 进度如何变化、最终如何收口；动作可以弱化，但不能消失，观察结果必须像正文一样出现。

## 目标体验

页面顺序只允许由一个投影层决定：

1. 真实开局判断：来自 `opening_judgment` 或真实 `assistant_text`，只渲染一次。
2. 当前动作：低强调短句，表达 agent 正在做什么，不展示工具名、英文 tool id、原始命令。
3. 结果反馈：工具或 runtime observation 返回后，以正文式事实反馈显示，并压过同一动作的运行态。
4. Todo：紧凑、可持久化，刷新后仍按公开时间线恢复。
5. 收尾：只在不和最终 assistant 正文重复时显示。
6. 停止：停止状态独占，出现后不再显示 running、发光、spinner 或旧失败动作。

## 权威链

```text
backend public_timeline / frontend runtime live events
-> publicTimeline normalize/merge
-> agentRunProjection
-> ChatMessage / PublicRunActivity render
```

职责边界：

- `publicTimeline.ts`：只负责标准化、合并、终态修正和去重，不决定页面主次。
- `agentRunProjection.ts`：唯一展示权威，负责时序、去重、tone、开局/动作/反馈/todo/收尾/停止选择。
- `ChatMessage.tsx`：只渲染真实 assistant 正文或真实开局判断，不再从工具动作推断正文。
- `PublicRunActivity.tsx`：只渲染投影结果，不再自己生成 `activityPlan`、`activitySummary` 或 closeout 推断。
- `agentRunPresentation.ts`：保留动作归一化、路径压缩、文本清洗等低层能力，移除动作生成开局的兜底权力。
- `runtime.ts`：把可公开 observation 映射成 `observation_report` 或有 observation 的 `work_action`，不得直接丢弃。

## 当前冲突和处理

| 位置 | 当前问题 | 处理 |
| --- | --- | --- |
| `ChatMessage.tsx` | `assistantContentFromTimeline` 调 `agentOpeningSignalFromTimeline`，会把工具动作伪造成正文开局 | 只允许真实 content、`opening_judgment`、`assistant_text` 进入正文 |
| `agentRunPresentation.ts` | `openingFallbackItem` / `openingTextForItem` 从工具动作生成开局 | 删除该兜底；保留 `actionViewForTimelineItem` 等低层归一化 |
| `PublicRunActivity.tsx` | `activityPlan` / `activitySummary` 自己决定 current、final、waiting、stopped | 改为接收/生成 `AgentRunProjection` 后渲染 |
| `runtime.ts` | `kind === "observation"` 直接 `return null` | 映射为 `observation_report`，内部 todo / 结构化噪声仍过滤 |
| `globals.css` | 存在多套状态样式，运行和停止视觉不够清晰 | 统一为正文感投影：动作弱化、反馈正文化、停止无运行动效 |
| 旧测试 | 仍期待工具开局生成正文判断 | 改为验证正文不伪造、活动投影显示动作 |

## 新投影结构

```ts
type AgentRunProjectionTone = "running" | "done" | "waiting" | "stopped" | "soft_error";

type AgentRunProjection = {
  opening: string;
  liveAction: string;
  feedback: string;
  todo: TodoProjection | null;
  closeout: string;
  stopped: string;
  tone: AgentRunProjectionTone;
  details: AgentRunDetail[];
};
```

投影规则：

- `stopped` 优先级最高。只要存在 stopped / aborted / cancelled 终态，投影层只输出停止反馈和必要 closeout，不输出 liveAction。
- `feedback` 优先使用最新 `observation_report`，其次使用已完成动作的 `observation`，再从完成动作生成自然结果句。
- `liveAction` 只取最新 running / error 动作；如果同一语义 key 已有 done observation，则不再显示 running 残留。
- `opening` 只取真实 `opening_judgment` 或真实 `assistant_text`，不从工具动作 fallback。
- `todo` 从最新 `todo_plan` 投影，显示完成数、当前项和少量上下文。
- `closeout` 只取 `final_summary` / artifact 中不与 assistant 正文重复的内容。
- 清理外露标签：不得渲染 `观察结果`、`观察报告`、`观察：`、`执行中`、`需要调整`、原始 tool id、内部 event id。

## 实施步骤

1. 新增 `frontend/src/components/chat/agentRunProjection.ts` 和单元测试。
2. 修改 `runtime.ts`，恢复 monitor observation 到公开时间线。
3. 修改 `ChatMessage.tsx`，移除动作推断正文开局，统一计算 projection 后传给活动组件。
4. 重写 `PublicRunActivity.tsx` 为纯投影渲染组件，删除旧 `activityPlan` / `activitySummary` 权威。
5. 清理 `agentRunPresentation.ts` 中动作转 opening 的兜底逻辑。
6. 调整 `globals.css` 中主会话投影样式，保持左对齐、正文感、弱动作、无停止动效。
7. 更新测试，覆盖时序、去重、observation 恢复、停止独占、todo 持久化和禁用标签。

## 验收用例

- 工具动作开局时，正文不伪造 opening，活动块显示动作反馈。
- `opening_judgment` 只渲染一次。
- running `tool_activity` / `work_action` 先显示动作。
- observation 返回后显示结果反馈，并替换或压过同一动作运行态。
- 停止后显示本轮已停止，没有 running 类、发光或 spinner。
- todo 通过公开时间线刷新后仍保留。
- 最终回答和 closeout 重复时不重复显示。
- 页面不出现 raw tool name、英文 tool id、内部 event id、`观察结果`、`观察报告`、`观察：`、`执行中`、`需要调整`。

## 检查结论

审查 `ChatMessage.tsx`、`PublicRunActivity.tsx`、`agentRunPresentation.ts`、`runtime.ts`、`events.ts`、`publicTimeline.ts` 和现有测试后，计划没有方向性矛盾。需要补充进实施范围的遗漏有两项：

- `publicTimeline.ts` 的 merge/normalize 可以保留，但它不是页面展示权威。
- 旧测试中“工具动作生成开局正文”的期望必须改掉，否则会继续保护错误体验。

## 验证命令

```powershell
cd frontend
npm test -- --run src/components/chat/agentRunProjection.test.ts src/components/chat/PublicRunActivity.test.ts src/components/chat/ChatMessage.test.ts src/components/chat/ChatPanel.test.ts src/lib/store/runtime.test.ts
npm run lint
```

涉及运行链路和页面可用性，实施完成后必须使用固定端口重启并检查：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/project_stack.ps1 -Action stop
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/project_stack.ps1 -Action start -FrontendMode dev
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/project_stack.ps1 -Action check
```
