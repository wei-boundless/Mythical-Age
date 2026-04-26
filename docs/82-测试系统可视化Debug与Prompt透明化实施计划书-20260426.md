# 测试系统可视化 Debug 与 Prompt 透明化实施计划书

日期：2026-04-26

## 0. 当前实施进度

第一轮闭环已经完成到可用状态：

- 后端已经新增 turn 列表、run overlay、turn overlay 和 prompt manifest API。
- QueryRuntime 会在模型调用前生成 `prompt_manifest` 旁路事件，并写入 trace 标注。
- 测试系统可以从 turn 卡片跳转到系统框架图，图上会显示运行路径、异常节点、异常链路和第几个节点出问题。
- 系统框架图里的“提示词组装”节点已经可以显示 Prompt 是否被记录，并展开静态层、会话层、当前轮层的来源摘要。

下一步重点不是再搭骨架，而是继续增强图上的诊断密度：把 trace 耗时、输入输出摘要、Prompt 来源差异和节点状态解释做得更细。

## 1. 这次要解决什么

现在测试系统已经能从前端运行 `smoke / stable / long`，也能读取最近运行、日志、失败问题和基础报告。系统框架页也已经有一张根据后端代码整理出的项目运行关系图，失败 issue 可以跳过去高亮相关节点。

但它现在还停留在“报告能看、节点能定位”的阶段。下一步要做的是把一次测试运行真正读成系统运行链路：

```text
测试运行
-> run_result / issues / trace / turn artifact
-> 每轮对话运行路径
-> 系统框架图 overlay
-> 节点与连线详情
-> Prompt 装配 manifest
-> 可视化 Debug 判断
```

也就是说，我们要让测试系统不只是告诉我们“哪里失败”，而是能直接回答：

- 这一轮对话经过了哪些系统节点？
- 哪条链路调用了工具、检索、记忆或模型？
- 失败是出在执行链、状态链、记忆链、证据链、工具链，还是 prompt 装配？
- 模型这一轮到底读到了哪些 prompt 来源？
- 如果是 long 场景问题，能不能从第 N 轮直接跳到对应的系统路径？

正确的终态是：前端选择一次测试运行，点开某个 turn 或 issue，系统框架图立刻用图的形式显示这一轮真实或推断的运行路径，并能继续点开 `提示词组装`、`记忆门面`、`证据编排`、`工具与技能运行`、`模型流式输出` 等节点查看对应证据。

## 2. 当前代码基础

已经完成的基础能力：

- `backend/experiments/catalog.py`
  定义前端可运行的测试 profile，目前是 `smoke / stable / long`。

- `backend/experiments/runner.py`
  负责启动、查询、取消测试运行，并维护运行状态。

- `backend/experiments/artifacts.py`
  读取 `run_result.json`、`issues.json`、`trace.jsonl`、`report.md`。

- `backend/experiments/graph_mapping.py`
  根据 issue 内容派生系统框架图节点和连线引用。

- `backend/api/experiments.py`
  暴露测试系统 API，目前已有 profiles、runs、artifacts、cancel。

- `frontend/src/components/workspace/views/TestSystemView.tsx`
  已经是测试系统页面，支持运行测试、查看最近运行、查看日志和失败问题。

- `frontend/src/components/workspace/views/SystemFrameworkView.tsx`
  已经是全页面系统框架图，节点和连线来自后端代码结构，并支持 issue 高亮。

- `frontend/src/lib/api.ts`
  已经包含基础实验系统 API client。

- `frontend/src/lib/store/types.ts`
  已有 `SystemGraphHighlight`，用于测试 issue 跳系统框架定位。

原始缺口：

- `trace.jsonl` 和 long 场景 turn artifact 还没有解析成系统框架图 overlay。已完成轻量解析，仍需补耗时聚合。
- 系统框架图只支持一次性高亮 issue，不能展示一轮运行路径和状态。已完成 turn overlay。
- Prompt 装配只有最终字符串，没有结构化 manifest。已完成 preview-only manifest。
- 测试报告、trace、turn artifact、prompt 来源之间还没有统一索引。已完成第一版 run/turn 索引，仍需把真实 turn id 和 prompt id 对齐得更严。
- 节点详情还不能显示该节点在某次运行中的事件、耗时、状态和输入输出摘要。

## 3. 设计原则

### 图是主界面，不是装饰

测试系统和系统框架的关系应该是：测试系统选择运行对象，系统框架负责可视化解释运行过程。图里的节点、连线、状态、错误和 prompt 来源都要能反查到测试产物或代码位置。

### 不重写测试体系

继续复用现有 `harness.run`、`run_result.json`、`issues.json`、`trace.jsonl`、`report.md` 和 long 场景 artifacts。新增能力放在 `backend/experiments` 里做派生解析，不要把已有测试 runner 改成另一套系统。

### 不污染原始报告

第一阶段不改写已有 `issues.json` 和 `run_result.json`。运行链路 overlay、turn 摘要、prompt manifest 都先由 API 派生。等结构稳定后，再考虑把索引 id 写入测试产物。

### Prompt 透明但不过度暴露

默认展示 prompt 的结构、来源、层级、字符数、preview 和是否进入模型，不默认保存或展示完整 prompt。完整内容只在本地 debug 模式开启。

### 运行链路和 Prompt 装配分开建模

运行链路回答“系统怎么跑”。Prompt manifest 回答“模型读到了什么”。两者在系统框架图里汇合，但后端数据结构要分开，避免 debug 时混成一团。

### 先推断链路，再做真实事件

第一版 overlay 可以根据现有 artifact 做启发式推断，并在 UI 标注“推断链路”。后续再让 runtime 写出更细的结构化事件，把推断逐步替换成真实观测。

## 4. 目标结构

### 4.1 测试运行对象

测试运行继续以 `output/test_runs/<run_id>/` 为根目录，常见文件保持不变：

```text
run_state.json
runner.log
run_result.json
issues.json
trace.jsonl
report.md
artifacts/**
```

新增的派生视图不强制落盘，优先通过 API 返回。

### 4.2 Turn 摘要

长场景测试需要能按 turn 展开。建议统一成：

```json
{
  "turn_id": "turn-46-doc",
  "index": 46,
  "scenario": "sixty-turn-real-user-marathon",
  "status": "failed",
  "summary": "PDF follow-up route drift",
  "artifact_path": "output/test_runs/.../turn-46-doc.json",
  "issue_count": 1,
  "has_trace": true,
  "has_prompt_manifest": false
}
```

### 4.3 系统图 Overlay

系统图 overlay 是测试系统和系统框架图之间的核心协议：

```json
{
  "run_id": "20260426-065921-long",
  "turn_id": "turn-46-doc",
  "mode": "inferred",
  "status": "failed",
  "summary": "第 46 轮出现 follow-up 路由漂移",
  "nodes": [
    {
      "id": "query-core",
      "status": "failed",
      "label": "对话执行核心",
      "events": ["astream", "plan_route=worker"],
      "latency_ms": null,
      "reason": "turn artifact 显示执行链进入主对话链后发生路由漂移"
    }
  ],
  "edges": [
    {
      "id": "query-evidence",
      "status": "failed",
      "events": ["expected pdf worker"],
      "latency_ms": null,
      "reason": "本轮应续接文档证据链，但实际链路未稳定绑定"
    }
  ],
  "artifacts": {
    "run_result": "output/test_runs/.../run_result.json",
    "issues": "output/test_runs/.../issues.json",
    "trace": "output/test_runs/.../trace.jsonl",
    "turn": "output/test_runs/.../turn-46-doc.json"
  },
  "prompt_manifest_id": null
}
```

Overlay 中的 `node.id` 和 `edge.id` 必须对应 `SystemFrameworkView.tsx` 中已有的图 id，例如：

- `api-router`
- `runtime-root`
- `query-core`
- `planner`
- `prompt`
- `memory`
- `retrieval`
- `evidence`
- `tooling`
- `model`
- `session-store`
- `storage`
- `tests`

### 4.4 Prompt Manifest

Prompt manifest 用来描述一次模型调用前，系统 prompt 是怎么装配出来的：

```json
{
  "prompt_id": "20260426-065921-long:turn-46-doc",
  "run_id": "20260426-065921-long",
  "turn_id": "turn-46-doc",
  "total_chars": 18200,
  "assembly_order": ["static_prompt", "session_prompt", "turn_prompt"],
  "sections": [
    {
      "id": "active_seed",
      "title": "当前灵魂 seed",
      "layer": "static",
      "source": "backend/soul/agent_core/ACTIVE_SEED.md",
      "model_visible": true,
      "chars": 3200,
      "preview": "..."
    }
  ]
}
```

初始层级固定为：

- `static`：当前 seed、CORE、skills snapshot、grounding guard、prompt concealment guard。
- `session`：当前工作指引、active skill、session memory、active process context、hot truth window。
- `turn`：当前轮长期记忆、exact durable context、retrieval evidence、当前轮相关材料。

## 5. 固定执行流

前端测试到可视化 Debug 的固定流程：

```text
进入测试系统
-> 选择或启动 run
-> 读取 run summary 与 artifacts
-> 如果有 issues，显示问题列表
-> 如果有 turns，显示 turn 列表
-> 点击 issue 或 turn
-> 请求 graph overlay
-> 切换到系统框架
-> 系统框架图渲染 overlay
-> 点击节点或连线查看运行详情
-> 点击提示词组装节点查看 prompt manifest
```

这条流里，测试系统负责“选择对象”，系统框架负责“解释链路”，Prompt manifest 负责“解释模型输入”。

## 6. 后端实施计划

### Phase 1：Trace-to-Graph API

目标：把现有测试产物转换成系统框架图 overlay。

新增文件：

- `backend/experiments/trace_graph.py`

职责：

- 读取 `run_result.json`。
- 读取 `issues.json`。
- 读取 `trace.jsonl`。
- 扫描 long 场景 `artifacts/**/turn-*.json`。
- 从 turn、issue、trace 中提取 route、tool、memory、retrieval、model、session 等信号。
- 生成 run-level overlay 和 turn-level overlay。

新增 API：

```text
GET /api/experiments/runs/{run_id}/turns
GET /api/experiments/runs/{run_id}/graph-overlay
GET /api/experiments/runs/{run_id}/turns/{turn_id}/graph-overlay
```

第一版推断规则：

- 所有对话默认经过 `api-router -> runtime-root -> query-core -> model -> session-store`。
- 出现 follow-up、planner、route、dispatch 信号时加入 `planner`。
- 出现 memory、durable、session memory、context package 信号时加入 `memory -> storage`。
- 出现 retrieval、rag、pdf、structured、evidence 信号时加入 `evidence -> retrieval -> storage`。
- 出现 tool、skill、direct_tool、function call 信号时加入 `tooling`。
- 出现 reasoning、DeepSeek、stream、SSE 信号时加强 `model` 和 `api-model` 链路。
- 出现 issue 时把对应节点和边标为 `failed` 或 `warning`。

完成标准：

- 对旧 run 缺少 turn artifact 时返回空 turns，不报错。
- 对 long run 能列出 turn。
- 任意 turn 能返回 overlay。
- overlay 的节点和边 id 都能在系统框架图中找到。

### Phase 2：系统框架图 Overlay 模式

目标：系统框架图支持运行路径，而不仅是 issue 高亮。

修改文件：

- `frontend/src/lib/store/types.ts`
- `frontend/src/lib/store/core.ts`
- `frontend/src/lib/store/runtime.ts`
- `frontend/src/lib/api.ts`
- `frontend/src/components/workspace/views/TestSystemView.tsx`
- `frontend/src/components/workspace/views/SystemFrameworkView.tsx`

新增前端类型：

```ts
type SystemGraphOverlay = {
  runId: string;
  turnId?: string;
  mode: "inferred" | "observed";
  status: "passed" | "failed" | "warning" | "unknown";
  summary: string;
  nodes: Array<SystemGraphOverlayNode>;
  edges: Array<SystemGraphOverlayEdge>;
  artifacts: Record<string, string>;
  promptManifestId?: string | null;
};
```

视觉规则：

- `passed`：柔和亮色描边。
- `warning`：黄橙色描边。
- `failed`：红橙色描边或脉冲提示。
- `unknown`：低透明度。
- `inferred`：图上显示“推断链路”。
- `observed`：图上显示“观测链路”。

完成标准：

- 测试系统点击 turn 后自动切到系统框架。
- 系统框架图显示该 turn 的路径。
- 点击 overlay 节点或连线能看到 reason、events、artifact path。
- 原来的 issue 高亮能力保留，不被 overlay 破坏。

### Phase 3：Prompt Manifest 生成

目标：让 prompt 装配透明、可追踪，但不改变实际 prompt 文本。

新增文件：

- `backend/query/prompt_manifest.py`

修改文件：

- `backend/query/prompt_builder.py`
- `backend/query/runtime.py`
- `backend/api/experiments.py`
- `backend/experiments/artifacts.py`

设计要求：

- 保留 `build_system_prompt(...)` 原行为。
- 新增并行函数生成 manifest，不改变最终 prompt 字符串。
- manifest 记录 section 来源、层级、字符数、preview、是否进入模型。
- 默认不保存完整 prompt content。
- 如果缺少 manifest，API 返回 `missing_manifest`，前端正常展示缺失状态。

建议函数：

```python
build_system_prompt_with_manifest(...)
build_prompt_manifest(...)
write_prompt_manifest_summary(...)
```

建议 API：

```text
GET /api/experiments/runs/{run_id}/turns/{turn_id}/prompt-manifest
```

完成标准：

- 一轮执行能生成 prompt manifest。
- manifest 能区分 static、session、turn 三层。
- manifest 的 `total_chars` 与实际 prompt 长度可对齐。
- 关闭 debug 全文模式时，不落盘完整 prompt。

### Phase 4：Prompt 装配可视化

目标：在前端能从系统框架图进入 prompt 装配分析。

前端修改：

- `SystemFrameworkView.tsx` 中 `prompt` 节点支持 overlay 详情。
- `TestSystemView.tsx` 的 turn 详情显示 `has_prompt_manifest`。
- 可选新增 `PromptManifestPanel` 组件，避免系统框架文件继续变大。

显示结构：

```text
提示词组装
├─ 静态层
├─ 会话层
└─ 当前轮层
```

每个 section 显示：

- 标题
- 来源
- 层级
- 字符数
- 是否进入模型
- preview
- 可选全文展开按钮

完成标准：

- 从某个 turn 能打开 prompt manifest。
- 能看到当前 seed、CORE、技能、记忆、检索证据是否进入 prompt。
- 能判断 prompt 问题来自哪一层。

### Phase 5：测试系统与系统框架双向联动

目标：从测试系统能进入图，从图也能回到对应测试运行。

前端行为：

- 系统框架 overlay 顶部显示当前 run 和 turn。
- 图上节点详情显示关联 artifact。
- 点击 artifact path 可在测试系统中选中对应 run。
- 点击 `tests` 节点可以回到测试系统。
- 点击 `memory / tooling` 等节点可以跳到对应工作台页面。

完成标准：

- 测试系统和系统框架之间不再是单向跳转，而是同一个 debug 工作流。
- 一个失败 turn 能同时看到运行链路、失败节点、prompt 装配和原始产物路径。

## 7. 文件级执行清单

### 后端新增

- `backend/experiments/trace_graph.py`
- `backend/query/prompt_manifest.py`

### 后端修改

- `backend/api/experiments.py`
  增加 turns、graph overlay、prompt manifest API。

- `backend/experiments/artifacts.py`
  补充 turn artifact 扫描和 trace 读取工具函数。

- `backend/experiments/graph_mapping.py`
  复用 issue 映射规则，并为 overlay 提供节点/边 id 常量。

- `backend/query/prompt_builder.py`
  增加 manifest 生成入口，保持原 prompt 输出不变。

- `backend/query/runtime.py`
  在 prompt 装配处生成 manifest 摘要，并与 run/turn 关联。

### 前端修改

- `frontend/src/lib/api.ts`
  增加 `listExperimentTurns`、`getExperimentGraphOverlay`、`getExperimentTurnGraphOverlay`、`getPromptManifest`。

- `frontend/src/lib/store/types.ts`
  增加 `SystemGraphOverlay`、`PromptManifest`、`ExperimentTurn` 类型。

- `frontend/src/lib/store/core.ts`
  增加 overlay 默认状态。

- `frontend/src/lib/store/runtime.ts`
  增加 `setSystemGraphOverlay`、`clearSystemGraphOverlay`。

- `frontend/src/components/workspace/views/TestSystemView.tsx`
  增加 turn 列表和“查看链路图”入口。

- `frontend/src/components/workspace/views/SystemFrameworkView.tsx`
  渲染 overlay 状态、选中详情、artifact 和 prompt manifest 入口。

- `frontend/src/app/globals.css`
  增加 overlay 节点、连线、状态面板、prompt tree 样式。

## 8. API 草案

### 列出测试轮次

```text
GET /api/experiments/runs/{run_id}/turns
```

返回：

```json
[
  {
    "turn_id": "turn-46-doc",
    "index": 46,
    "scenario": "sixty-turn-real-user-marathon",
    "status": "failed",
    "summary": "PDF follow-up route drift",
    "artifact_path": "output/test_runs/.../turn-46-doc.json",
    "issue_count": 1,
    "has_trace": true,
    "has_prompt_manifest": false
  }
]
```

### 读取整次运行 overlay

```text
GET /api/experiments/runs/{run_id}/graph-overlay
```

用途：看整次 run 中哪些系统节点最常失败。

### 读取单轮 overlay

```text
GET /api/experiments/runs/{run_id}/turns/{turn_id}/graph-overlay
```

用途：看某一轮对话实际或推断经过的运行链路。

### 读取 Prompt Manifest

```text
GET /api/experiments/runs/{run_id}/turns/{turn_id}/prompt-manifest
```

用途：看某一轮模型调用前的 prompt 装配结构。

## 9. 验证计划

### 后端验证

```bash
python -m py_compile backend/experiments/trace_graph.py backend/query/prompt_manifest.py backend/api/experiments.py
```

检查：

- `GET /api/experiments/runs/{run_id}/turns` 对新旧 run 都不报错。
- `GET /api/experiments/runs/{run_id}/graph-overlay` 能返回合法节点和边。
- `GET /api/experiments/runs/{run_id}/turns/{turn_id}/graph-overlay` 能返回单轮链路。
- 缺少 prompt manifest 时返回清晰的 missing 状态。

### 前端验证

```bash
npm run build
```

检查：

- 测试系统可以打开。
- 最近运行仍能读取。
- issue 点击定位仍然可用。
- turn 点击能切换到系统框架 overlay。
- overlay 不影响系统框架原本节点和连线点击。

### 测试链验证

```bash
python -m harness.run --profile smoke
python -m harness.run --profile stable
```

检查：

- 新 API 能读取新产生的 run。
- overlay 对 smoke/stable 即使没有 turn，也能返回 run-level 总览。

长场景验证：

```bash
python -m harness.run --profile long
```

检查：

- 能列出 turn。
- 失败 turn 能映射到系统框架。
- Prompt manifest 在开启后能显示 static/session/turn 三层。

## 10. 风险与边界

### Overlay 推断不等于真实链路

第一版 overlay 是从现有 artifact 中推断出来的，可能不完整。前端必须标注 `推断链路`，不要把它说成绝对真实路径。

### 旧产物不完整

旧 run 可能没有 turn artifact、trace 或 prompt manifest。API 要返回空列表或 missing 状态，不能直接 500。

### Prompt 泄漏风险

默认只展示 preview 和统计信息。完整 prompt 只能在本地 debug 模式开启，且需要明确标识。

### 前端图过载

系统框架图已经很密。Overlay 不应再追加大量永久节点，而应该用状态、路径和详情面板表达本次运行。

### 核心执行链不能被可视化改造影响

Prompt manifest 和 trace overlay 都应该是旁路观测能力，不能改变 QueryRuntime 的执行结果和模型输入。

## 11. 不做什么

第一轮不做：

- 不引入新的测试 runner。
- 不让前端传任意 shell 命令。
- 不默认保存完整 prompt。
- 不做复杂动画回放。
- 不接外部可观测平台。
- 不把所有 trace 原文一次性塞到前端。

这些不是否定，而是为了先把本地可用的 debug 闭环做稳。

## 12. 推荐实施顺序

建议按这个顺序开始：

1. **先做 `trace_graph.py` 和 overlay API**
   这一步不碰核心执行链，风险最低，而且立刻能复用已有测试产物。

2. **再改系统框架 Overlay UI**
   让测试系统点击 turn 后能真的把一次运行读成图。

3. **再做 Prompt Manifest**
   这一步会碰 prompt 装配核心，需要更小心，必须保证最终 prompt 文本不变。

4. **最后接 Prompt 可视化面板**
   让 `提示词组装` 节点成为可分析节点，而不是只在图上存在。

这个顺序的好处是每一步都能单独验收，也能随时回退。

## 13. 第一轮最小闭环

第一轮实施目标只锁定这几个点：

- 新增 `backend/experiments/trace_graph.py`。
- 新增 turns API。
- 新增 run-level 和 turn-level graph overlay API。
- 前端测试系统显示 turn 列表。
- 点击 turn 后切换到系统框架图。
- 系统框架图显示 overlay 节点和连线状态。

第一轮完成后，我们应该能做到：

```text
打开测试系统
-> 选择一次 long run
-> 点击 turn-46-doc
-> 系统框架图高亮这一轮经过的路径
-> 点击失败链路查看为什么映射到这里
```

这就是后续修 follow-up、记忆召回、工具续写、状态漂移问题时最重要的基础设施。
