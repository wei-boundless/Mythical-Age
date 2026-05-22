# Workbench Three-Pane Frontend Plan 2026-05-22

## Goal

把前端改成低噪声、实用优先的 Agent 工作台：左侧资源定位，中间主工作区，右侧辅助工具。参考方向是简洁 IDE/浏览器式布局，不做营销页、装饰背景或堆卡片。

## Structure

- 左侧：固定窄 rail + 可伸缩资源栏。
  - rail 用图标切换主层级：主会话、图任务层、能力系统、项目/文件。
  - 资源栏按 tab 切换项目、会话、文件；文件树只展示高价值入口，不把所有实现细节摊满。
- 中间：主工作区。
  - 顶部是紧凑工具栏。
  - 主会话、图任务层、能力系统仍按现有路由状态切换。
  - 对话输入继续固定在视觉底部。
- 右侧：可伸缩辅助栏。
  - tab：监控、网页、运行详情。
  - 监控沿用真实 live monitor，不再伪装历史任务。
  - 网页提供 URL 输入和 iframe 预览。
- 三栏宽度：左栏、右栏均可拖拽，持久化到 localStorage；中间自适应。

## Visual Direction

- 工具型、干净、薄边框、高信息密度。
- 背景以近白和冷灰为主，蓝色只作状态和选中信号。
- 不使用大 hero、灵魂背景、装饰 orb 或过多卡片。
- 使用图标按钮和紧凑 tab，避免解释性副标题。

## Implementation Steps

1. 新增 Workbench shell 组件，承载 rail、左资源栏、中间工作区、右辅助栏和拖拽分隔条。
2. 改造 `page.tsx`，用 shell 包住现有 `ChatPanel`、`TaskSystemView`、`CapabilitySystemView`。
3. 将 `TaskMonitorDock` 改为可嵌入右侧 tab 的面板，保留刷新、折叠和详情能力。
4. 新增网页辅助面板，支持输入 URL 并在右栏打开。
5. 新增文件/项目资源栏，使用已有 inspector file API 和 store，不新增后端。
6. 重写工作台相关 CSS，清理旧 practical workspace 的视觉噪声和灵魂背景残留。
7. 运行构建和关键测试，启动页面并检查桌面宽度下三栏渲染。

## Acceptance

- 访问 `http://localhost:3000/` 首屏就是三栏工作台。
- 左右栏可以拖拽改变宽度，刷新后保持。
- 左侧可切换项目/会话/文件，文件能打开到内置编辑器。
- 右侧可切换监控/网页，网页能打开输入的 URL。
- 监控列表不再显示一屏伪运行历史。
- `npm run build` 通过。
