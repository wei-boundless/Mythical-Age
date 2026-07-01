# 图任务算法适配器与 Tree Reduce 架构裁决

状态：MVP 接线实施中  
日期：2026-07-02

## 1. 核心裁决

图任务系统不应按业务硬编码运行方式，而应把“图如何推进”抽象成运行算法。

```text
writing graph      -> writing_iteration / loop_iteration algorithm
project review     -> tree_reduce algorithm
future deep search -> network_frontier / graph_walk algorithm
```

审查图不是一个特殊项目网络流程，本质是树状归约算法：

```text
物理树决定下一层
目录节点展开子目录和直接文件
文件节点是叶子，输出 module_index
目录节点等待子目录 summary 和直接文件 module_index，输出 directory_summary
根目录无父节点时输出整棵树的根级语义索引候选
```

这意味着旧的“目录渲染”概念必须收缩为 `tree materialization`：它只把物理骨架物化成下一层 `TaskGraphDefinition`，不拥有第二套调度权威。

## 2. 权威链路

成熟 agent / workflow graph 的标准是：运行路径只有一条主权威链，业务逻辑不能绕过图系统。

```text
Physical Skeleton
-> TreeGraphMaterialization
-> TaskGraphDefinition
-> ExecutableGraphConfig
-> GraphRuntime / GraphLoop
-> GraphNodeWorkOrder
-> agent typed output
-> runtime algorithm adapter
-> required side-effect sink
-> Project Network Store
-> parent tree reduce input
```

权威边界：

```text
file_management.project_structure
  提供物理骨架：目录、文件、AST、git facts。

tree_reduce algorithm
  决定叶子、分支、归约和根收口规则。

GraphLoop
  只执行已发布图配置、派发节点、接收结果、执行必需算法 side effect、推进状态。

project_network sink
  只摄取 typed work products，写入 store，登记 child return。

agent
  只审查 assigned_scope 指向的文件或目录帧，输出 typed work product。
```

## 3. 叶子和分支规则

叶子规则：

```text
如果物理节点是文件，或当前层没有子层需要展开：
  生成 leaf review node
  agent 只读取 assigned_scope 指定文件
  输出 product_kind=module_index
  side effect 将 work product 写入 Project Network Store
```

分支规则：

```text
如果物理节点是目录且存在子目录或直接文件：
  直接文件生成 leaf review nodes
  子目录先独立运行 tree_reduce 子图
  当前目录等待 child directory_summary refs 和 direct module_index refs
  目录汇总节点输出 product_kind=directory_summary
```

根节点规则：

```text
如果目录节点没有 parent_frame_id：
  directory_summary 是根级语义索引候选
  后续必须经过 schema / anchor / coverage / conflict curator
  只有 curator 允许发布到最终 Semantic Generation
```

## 4. 当前实现接线

已落地的关键接线：

```text
backend/graph_system/runtime_algorithm_adapters.py
  tree_reduce adapter 校验 graph_build_work_products。
  合格时声明 required side effect: project_network_work_product_ingest。
  合法空数组不再被误判为缺字段。

backend/graph_system/runtime_algorithm_effects.py
  GraphLoop 接收 NodeResult 前执行 required side effects。
  必需 side effect 缺 sink 或失败时，节点变为 blocked，不允许假成功推进。

backend/graph_system/loop.py
  accept_node_result() 先执行算法 effect，再存 NodeResult、更新边和状态。

backend/harness/runtime/services.py
  AgentRuntimeServices 暴露 runtime_algorithm_effect_sink。

backend/harness/entrypoint/runtime_facade.py
  harness 接住 project_network_work_product_ingest。
  通过 DirectoryRuntimeService.accept_directory_node_result() 写入 Project Network Store。

backend/task_system/project_network/template_catalog.py
  module_index / directory_aggregate 节点声明 runtime_algorithm=tree_reduce。
  失败策略为 retry_same_node。
```

## 5. 术语收缩

旧名称 `DirectoryRender*` 当前仍指代“目录树物化状态”，但它不应再被理解为独立渲染架构。

目标命名应逐步收敛为：

```text
DirectoryRenderBudget              -> DirectoryTreeBudget
DirectoryRenderFrame               -> DirectoryTreeFrame
DirectoryManifestProduct           -> DirectoryTreeManifest
DirectoryFrameMaterializationPackage -> TreeFrameMaterializationPackage
DirectoryRenderService             -> DirectoryTreeMaterializer
DirectoryRuntimeService            -> TreeReduceRuntimeService / ProjectNetworkTreeRuntimeService
```

迁名原则：

- 不保留两套执行路径。
- 迁名只改权威名称和导入路径，不改变 `TaskGraphDefinition -> ExecutableGraphConfig -> GraphLoop` 主链。
- 已持久化的旧 authority 只允许在 repository 读取边界做一次性规范化，不允许作为长期兼容分支参与运行。

## 6. 最终标准

项目语义网络建立要以树算法为运行骨架：

```text
系统抽物理树
算法铺运行树
agent 写语义产物
side-effect sink 入库
父层按 refs 归约
根层交 curator 发布
```

这样 agent 不需要“自己爬一步想一步”，它只是顺着已铺好的物理网络和算法路标行动。语义层给方向，物理层给落脚点，GraphLoop 给状态闭环。
