# Provider Visible Append Ledger Storage/API Migration Plan

创建日期：2026-06-30

状态：已确认，已实施（2026-06-30）。

本文是 `provider_visible_context_ledger` -> `provider_visible_append_ledger` 的专门迁移计划。它不是普通命名清理，而是 active runtime storage、metadata、API rollback、context commit record、physical prefix frame 对接的一次 clean cutover。

## 1. 目标

把当前名为 `provider_visible_context_ledger` 的模块和契约收口为 `provider_visible_append_ledger`。

原因：

- 该 ledger 只记录 current append candidates 经 provider success 后的确认状态。
- 它不拥有下一轮 replay 顺序权威。
- 下一轮 provider-visible replay 的唯一物理权威是 `physical_prefix_frame_ledger` 和 `physical_context_assembler`。
- `context` 这个词太宽，会让后续维护者误以为该 ledger 是所有 provider-visible context 的源事实。

目标读法：

```text
context_pipeline
-> provider_visible_append_ledger current append candidates
-> provider success confirmation
-> physical_prefix_frame promotion
-> physical_context_assembler replay
```

## 2. 非目标

本计划不做以下事情：

- 不改变 provider payload 的实际消息顺序。
- 不改变 cache / prefix / physical lane 决策算法。
- 不把 append ledger 改成 replay owner。
- 不迁移历史对话正文、archive 文档和旧审计文本里的历史事实。
- 不增加长期 compatibility alias、双写、双读 fallback。
- 不新增回归测试文件。

保留的名称：

| 名称 | 保留原因 |
| --- | --- |
| `provider_visible_context_prefix` | 这是 physical prefix lane，描述 replay 后的位置，不是 append ledger 名称 |
| `provider_visible_hash` | 描述 provider-visible payload hash，非 ledger 专属 |
| `provider_visible_payload_form` | 描述 provider transport 形态，非 ledger 专属 |
| `context_append` | 语义 section 名，仍表示 current turn append 生命周期 |
| `context_memory_prefix` | 语义 section 名，仍表示 confirmed replay prefix |

## 3. Source Audit

### 3.1 Current Runtime Flow

| 阶段 | 当前文件 | 当前职责 | 目标职责 |
| --- | --- | --- | --- |
| capability/policy 筛选 | `backend/runtime/context_management/context_pipeline.py` | 根据 `context_segment_policy` 选出可 seal 的 provider-visible append candidates | 保持；入参/diagnostics 改为 append scope |
| append candidate 记录 | `backend/runtime/context_management/provider_visible_context_ledger.py` | 为 current append 加 metadata、去重、等待 provider success | 改名为 `provider_visible_append_ledger.py` |
| provider success 确认 | `confirm_provider_visible_context_entries()` | provider success 后追加 confirmed entries 和 success anchor | 改名为 `confirm_provider_visible_append_entries()` |
| commit candidate 提取 | `backend/runtime/context_management/context_candidates.py` | 从 provider payload segment metadata 提取 commit candidate | 读取 `provider_visible_append_ledger_*` metadata |
| request commit record | `backend/runtime/context_management/context_commit_record.py` | 记录 provider request 前后 anchor | 字段从 `provider_visible_ledger_anchor*` 收口为 `provider_visible_append_anchor*` |
| accounting -> commit | `backend/runtime/model_gateway/model_runtime.py` | 成功/失败时生成 context commit record、确认 append candidates | import/function/metadata key 同步改名 |
| physical frame promotion | `backend/runtime/context_management/physical_prefix_frame_ledger.py` | provider success 后把 confirmed current append 提升进 physical frame | 读取新 metadata key；保留 physical lane |
| physical replay assembly | `backend/runtime/context_management/physical_context_assembler.py` | 按 static prefix -> physical frame -> current append -> dynamic tail 拼接 | 读取新 commit stage key；不从 append ledger replay |
| tool protocol grouping | `backend/runtime/context_management/provider_tool_protocol.py` | 用 append entry index 对 tool rounds 做排序/定位 | entry key 改名，不改 protocol 语义 |
| session truncate rollback | `backend/api/sessions.py` | edit/resend 后移动 active append cursor | API helper 改为 append ledger rollback |
| topology/inspection | `backend/harness/runtime/context_contract/inspection_payload.py` | 展示 ProviderVisibleAppendLedger 节点 | 路径和 authority 改为 append ledger |

### 3.2 Storage Audit

迁移前 active storage 状态：

- `storage/runtime_state/provider_visible_context_ledger/*.json` 存在 428 个 active ledger 文件。
- `storage/runtime_state/provider_visible_append_ledger/` 当前不存在。
- `storage/runtime_state` 里至少 1469 个 JSON 含旧 metadata / authority / anchor 名称。

因此，不能只改 active code。必须一次性迁移 active runtime_state 中的结构化 JSON，否则新代码会读不到旧 physical frame 和 context commit record。

实施结果：

- active code 已 clean cutover 到 `provider_visible_append_ledger`，未保留旧 module/function alias。
- `storage/runtime_state/provider_visible_context_ledger` 已移动为 `storage/runtime_state/provider_visible_append_ledger`，迁移后新目录保留 428 个 ledger JSON。
- active runtime_state 结构化迁移分三轮完成：1459 个 JSON 的 key/受控 authority/schema/status 字符串迁移，252 个 JSON 的补充受控 authority 值迁移，33 个 JSON 的动态统计 key 迁移。
- 迁移只改结构化 key 和受控诊断/authority/schema 字符串；不改 `provider_visible_message.content` 等封存正文，避免破坏 provider-visible hash 和历史 provider 输入事实。

## 4. Authority Map

| 模块 | 当前角色 | 隐含风险 | 目标动作 |
| --- | --- | --- | --- |
| `provider_visible_context_ledger.py` | record current append confirmation | 名字暗示 provider-visible context 总账/replay owner | 文件、函数、metadata、authority 全部改为 append ledger |
| `context_pipeline.py` | decide routing between append/tail/prefix | 参数名 `provider_visible_context_scope` 过宽 | 改为 `provider_visible_append_scope` |
| `context_candidates.py` | normalize commit candidates | 旧 metadata key 会成为事实入口 | 只读新 `provider_visible_append_ledger_*` |
| `physical_prefix_frame_ledger.py` | promote confirmed append into replay frame | 若只改 ledger，不迁移 frame metadata，会断 replay | 读取/写入新 key；active storage 同步迁移 |
| `physical_context_assembler.py` | assemble final physical provider order | 不能从 append ledger 读取 replay | 只识别新 current append stage；继续从 physical frame replay |
| `model_runtime.py` | provider request success boundary | success confirmation import/function 旧名 | 同步改名；context commit record 字段改为 append anchor |
| `api/sessions.py` | truncate rollback coordinator | API 名称把 append cursor 叫 context ledger | helper/API diagnostics 改为 append rollback |
| `inspection_payload.py` | present topology | 节点 label 已正确，path/authority 旧 | path/authority 改名 |

## 5. Target Naming Map

### 5.1 Module / Function

| 当前名 | 目标名 |
| --- | --- |
| `provider_visible_context_ledger.py` | `provider_visible_append_ledger.py` |
| `PROVIDER_VISIBLE_CONTEXT_LEDGER_SCHEMA_REVISION` | `PROVIDER_VISIBLE_APPEND_LEDGER_SCHEMA_REVISION` |
| `PROVIDER_VISIBLE_CONTEXT_LEDGER_ADAPTER_CONTRACT` | `PROVIDER_VISIBLE_APPEND_LEDGER_ADAPTER_CONTRACT` |
| `PROVIDER_VISIBLE_CONTEXT_LEDGER_CONFIRMED_STATUS` | `PROVIDER_VISIBLE_APPEND_CONFIRMED_STATUS` |
| `assemble_provider_visible_context_specs()` | `assemble_provider_visible_append_specs()` |
| `provider_visible_context_append_candidate_spec()` | `provider_visible_append_candidate_spec()` |
| `confirm_provider_visible_context_entries()` | `confirm_provider_visible_append_entries()` |
| `latest_provider_visible_context_success_anchor()` | `latest_provider_visible_append_success_anchor()` |
| `truncate_provider_visible_context_ledger_after_session_cutoff()` | `truncate_provider_visible_append_ledger_after_session_cutoff()` |
| `load_provider_visible_context_ledger()` | `load_provider_visible_append_ledger()` |
| `save_provider_visible_context_ledger()` | `save_provider_visible_append_ledger()` |
| `provider_visible_context_ledger_path()` | `provider_visible_append_ledger_path()` |
| `safe_provider_visible_context_ledger_filename()` | `safe_provider_visible_append_ledger_filename()` |

禁止保留旧函数 alias。

### 5.2 Runtime Metadata

| 当前 key/value | 目标 key/value |
| --- | --- |
| `provider_visible_context_ledger_scope` | `provider_visible_append_ledger_scope` |
| `provider_visible_context_ledger_storage_root` | `provider_visible_append_ledger_storage_root` |
| `provider_visible_context_ledger_commit_stage` | `provider_visible_append_commit_stage` |
| `provider_visible_context_ledger_item_key` | `provider_visible_append_item_key` |
| `provider_visible_context_ledger_entry_index` | `provider_visible_append_entry_index` |
| `provider_visible_context_ledger_authority` | `provider_visible_append_ledger_authority` |
| `provider_visible_context_candidate_message` | `provider_visible_append_candidate_message` |
| `provider_visible_context_candidate_kind` | `provider_visible_append_candidate_kind` |
| `provider_visible_context_candidate_source_ref` | `provider_visible_append_candidate_source_ref` |
| `provider_visible_context_candidate_semantic_commit_class` | `provider_visible_append_candidate_semantic_commit_class` |
| `provider_visible_context_candidate_provider` | `provider_visible_append_candidate_provider` |
| `provider_visible_context_candidate_model` | `provider_visible_append_candidate_model` |
| `runtime.context_management.provider_visible_context_ledger` | `runtime.context_management.provider_visible_append_ledger` |
| `runtime.context_management.provider_visible_context_ledger.current_append` | `runtime.context_management.provider_visible_append_ledger.current_append` |
| `runtime.context_management.provider_visible_context_ledger.provider_success_anchor` | `runtime.context_management.provider_visible_append_ledger.provider_success_anchor` |

### 5.3 Scope / Anchor Fields

| 当前字段 | 目标字段 |
| --- | --- |
| `provider_visible_context_scope` | `provider_visible_append_scope` |
| `fork_point_provider_visible_ledger_anchor` | `fork_point_provider_visible_append_anchor` |
| `provider_visible_ledger_anchor` | `provider_visible_append_anchor` |
| `provider_visible_ledger_anchor_before` | `provider_visible_append_anchor_before` |
| `provider_visible_ledger_confirmation` | `provider_visible_append_confirmation` |
| `provider_visible_ledger_anchor_after` | `provider_visible_append_anchor_after` |

### 5.4 Storage

| 当前路径 | 目标路径 |
| --- | --- |
| `storage/runtime_state/provider_visible_context_ledger/*.json` | `storage/runtime_state/provider_visible_append_ledger/*.json` |

旧目录在迁移成功后删除，不保留 active fallback。

## 6. Implementation Plan

### Phase A: Code Symbol Cutover

动作：

1. 移动文件 `provider_visible_context_ledger.py` -> `provider_visible_append_ledger.py`。
2. 改 module constants / functions / private helper names。
3. 更新 imports 和 `runtime/context_management/__init__.py` exports。
4. 更新 `context_pipeline.py`、`single_agent_turn.py`、`model_runtime.py`、`api/sessions.py` 调用点。
5. 更新 topology/inspection/manifest/authority_rules 中的 path 和 authority。

完成标准：

- active backend code 不再 import `runtime.context_management.provider_visible_context_ledger`。
- active backend code 不再调用 `provider_visible_context_append_candidate_spec()` 等旧函数。
- 不保留旧文件和旧 alias。

### Phase B: Metadata Cutover

动作：

1. `_current_append_spec_from_candidate()` 写入新 metadata keys。
2. `ContextCommitCandidate.from_provider_payload_segment()` 只读取新 metadata keys。
3. `physical_prefix_frame_ledger.py` 读取/写入新 entry/item/stage/candidate keys。
4. `physical_context_assembler.py` 使用 `provider_visible_append_commit_stage` 判断 current append / replay。
5. `provider_tool_protocol.py` 改用 `provider_visible_append_entry_index`。
6. follow-up segment plan metadata copy 从 `provider_visible_context_ledger_` 前缀改为新 key 白名单。

完成标准：

- active code 不再写入 `provider_visible_context_ledger_*`。
- active code 不再读取旧 metadata key。
- `provider_visible_context_prefix` 仍保留，因为它是 physical lane。

### Phase C: Storage Migration

动作：

1. 对 `storage/runtime_state` 下结构化 JSON 做一次性迁移：
   - key rename；
   - authority string rename；
   - schema string rename；
   - error code / reason 中属于 active contract 的 rename；
   - anchor field rename。
2. 移动目录：
   - `provider_visible_context_ledger` -> `provider_visible_append_ledger`。
3. 迁移只覆盖 active runtime_state；不改 `storage/runtime_archive`、`storage/sessions` 中的历史对话正文。
4. 迁移后 active runtime 不读旧路径、不读旧 keys。

完成标准：

- `storage/runtime_state/provider_visible_context_ledger` 不存在。
- `storage/runtime_state/provider_visible_append_ledger` 存在且文件数量等于迁移前旧目录数量。
- active runtime_state 中旧 key 搜索清零，允许历史 archive/session 仍保留旧文本。

### Phase D: Plan / Docs / Diagnostics

动作：

1. 更新主命名计划，标记本专门计划。
2. 更新 context design docs 中直接描述 active contract 的段落。
3. 不批量修改历史审计报告和对话记录。

完成标准：

- active docs 不再把 append ledger 叫 provider-visible context ledger。
- 历史问题记录可保留旧名，但需要能读出它是历史名。

## 7. Verification

不新增测试文件。执行以下真实验证：

```powershell
python -m py_compile `
  backend\runtime\context_management\provider_visible_append_ledger.py `
  backend\runtime\context_management\context_candidates.py `
  backend\runtime\context_management\context_pipeline.py `
  backend\runtime\context_management\physical_context_assembler.py `
  backend\runtime\context_management\physical_prefix_frame_ledger.py `
  backend\runtime\model_gateway\model_runtime.py `
  backend\harness\loop\single_agent_turn.py `
  backend\api\sessions.py
```

```powershell
rg -n "provider_visible_context_ledger|provider_visible_context_append|provider_visible_context_scope|provider_visible_ledger_anchor|fork_point_provider_visible_ledger_anchor" `
  backend/runtime backend/harness backend/api frontend/src `
  --glob "*.py" --glob "*.ts" --glob "*.tsx"
```

对 `storage/runtime_state` 使用结构化 JSON 审计，而不是裸文本 `rg`：

- key 名不得包含 `provider_visible_context_ledger` / `provider_visible_context_append` / `provider_visible_context_scope` / `provider_visible_ledger_anchor` / `fork_point_provider_visible_ledger_anchor` / `provider_visible_context_candidate`。
- 受控字符串字段（`authority`、`schema`、`code`、`reason`、`cache_impact`、`content_source`、`path` 等）不得包含旧 contract 名。
- `provider_visible_message.content`、工具观察正文和历史模型输出正文不做字符串替换；这些是已经封存的 provider-visible 内容，不能为了命名迁移破坏 hash chain。

```powershell
git diff --check -- `
  backend\runtime\context_management `
  backend\runtime\model_gateway `
  backend\harness `
  backend\api `
  backend\runtime\context_management\design_docs
```

另外做一个真实 inline construction：

1. 构造一个 `context_append` message spec。
2. 经 `assemble_provider_visible_append_specs()` 生成 current append candidate。
3. 构造 `ProviderRequestPacket` 和 provider payload manifest。
4. 从 manifest segment 提取 `ContextCommitCandidate`。
5. 调用 `confirm_provider_visible_append_entries()` 写入 append ledger。
6. 调用 physical frame promotion，确认 `physical_context_assembler` 下一轮从 physical frame replay，而不是从 append ledger replay。

## 8. Risk Controls

| 风险 | 控制 |
| --- | --- |
| 新代码读不到旧 frame metadata | Phase C 同步迁移 active runtime_state 的 physical frame JSON |
| 误删 historical audit facts | 迁移限定 `storage/runtime_state`，不改 archive/session 正文 |
| append ledger 越权 replay | `physical_context_assembler` 继续只从 physical prefix frame replay |
| 保留旧 alias 造成双权威 | 禁止 alias、禁止双读、禁止双写 |
| 广泛搜索误伤 `provider_visible_context_prefix` | 明确保留该 physical lane 名 |
| 迁移中断造成半迁移 | 先 dry-run 统计，再执行；执行后以 rg 和目录数量验证 |

## 9. Go / No-Go

开始实施前需要确认：

- 接受 `provider_visible_append_ledger` 作为目标名。
- 接受 active runtime_state 一次性迁移，不保留 runtime fallback。
- 接受不迁移 archive/session 历史文本。
- 接受本切片不改物理缓存算法，只改命名和存储/API contract。
