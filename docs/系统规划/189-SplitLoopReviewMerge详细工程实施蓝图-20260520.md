# 189-Split/Loop/Review/Merge 详细工程实施蓝图

日期：2026-05-20

## 1. 目标

本计划只解决一个工程目标：

```text
把“用户要求的任务范围”编译成可追踪批次，
让每个批次走 execute -> review -> repair loop -> commit，
最终 merge 只消费 committed batch。
```

它不做写作专用逻辑。章节只是 `unit_kind=chapter` 的一个示例，同一套机制必须能支持：

- 文件批次
- 数据批次
- 图片批次
- 资料源批次
- 测试用例批次
- 章节批次

## 2. 核心边界

### 2.1 split 和 loop 的分工

```text
split = 范围编译器
loop = 执行控制器
review = 批次验收器
commit = 状态提升器
merge = 汇总器
```

split 负责：

- 生成 batch_id。
- 定义每个 batch 的范围。
- 定义 batch 顺序。
- 生成幂等键基础。
- 给 execution package 提供可检查计划。

loop 负责：

- 在一个 batch 内根据审核结果决定是否返修。
- 控制 max_repair_rounds。
- 不负责生成新 batch 范围。

review 负责：

- 检查 candidate packet 是否合格。
- 输出 pass/revise/block/manual_gate。

commit 负责：

- 把通过审核的 candidate 提升为 committed packet。
- 只有 committed packet 对后续 batch 和 final merge 可见。

merge 负责：

- 按 batch_sequence 汇总 committed packet。
- 拒绝消费 candidate packet。
- 根据 merge policy 处理缺失或失败 batch。

### 2.2 第一阶段绝对不做

第一阶段不做：

- 不启动子任务。
- 不改 active scheduler。
- 不做动态 split。
- 不让 agent 自己生成 batch。
- 不做领域私门。

第一阶段只做：

```text
配置 -> 编译 -> execution package 展示 -> 前端可见 -> 测试通过
```

## 3. 数据模型设计

### 3.1 BatchRange

文件：`backend/tasks/task_split_merge_models.py`

```python
@dataclass(frozen=True, slots=True)
class BatchRange:
    start: int
    end: int
    label: str

    def to_dict(self) -> dict[str, Any]:
        ...
```

规则：

- `start >= 1`
- `end >= start`
- `label` 必须稳定。

### 3.2 BatchSpec

```python
@dataclass(frozen=True, slots=True)
class BatchSpec:
    batch_id: str
    sequence_index: int
    unit_kind: str
    range: BatchRange
    input_contract_id: str = ""
    output_contract_id: str = ""
    idempotency_key: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
```

规则：

- `batch_id` 必须稳定。
- `sequence_index` 从 1 开始。
- `idempotency_key` 由 graph_id、node_id、plan_id、batch_id 生成。

### 3.3 BatchAcceptancePolicy

```python
@dataclass(frozen=True, slots=True)
class BatchAcceptancePolicy:
    mode: str = "review_then_commit"
    review_graph_id: str = ""
    review_node_id: str = ""
    repair_policy: str = "repair_until_pass_or_manual_gate"
    max_repair_rounds: int = 3
    commit_visibility: str = "next_batch_after_acceptance"
```

支持模式第一阶段只做诊断：

- `review_then_commit`
- `manual_commit`
- `auto_commit_without_review`

其中 `auto_commit_without_review` 必须给 warning，因为长任务不推荐。

### 3.4 BatchMergePolicy

```python
@dataclass(frozen=True, slots=True)
class BatchMergePolicy:
    mode: str = "wait_all_committed"
    result_order: str = "batch_sequence"
    allow_partial: bool = False
    final_review_required: bool = True
```

第一阶段支持：

- `wait_all_committed`
- `manual_merge`

其他模式标记 unsupported。

### 3.5 StaticSplitPlan

```python
@dataclass(frozen=True, slots=True)
class StaticSplitPlan:
    plan_id: str
    graph_id: str
    node_id: str
    unit_kind: str
    requested_count: int
    batch_size: int
    range_start: int
    batches: tuple[BatchSpec, ...]
    acceptance_policy: BatchAcceptancePolicy
    merge_policy: BatchMergePolicy
    issues: tuple[SplitMergeIssue, ...]
    metadata: dict[str, Any] = field(default_factory=dict)
```

### 3.6 SplitMergeIssue

```python
@dataclass(frozen=True, slots=True)
class SplitMergeIssue:
    code: str
    message: str
    severity: str = "error"
    graph_id: str = ""
    node_id: str = ""
    plan_id: str = ""
```

## 4. 配置契约

### 4.1 contract_bindings 路径

节点上统一保存：

```text
node.contract_bindings.unit_batch
node.contract_bindings.runtime.split_policy
node.contract_bindings.runtime.batch_acceptance_policy
node.contract_bindings.runtime.merge_policy
```

不要新增旧字段。

### 4.2 最小配置

```json
{
  "unit_batch": {
    "unit_kind": "chapter",
    "requested_count": 50,
    "batch_size": 10,
    "range_start": 1,
    "range_label_template": "{unit_kind}_{start}_{end}",
    "ordering": "ascending"
  },
  "runtime": {
    "split_policy": {
      "mode": "static_batch",
      "max_batches": 20,
      "child_execution_mode": "sequential"
    },
    "batch_acceptance_policy": {
      "mode": "review_then_commit",
      "repair_policy": "repair_until_pass_or_manual_gate",
      "max_repair_rounds": 3,
      "commit_visibility": "next_batch_after_acceptance"
    },
    "merge_policy": {
      "mode": "wait_all_committed",
      "result_order": "batch_sequence",
      "allow_partial": false,
      "final_review_required": true
    }
  }
}
```

### 4.3 通用例子

50 章：

```json
{"unit_kind": "chapter", "requested_count": 50, "batch_size": 10}
```

100 个文件：

```json
{"unit_kind": "file", "requested_count": 100, "batch_size": 20}
```

30 个图片：

```json
{"unit_kind": "image", "requested_count": 30, "batch_size": 5}
```

## 5. 后端实现阶段

### 5.1 阶段 A：模型和纯函数 builder

新增文件：

```text
backend/tasks/task_split_merge_models.py
backend/tasks/task_split_plan_builder.py
backend/tests/task_split_plan_builder_regression.py
```

核心函数：

```python
def build_static_split_plan(
    *,
    graph_id: str,
    node_id: str,
    contract_bindings: dict[str, Any],
) -> StaticSplitPlan | None:
    ...
```

输入：

- graph_id
- node_id
- node.contract_bindings

输出：

- 无配置返回 None。
- 有配置返回 StaticSplitPlan。
- 配置错误也返回 plan，但带 issues。

批次生成规则：

```python
range_start = 1
requested_count = 50
batch_size = 10

1-10
11-20
21-30
31-40
41-50
```

如果 `requested_count=53`：

```text
1-10
11-20
21-30
31-40
41-50
51-53
```

### 5.2 阶段 B：编译器 diagnostics 接入

修改文件：

```text
backend/tasks/coordination_graph_compiler.py
```

接入点：

`compile_task_graph_definition_runtime_spec()` 中 runtime spec 返回前，对 graph.nodes 扫描：

```python
split_plans = [
    plan for node in graph.nodes
    if (plan := build_static_split_plan(...)) is not None
]
```

放入：

```python
diagnostics={
  ...
  "split_plans": [plan.to_dict() for plan in split_plans],
  "split_merge_issues": [...]
}
```

第一阶段不修改：

- runtime nodes
- runtime edges
- scheduler state

### 5.3 阶段 C：ExecutionPackage 接入

修改文件：

```text
backend/api/tasks.py
```

在 `_compiled_task_graph_execution_parts()` 或 `build_task_system_task_graph_execution_package()` 中读取：

```python
split_plans = runtime_spec.diagnostics.get("split_plans") or []
split_merge_issues = runtime_spec.diagnostics.get("split_merge_issues") or []
```

输出：

```json
{
  "split_plans": [...],
  "split_merge_issues": [...],
  "summary": {
    "split_plan_count": 1,
    "split_batch_count": 5,
    "split_merge_issue_count": 0
  }
}
```

object_trace_index 增加：

```json
{
  "object_type": "split_plan",
  "object_id": "split:graph.xxx:node.writer",
  "source_path": "graph.nodes[node.writer].contract_bindings.unit_batch",
  "runtime_ref": {"node_id": "node.writer"},
  "status": "ready"
}
```

### 5.4 阶段 D：后端测试

新增测试：

```text
backend/tests/task_split_plan_builder_regression.py
```

测试用例：

1. 50 / 10 生成 5 批。
2. 53 / 10 生成 6 批，最后 51-53。
3. batch_size=0 报 error。
4. requested_count 缺失报 error。
5. max_batches 超限报 error。
6. merge_policy 缺失默认 wait_all_committed。
7. auto_commit_without_review 报 warning。
8. unsupported split mode 报 error。

扩展：

```text
backend/tests/task_graph_execution_package_regression.py
```

测试 execution package 输出 split plan summary。

## 6. 前端实现阶段

### 6.1 API 类型

修改：

```text
frontend/src/lib/api.ts
```

给 `TaskGraphExecutionPackage` 增加：

```ts
split_plans?: Array<Record<string, unknown>>;
split_merge_issues?: Array<Record<string, unknown>>;
```

summary 增加：

```ts
split_plan_count?: number;
split_batch_count?: number;
split_merge_issue_count?: number;
```

### 6.2 contract helper

修改：

```text
frontend/src/components/workspace/views/task-system/taskGraphContractBindings.ts
```

新增 helper：

```ts
getUnitBatchBindings(target)
updateUnitBatchBindings(target, patch)
getRuntimeSplitPolicy(target)
updateRuntimeSplitPolicy(target, patch)
getRuntimeBatchAcceptancePolicy(target)
updateRuntimeBatchAcceptancePolicy(target, patch)
getRuntimeMergePolicy(target)
updateRuntimeMergePolicy(target, patch)
```

### 6.3 节点编辑台增加批次分区

修改：

```text
TaskGraphNodeUnitInspector.tsx
```

新增 section：

```text
批次拆分
```

字段：

- 单位类型 `unit_kind`
- 总数量 `requested_count`
- 每批数量 `batch_size`
- 起始序号 `range_start`
- 最大批次数 `max_batches`
- 执行顺序 `child_execution_mode`
- 每批审核模式 `batch_acceptance_policy.mode`
- 最大返修轮次 `max_repair_rounds`
- 汇总模式 `merge_policy.mode`
- 最终审核 `final_review_required`

写入：

```text
contract_bindings.unit_batch
contract_bindings.runtime.split_policy
contract_bindings.runtime.batch_acceptance_policy
contract_bindings.runtime.merge_policy
```

不要写旧字段。

### 6.4 发布包显示 split plan

修改：

```text
TaskGraphExecutionPackagePanel.tsx
```

新增区块：

```text
批次拆分计划
```

显示：

- plan id
- node id
- unit kind
- requested count
- batch size
- batch count
- acceptance policy
- merge policy
- batch 列表前 10 个
- issues

### 6.5 底部 dock 追踪

修改：

```text
TaskGraphExecutionDock.tsx
```

当前对象是节点且有关联 split_plan 时显示：

```text
SplitPlan 5 batches / review_then_commit / wait_all_committed
```

### 6.6 前端预检

修改：

```text
taskGraphPreflight.ts
```

新增预检：

- requested_count 缺失。
- batch_size 缺失。
- batch_size > requested_count 给 info 或 warning。
- auto_commit_without_review 给 warning。
- final_review_required=false 给 warning。

## 7. Review / Repair / Commit 设计

### 7.1 第一阶段只编译，不运行

第一阶段只在 split plan 中声明：

```json
{
  "acceptance_policy": {
    "mode": "review_then_commit",
    "repair_policy": "repair_until_pass_or_manual_gate",
    "max_repair_rounds": 3,
    "commit_visibility": "next_batch_after_acceptance"
  }
}
```

### 7.2 第二阶段运行时对象

第二阶段再新增：

```text
BatchCandidatePacket
BatchReviewPacket
BatchCommitPacket
BatchRepairRequest
```

状态机：

```text
planned
-> running
-> candidate_ready
-> review_running
-> review_passed / review_rejected / manual_gate
-> repair_running
-> committed
-> merge_ready
```

### 7.3 merge 只消费 committed

merge 规则：

```text
candidate packet 不能 merge
review_rejected packet 不能 merge
committed packet 可以 merge
failure packet 按 merge_policy 处理
```

第一阶段把这个规则写进 plan，第二阶段再 runtime 执行。

## 8. 与 loop 的结合

每个 batch 内部可以有 repair loop：

```text
execute batch
review batch
if rejected and repair_round < max:
    repair batch
    review again
else if rejected:
    manual gate or fail
commit only if passed
```

工程实现上：

- split plan 生成 batch。
- loop frame 控制 batch 内 repair。
- merge 等待 committed batch。

loop 不生成 batch，也不决定 batch 范围。

## 9. 风险和控制

### 9.1 风险：配置复杂

控制：

- 第一版前端给默认值。
- 高级字段折叠。
- 提供模板：按数量拆分、按文件列表拆分、按章节拆分。

### 9.2 风险：用户以为已经自动执行

控制：

- L1 UI 明确显示“编译计划，尚未自动启动批次运行”。
- 只有 L2 后才显示“可运行批次”。

### 9.3 风险：review 缺失导致污染

控制：

- `auto_commit_without_review` 警告。
- merge 默认 `wait_all_committed`。
- 下一批默认只能读 committed output。

### 9.4 风险：改动过大

控制：

- L1 不改 scheduler。
- L1 不改 runtime。
- 只新增 diagnostics 和 execution package 字段。

## 10. 第一轮完成标准

第一轮完成后，必须能做到：

1. 在节点配置中填写：

```text
unit_kind=chapter
requested_count=50
batch_size=10
review_then_commit
wait_all_committed
```

2. 保存后编译 execution package。

3. 发布包显示：

```text
5 batches
chapter_001_010
chapter_011_020
chapter_021_030
chapter_031_040
chapter_041_050
acceptance: review_then_commit
merge: wait_all_committed
```

4. 测试证明：

- 不会写入旧字段。
- 不启动子任务。
- 不影响现有 GraphUnit。
- 不影响没有 split 配置的任务图。

## 11. 第二轮入口

第一轮稳定后，第二轮才开始：

- BatchCandidatePacket。
- BatchReviewPacket。
- BatchCommitPacket。
- GraphUnit child run 批次化。
- MergeGate shadow state。

第二轮仍不做动态 split。

## 12. 第三轮入口

第三轮才考虑动态 split：

- Agent structured split request。
- split request validator。
- max child flow。
- idempotency。
- cancellation。
- partial merge。

没有前两轮，第三轮不能开始。

