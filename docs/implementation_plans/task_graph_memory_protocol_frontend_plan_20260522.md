# 通用任务图 Memory Protocol 前端可见层实施计划

日期：2026-05-22

## 目标

上一阶段已经让后端标准视图输出 `memory_protocol`。本阶段继续把它接入图编辑器可见层：资源流页面、预检和 API 类型都以通用协议为准，而不是让前端继续从草稿 nodes / edges 中反推仓库和读写语义。

这是通用任务图编辑器能力，不引入写作任务边界。

## 界面分类

- 产品类型：通用 Agent 任务图编辑器。
- 用户角色：任务图设计者、运行编排者、协议维护者。
- 主对象：TaskGraphDefinition 及其标准视图。
- 页面层级：图工作台 > 资源流层 > protocol / repository / edge / runtime store 分面。
- 页面形态：高密度工作台，不做营销页，不做说明式副标题堆叠。

## 当前问题

1. 前端 `TaskGraphStandardView` 类型没有 `memory_protocol` 和 `collection_specs`，后端新增协议无法被类型系统承接。
2. `TaskGraphMemoryArtifactPage` 仍以本地 `memoryModel` 为主，标准视图只做摘要，没有展示协议级 repositories / collections / read / write / commit / issues。
3. 预检主要依赖前端自建 memory matrix，后端协议 issue 没有统一进入 preflight 列表。
4. Collection 只显示基础字段，没有显式编辑 `content_requirement`，用户无法看出 canonical text 与 refs-only 的区别。
5. 资源页分面里“仓库结构”和“读写矩阵”有用，但缺一个“协议视图”作为运行真实结构的权威入口。

## 实施范围

### 1. API 类型

在 `frontend/src/lib/api.ts` 增加：

- `TaskGraphMemoryProtocol`
- `TaskGraphMemoryProtocolRepository`
- `TaskGraphMemoryProtocolCollection`
- `TaskGraphMemoryProtocolEdge`

并为 `TaskGraphStandardView` 增加 `memory_protocol`，为 `TaskGraphStandardResourceSpec` 增加 `collection_specs`。

### 2. 标准视图模型

在 `taskGraphStandardView.ts` 增加 `buildTaskGraphMemoryProtocolStandardModel`：

- 从 `standardView.memory_protocol` 读取 repositories / collections / read_edges / write_edges / commit_edges / issues。
- 输出 issue count、canonical collection count、refs-only collection count、edge count by operation。
- 只使用通用协议词，不引入业务领域词。

### 3. 预检对接

在 `taskGraphPreflight.ts`：

- `standardView` 入参加入 `memory_protocol`。
- 将 `memory_protocol.issues` 转成 `TaskGraphPreflightIssue`。
- source 使用 `backend.memory_protocol`。
- issue scope 按 edge_id / node_id / graph 判断。
- 保留前端本地预检，但后端协议 issue 是更权威的运行协议预检来源。

### 4. 资源流页面

在 `TaskGraphMemoryArtifactPage.tsx`：

- 新增 `protocol` 分面，作为资源流首页分面。
- 顶部摘要增加 protocol repositories / collections / read / write / commit / issues。
- 协议分面显示：
  - repository 列表
  - collection 表
  - read/write/commit 边列表
  - protocol issues
- 仓库结构分面增加 `content_requirement` 编辑：
  - canonical_text_required
  - artifact_ref_only_allowed
- 新增集合默认时写入通用 content requirement，避免空壳 collection。

### 5. 验证

- 跑 `npm test` 或针对可用测试。
- 跑 TypeScript 检查：优先 `npm run build`；若太重，至少用 `npx tsc --noEmit`。
- 如启动本地前端可行，打开图编辑器页面做一次目视检查。

## 不做

1. 不大改工作台主导航。
2. 不改后端协议结构，除非前端暴露出真实结构缺陷。
3. 不把写作图的记忆分类、世界观、大纲等概念写入通用编辑器。
4. 不删除已有 matrix / selector / snapshot 分面，它们是编辑手段；本轮只是增加协议权威视图。

## 验收

1. 前端类型能识别 `standardView.memory_protocol`。
2. 资源流页能显示协议摘要和协议 issue。
3. 预检能显示后端 memory protocol issue，并可定位 edge。
4. collection 可编辑内容要求，用户能明确 canonical 与 refs-only。
5. 前端测试或类型检查通过。
