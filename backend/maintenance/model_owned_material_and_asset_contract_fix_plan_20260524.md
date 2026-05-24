# Model-Owned Material And Asset Contract Fix Plan - 2026-05-24

## 1. 问题定义

本计划修复两个在“接手旧浏览器游戏并增加第二层关卡”实验中暴露出的结构问题：

1. 材料路径抽取仍由正则和关键词承担理解职责，导致 `required_reads` 出现脏路径。
2. `assets/` 目录没有被识别为已有工程必须继承的结构化材料和产物，导致新 sandbox 丢失美术资源。

这不是“正则再写准一点”的问题。真实缺陷是：代码层在模型之前抢先理解用户目标，把自然语言里的路径、材料、输出和资产关系编译成硬 obligation。随后 runtime 和 validator 围绕这个错误契约执行和验收。

目标状态：

```text
用户请求
-> 主模型输出结构化理解结果
-> 程序编译为执行契约
-> runtime 执行工具
-> 程序按真实 evidence 验收
-> RunOutcome 统一收口
```

程序只允许做事实候选提取、权限边界、工具执行、证据验收，不允许用正则重新裁决“什么是材料、什么是产物、什么必须继承”。

## 2. 当前代码事实

### 2.1 脏材料路径来源

文件：[backend/intent/execution_obligation.py](D:/AI应用/langchain-agent/backend/intent/execution_obligation.py)

当前链路：

```text
build_execution_obligation()
-> _collect_required_reads()
-> _PATH_RE 扫描整段用户自然语言
-> _path_looks_like_required_input()
-> required_reads
```

实验 prompt 中这句：

```text
你必须先读回源项目的 index.html、styles.css、game.js、README.md，并检查 assets/ 目录
```

被抽成：

```text
game.js
README.md
并检查 assets/ 目录
```

根因：

- `_PATH_RE` 允许中文、空格、斜杠混合，导致“并检查 assets/ 目录”被当成路径。
- `_path_looks_like_required_input()` 只检查局部上下文是否有“读回/检查”等词，不能区分自然语言片段和真实路径。
- 目录材料没有正式数据结构，`source_project_dir` 没有变成 `required_read_dirs`。
- `execution_obligation.required_reads` 后续会进入 [backend/runtime/contracts/obligation_validation.py](D:/AI应用/langchain-agent/backend/runtime/contracts/obligation_validation.py)，成为硬验收项。

### 2.2 assets 没进入继承契约

相关文件：

- [backend/intent/execution_obligation.py](D:/AI应用/langchain-agent/backend/intent/execution_obligation.py)
- [backend/runtime/professional_runtime/goal_contract.py](D:/AI应用/langchain-agent/backend/runtime/professional_runtime/goal_contract.py)
- [backend/task_system/goal_profiles/task_goal_profiles.py](D:/AI应用/langchain-agent/backend/task_system/goal_profiles/task_goal_profiles.py)

当前 `game_vertical_slice_delivery` profile 只有抽象动作：

```text
integrate_asset
```

但没有产出具体 contract：

```text
source_asset_dirs
target_asset_dirs
required_asset_files
asset_reference_policy
```

`goal_contract` 当前会把目标输出目录展开成：

```text
frontend/public/games/arcane_dungeon_studio/index.html
frontend/public/games/arcane_dungeon_studio/styles.css
frontend/public/games/arcane_dungeon_studio/game.js
frontend/public/games/arcane_dungeon_studio/README.md
```

但不会把：

```text
source_project/assets/
target_project/assets/
```

纳入 required material / required output。

### 2.3 visual_asset_refs 验收过宽

文件：[backend/runtime/contracts/deliverable_validator.py](D:/AI应用/langchain-agent/backend/runtime/contracts/deliverable_validator.py)

当前 `_has_asset_evidence()` 只要 evidence 文本里出现：

```text
asset
assets/
.svg
资源
图片
```

就能满足 `visual_asset_refs`。这会把“源码里仍有 `assets/player.svg` 字符串引用”误判为“真实美术资源已存在”。

正确验收必须是：

```text
源码引用的 asset 路径
-> 在目标产物目录中存在真实文件
-> 文件来自复制/写入/生成证据
-> 才满足 visual_asset_refs
```

## 3. 设计原则

本计划继承仓库既有设计原则：

1. 主模型拥有当前轮理解权。
   依据：[backend/maintenance/model_owned_understanding_rebuild_plan_20260524.md](D:/AI应用/langchain-agent/backend/maintenance/model_owned_understanding_rebuild_plan_20260524.md)

2. 程序拥有证据验收权，不拥有语义猜测权。
   模型决定“要读什么、继承什么、写什么”；程序验证“是否真的读过、写过、验证过”。

3. `RunOutcome` 是唯一完成协议。
   依据：[docs/implementation_plans/run_outcome_unified_completion_design_20260524.md](D:/AI应用/langchain-agent/docs/implementation_plans/run_outcome_unified_completion_design_20260524.md)

4. Prompt / profile / contract 不重新理解用户目标。
   依据：[docs/implementation_plans/prompt_library_binding_and_dynamic_assembly_master_plan_20260523.md](D:/AI应用/langchain-agent/docs/implementation_plans/prompt_library_binding_and_dynamic_assembly_master_plan_20260523.md)

5. 正则只能产弱候选，不能产硬 obligation。
   正则输出必须命名为 `candidate_*` 或 `hints`，不得直接写入 `required_reads`、`required_writes`。

## 4. 目标架构

### 4.1 新的结构化理解结果

新增或扩展模型输出结构：

```python
ModelTurnDecision.resource_contract = {
    "source_projects": [
        {
            "path": "output/sandbox_runs/.../workspace/frontend/public/games/arcane_dungeon_studio",
            "role": "read_only_source_project",
            "required": True
        }
    ],
    "target_projects": [
        {
            "path": "frontend/public/games/arcane_dungeon_studio",
            "role": "sandbox_output_project",
            "required": True
        }
    ],
    "required_read_files": [
        "index.html",
        "styles.css",
        "game.js",
        "README.md"
    ],
    "required_read_dirs": [
        "assets"
    ],
    "required_write_files": [
        "index.html",
        "styles.css",
        "game.js",
        "README.md"
    ],
    "required_write_dirs": [
        "assets"
    ],
    "asset_policy": {
        "must_preserve_existing_assets": True,
        "referenced_assets_must_exist": True,
        "allow_generated_replacement": False
    }
}
```

命名原则：

- `source_projects` 是只读材料边界。
- `target_projects` 是写入边界。
- `required_read_files` 是相对源项目的读取要求。
- `required_write_files` 是相对目标项目的写入要求。
- `required_read_dirs` / `required_write_dirs` 明确支持目录。
- `asset_policy` 决定美术资源是继承、生成、替换还是混合。

### 4.2 编译后的执行契约

程序根据模型结构化结果编译：

```python
ExecutionObligation.required_reads = [
    {"path": "<source>/index.html", "kind": "code", "role": "source_file"},
    {"path": "<source>/styles.css", "kind": "code", "role": "source_file"},
    {"path": "<source>/game.js", "kind": "code", "role": "source_file"},
    {"path": "<source>/README.md", "kind": "text", "role": "source_file"},
    {"path": "<source>/assets", "kind": "asset_dir", "role": "source_asset_dir"}
]

ExecutionObligation.required_writes = [
    {"path": "<target>/index.html", "kind": "file_write"},
    {"path": "<target>/styles.css", "kind": "file_write"},
    {"path": "<target>/game.js", "kind": "file_write"},
    {"path": "<target>/README.md", "kind": "file_write"},
    {"path": "<target>/assets", "kind": "asset_dir_write"}
]
```

如果用户不是“接手旧项目”，而是“从零创建游戏”，则 asset policy 可以要求 `generated_assets` 或 `created_assets`，但不能伪装成继承。

### 4.3 正则降级为候选层

保留低风险候选提取：

```python
RequestFacts.path_candidates
RequestFacts.file_name_candidates
RequestFacts.directory_candidates
```

禁止：

```python
regex -> required_reads
regex -> required_writes
regex -> task_goal_type
regex -> asset_policy
```

只有模型输出或显式 API 参数可以进入 hard obligation。

## 5. 固定执行流

目标链路：

```text
UserMessage
  -> RequestFacts
     - 原文
     - path_candidates
     - explicit mode / selected task
     - workspace/session facts
  -> ModelTurnDecision
     - interaction_intent
     - action_intent
     - task_goal_type
     - resource_contract
     - todo_required
  -> TaskRequirementContract
     - 编译模型决策，不重新理解
  -> ExecutionObligation
     - 从 resource_contract 编译 required reads/writes/verifications
  -> GoalContract
     - 从 ExecutionObligation 投影专业任务目标，不再扫描自然语言补硬路径
  -> Runtime Execution
     - read/write/terminal/browser
  -> Evidence Ledger
     - 记录真实读、写、验证、资产文件
  -> Deliverable Validator
     - 验证源码引用与真实资产文件一致
  -> Obligation Validator
     - 验证 read/write/verify 都由真实工具观察满足
  -> RunOutcome
```

## 6. 分阶段实施计划

### Phase 1：建立 ResourceContract 数据模型

目标：让模型有正式位置输出材料、目标、资产继承关系。

涉及文件：

- `backend/agent_runtime/turn_decision.py` 或当前 `ModelTurnDecision` 定义所在模块
- `backend/agent_system/assembly/runtime_chain.py`
- `backend/tests/model_turn_decision_validation_regression.py`

工作项：

1. 新增 `resource_contract` 字段。
2. 定义 `source_projects`、`target_projects`、`required_read_files`、`required_read_dirs`、`required_write_files`、`required_write_dirs`、`asset_policy`。
3. 更新模型决策 schema 和校验。
4. 更新 professional prompt，让模型用清晰任务语言输出资源契约。

完成标准：

- 模型决策可以表达“只读源项目”和“目标输出目录”。
- 可以表达 `assets/` 必须继承。
- 没有 `resource_contract` 时，不从正则制造硬 reads/writes。

### Phase 2：ExecutionObligation 改为编译模型契约

目标：移除 `_PATH_RE` 对 `required_reads` 的硬生成权。

涉及文件：

- [backend/intent/execution_obligation.py](D:/AI应用/langchain-agent/backend/intent/execution_obligation.py)
- [backend/task_system/contracts/task_requirement_contracts.py](D:/AI应用/langchain-agent/backend/task_system/contracts/task_requirement_contracts.py)
- [backend/tests/execution_obligation_regression.py](D:/AI应用/langchain-agent/backend/tests/execution_obligation_regression.py)

工作项：

1. 新增 `_collect_required_reads_from_resource_contract()`。
2. 新增 `_collect_required_writes_from_resource_contract()`。
3. `_collect_required_reads()` 不再扫描自然语言生成 hard obligation。
4. 旧 `_PATH_RE` 只输出 diagnostics：`candidate_paths`。
5. 删除或隔离“中文自然语言 + slash”路径识别。

完成标准：

- 实验 prompt 不再产生 `game.js`、`README.md`、`并检查 assets/ 目录` 这种脏 required_reads。
- 源项目完整路径和 `assets/` 目录进入 required_reads。
- 目标项目和 `assets/` 目录进入 required_writes。

### Phase 3：GoalContract 停止补充硬路径

目标：`goal_contract` 只消费 `ExecutionObligation`，不再扫描用户自然语言补硬输出路径。

涉及文件：

- [backend/runtime/professional_runtime/goal_contract.py](D:/AI应用/langchain-agent/backend/runtime/professional_runtime/goal_contract.py)
- [backend/runtime/professional_runtime/required_action_queue.py](D:/AI应用/langchain-agent/backend/runtime/professional_runtime/required_action_queue.py)
- [backend/runtime/professional_runtime/tool_contract_gate.py](D:/AI应用/langchain-agent/backend/runtime/professional_runtime/tool_contract_gate.py)

工作项：

1. `_goal_contract_from_semantic_contract()` 只从 `execution_obligation.required_reads/writes` 生成 required paths。
2. `_build_goal_contract()` 中自然语言路径抽取降级为 legacy diagnostics 或删除。
3. required action queue 支持目录级输出，尤其 `assets/`。
4. 工具门禁提示改为“模型契约要求”，不再写“从文本提取到路径”。

完成标准：

- `goal_contract.required_material_paths` 与 `required_output_paths` 不含裸文件名和脏中文片段。
- 目录输出 `frontend/.../assets` 可被真实文件写入或复制满足。

### Phase 4：资产继承工具能力与证据记录

目标：让 agent 能真实继承目录资源，而不是只保留字符串引用。

涉及文件：

- 工具定义所在模块，重点检查 `write_file`、`edit_file`、`terminal`、可能已有的 `copy_file/list_dir` 能力
- [backend/runtime/memory/tool_observation_ledger.py](D:/AI应用/langchain-agent/backend/runtime/memory/tool_observation_ledger.py)
- `backend/runtime/tool_runtime/tool_result_envelope.py`

工作项：

1. 确认是否已有目录复制工具；没有则新增 `copy_path` 或允许 terminal 复制并结构化记录结果。
2. 对 `assets/` 目录写入/复制产生 `artifact_refs`。
3. ledger 增加 asset evidence 类型：
   - `source_asset_read`
   - `asset_write`
   - `asset_reference_check`
4. terminal 验证结果如果列出了真实文件，应进入 observed paths。

完成标准：

- 新 sandbox 中真实存在 `assets/player.svg` 等文件。
- ledger 能区分“源码引用了 asset”和“目标目录有真实 asset 文件”。

### Phase 5：visual_asset_refs 验收改为引用-文件一致性

目标：不能再用 `.svg` 字符串满足美术资源验收。

涉及文件：

- [backend/runtime/contracts/deliverable_validator.py](D:/AI应用/langchain-agent/backend/runtime/contracts/deliverable_validator.py)
- [backend/runtime/contracts/obligation_validation.py](D:/AI应用/langchain-agent/backend/runtime/contracts/obligation_validation.py)

工作项：

1. 从写入后的源码文件或 terminal 输出中提取 asset refs。
2. 对每个 `assets/*.svg/png/jpg/webp` 引用检查目标目录真实文件。
3. `visual_asset_refs` 满足条件改为：

```text
asset reference exists
AND referenced asset file exists
AND asset file has read/write/copy evidence
```

4. 如果引用存在但文件不存在，返回结构化缺失：

```json
{
  "missing_deliverables": ["visual_asset_refs"],
  "missing_assets": ["assets/player.svg", "..."],
  "repairable_by_tools": true
}
```

完成标准：

- 只有 `game.js` 出现 `.svg` 字符串不能通过 `visual_asset_refs`。
- assets 文件真实存在时通过。
- 缺资产时触发 evidence resubmission，而不是直接 partial 收口。

### Phase 6：修复收口与续跑

目标：当验收发现缺资产，应让 agent 继续修，而不是立刻最终 partial。

涉及文件：

- [backend/runtime/professional_runtime/driver.py](D:/AI应用/langchain-agent/backend/runtime/professional_runtime/driver.py)
- [backend/runtime/professional_runtime/evidence_closeout.py](D:/AI应用/langchain-agent/backend/runtime/professional_runtime/evidence_closeout.py)
- [backend/runtime/outcome/builder.py](D:/AI应用/langchain-agent/backend/runtime/outcome/builder.py)

工作项：

1. 将 `missing_assets` 纳入 resubmission tools 判断。
2. recovery prompt 明确告诉模型：

```text
你的源码引用了这些 asset，但目标目录缺真实文件。
请读取源 assets 目录并复制或生成对应文件。
完成后重新提交验证证据。
```

3. `RunOutcome.status=partial` 只在工具预算耗尽或模型拒绝修复后出现。

完成标准：

- 缺 asset 文件时 agent 会继续调用工具修复。
- 修复后 `RunOutcome.completed=true`。

## 7. 文件级执行清单

必须改：

- `backend/intent/execution_obligation.py`
  - 降级 `_PATH_RE`。
  - 新增 resource contract 编译。

- `backend/runtime/professional_runtime/goal_contract.py`
  - 停止从自然语言生成 hard paths。
  - 支持目录级 material/output。

- `backend/runtime/contracts/deliverable_validator.py`
  - 新增 asset refs 到真实文件的一致性验收。

- `backend/runtime/contracts/obligation_validation.py`
  - 目录 material/read 和 output/write 验收。

- `backend/runtime/memory/tool_observation_ledger.py`
  - 记录 asset read/write/copy evidence。

- `backend/runtime/professional_runtime/driver.py`
  - 缺资产触发继续修复。

可能改：

- `backend/task_system/contracts/task_requirement_contracts.py`
  - 消费 resource contract。

- `backend/agent_system/assembly/runtime_chain.py`
  - 将 `resource_contract` 从模型决策传入 current turn / task contract。

- `backend/prompting/professional_profiles.py`
  - 提示模型明确输出资源契约，但不能写内部 runtime 字段给最终用户。

- 工具 runtime 文件
  - 如需正式目录复制工具。

必须加/改测试：

- `backend/tests/execution_obligation_regression.py`
  - 接手旧项目 prompt 不产生脏 required_reads。
  - resource contract 编译出 source files/source assets/target files/target assets。

- `backend/tests/professional_task_run_regression.py`
  - assets 缺失时不通过 visual_asset_refs。
  - assets 存在时通过。

- `backend/tests/completion_judgment_regression.py`
  - 缺 asset 时 `completed=false`。

- `backend/tests/system_eval`
  - 增量接手游戏项目并增加第二层，要求 assets 继承。

## 8. 验证矩阵

### Case A：接手旧游戏，保留资源

输入：

```text
只读源项目在：output/sandbox_runs/.../arcane_dungeon_studio/
目标输出目录：frontend/public/games/arcane_dungeon_studio/
保留现有玩法和 SVG 资产引用，增加第二层
```

必须满足：

- 读取源 `index.html/styles.css/game.js/README.md/assets/`。
- 写入目标 `index.html/styles.css/game.js/README.md/assets/`。
- `assets/*.svg` 真实存在。
- `game.js` 引用的 assets 都存在。
- `RunOutcome.completed=true`。

### Case B：从零创建游戏并生成资源

必须满足：

- 不要求 source assets。
- 必须生成或写入目标 assets。
- 引用和真实文件一致。

### Case C：只读审查旧项目

必须满足：

- 不产生 required_writes。
- assets 可作为 material dir。
- 不触发写入门禁。

### Case D：源码引用缺失资产

必须满足：

- `visual_asset_refs` 不通过。
- 返回 `missing_assets`。
- 如果工具预算仍有余量，进入 resubmission。

## 9. 禁止事项

1. 禁止继续让正则直接生成 hard `required_reads/required_writes`。
2. 禁止用裸文件名满足材料读取义务。
3. 禁止把 `assets/*.svg` 字符串引用当成资产存在证据。
4. 禁止后端替模型猜“专业游戏模板需要哪些资产”并静默写入契约。
5. 禁止为了通过测试伪造产物或伪造浏览器验证。
6. 禁止保留旧 fallback 自动写文件来掩盖模型未完成任务。

## 10. Cutover 规则

### Shadow 阶段

- 正则候选仍可写入 diagnostics。
- hard obligation 只消费 `resource_contract` 和显式 API 参数。
- 对比日志记录：

```text
regex_candidates
model_resource_contract
compiled_execution_obligation
```

### Cutover 阶段

- `_PATH_RE` 不再影响 required reads/writes。
- `visual_asset_refs` 切到真实文件验收。
- long_runner 只看 `RunOutcome.completed`。

### Rollback 原则

不回滚到正则硬抽取。若模型 `resource_contract` 缺失，应：

1. 要求模型补交资源契约。
2. 或进入澄清/blocked。
3. 不允许程序用正则自行补 hard obligation。

## 11. 最终验收定义

完成本计划后，以下全部为真：

1. 接手旧项目时，源目录和目标目录角色不会混淆。
2. `required_reads` 不出现裸文件名和自然语言脏片段。
3. `assets/` 可作为目录材料和目录产物。
4. 引用的 asset 文件必须真实存在。
5. 缺 asset 会触发修复循环，而不是假通过。
6. `RunOutcome.completed` 与真实 evidence 一致。
7. 正则只提供候选，不再拥有理解权。

