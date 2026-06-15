# Prompt 链路修复计划（链路稳固版）

## 目标

修复新对话中暴露的三条链路问题，确保 prompt 装配、证据分层和工具选择都按成熟 agent 的单一权威链运行，不再出现 cache 顺序错位、replay evidence 语义错层、已知目标仍先 search 的情况。

## 三条问题与根因

### 1. stable prefix 顺序错位

现象：最新 packet 的 prefix 顺序里，`file_evidence_policy_stable` 出现在两个 `task` 段之后，但它仍被标成 `session`，导致 `prefix_tier_order_regression` 和 cache_boundary warning。

根因：`backend/prompt_composition/manifest.py` 的层级策略允许 `file_evidence_policy_stable` 同时落在 `session/task`，但 compiler 实际组装里它被放在 `artifact_scope_stable`、`tool_index_stable`、`task_contract_stable` 之后，形成前缀错序。

### 2. task replay evidence 被当成 stable

现象：`task_state_replay_entry` 在 slot layer 被命名为 `task_state_replay_stable`，但实际载体是 `cache_scope=none/cache_role=volatile/prefix_tier=volatile`，于是 manifest 产生大量 layer violation。

根因：`backend/prompt_composition/runtime_slot_plan.py` 的 layer 命名和 `backend/prompt_composition/manifest.py` 的稳定层策略不一致。这里不是数据坏了，而是层级命名把 append-only evidence 伪装成 stable。

### 3. 已知 target_objects 仍先 search

现象：任务合同已经带了 `working_scope.target_objects=["fps_game.html"]`，但模型首轮仍先发 `search_files`。

根因：任务合同已经投影了目标文件，但 tool guidance / contract instruction 没有把“已知对象路径应先直接 `read_file` / `path_exists`，不要把 search 当默认定位动作”写成明确的稳定行为规则。

## 修复原则

- 只改权威源头，不在下游补丁式兜底。
- 不保留旧的错误层语义或 shadow 逻辑。
- 修复后要让 prefix 顺序、层语义、工具选择三者互相一致。
- 不改任务结果展示链路，不碰前端投影。

## 拟定修改

### A. 修复 stable prefix 顺序

文件：
- `backend/harness/runtime/compiler.py`
- `backend/prompt_composition/manifest.py`

动作：
- 调整 `single_agent_turn` / `task_execution` 的稳定段装配顺序，确保 `file_evidence_policy_stable` 与其它 session stable 段连续，不落在 task 段之后。
- 若 `file_evidence_policy_stable` 的内容仍需要放在 session stable，则保持它在所有 task 段之前。
- 维持 `artifact_scope_stable -> tool_index_stable -> file_evidence_policy_stable -> task_contract_stable` 的连续稳定区，不再穿插 task 段。

验收：
- `prompt_composition_manifest.diagnostics.cache_boundary.status == "ok"`。
- 不再出现 `prefix_tier_order_regression`。
- session / task / volatile 三段前缀连续。

### B. 修复 replay evidence 层语义

文件：
- `backend/prompt_composition/runtime_slot_plan.py`
- `backend/prompt_composition/manifest.py`
- 必要时补 `backend/prompt_composition/tracing.py`

动作：
- 将 `runtime_task_state_replay` 对应层从 `task_state_replay_stable` 改成 append-only evidence 语义层，避免它被解释成 stable prefix。
- 保留其 `prefix_tier=volatile`、`cache_role=volatile`、`dynamic_tier=append_only_task_evidence` 的事实，不再把它纳入稳定层策略。
- 同步 manifest 的 layer policy，让 replay evidence 不再参与 stable 级前缀/缓存断言。

验收：
- replay 仍可投影为可追踪证据，但不再触发 layer cache policy violation。
- `task_state_replay_entry` 在 diagnostics 中只保留 append-only evidence 语义。

### C. 强化已知目标路径的工具选择策略

文件：
- `backend/harness/runtime/task_contract_manifest.py`
- `backend/harness/runtime/compiler.py`
- `backend/harness/runtime/tool_catalog_manifest.py`
- 必要时 `backend/harness/runtime/section_renderer.py` / `prompt_composition` 相关渲染入口

动作：
- 让 `working_scope.target_objects` 不只是目标字段，而是可执行的路径语义输入。
- 在任务合同或工具指导中明确：当目标对象已知且表现为文件路径时，优先 `path_exists` / `read_file`，不要先用 `search_files` 重新发现。
- 保留 `search_files` 的用途，但只给未知路径或目录范围搜索，不把它写成已知路径的默认入口。

验收：
- 新任务在已知文件目标时，不再首轮无条件 search。
- `task_contract_stable` 的合同文本和工具 guidance 对“已知路径直读”一致。

## 不做的事

- 不重写前端投影。
- 不新增兼容旧层语义的 shadow 路由。
- 不把 replay evidence 继续伪装成 stable。
- 不靠测试假通过替代结构修复。

## 验证

1. 运行 prompt 组装冒烟，确认 latest packet 的 prefix 顺序和 cache_boundary 归零。
2. 复跑一个已知文件目标的任务，确认首个定位动作不再先走 `search_files`。
3. 复查 `task_state_replay_entry` 的 diagnostics，不再把 volatile evidence 判成 stable violation。
4. 更新 maintenance record，记录新 packet 的实测结果。
