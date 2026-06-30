# Provider Cache Prefix Health Authority Cleanup

创建日期：2026-06-30

状态：已实施，待固定端口运行复核。

## 1. 目标

本片清理缓存健康裁决的旧口径，尤其是：

```text
cached_tokens > 0 -> warm
```

这个判断不能证明前缀命中。目标口径是：

```text
ProviderCacheBus.summary.current_prefix_covered == true
latest_under_read_tokens == 0
latest_prefix_health.verdict == covered
```

总 hit rate、cached tokens、cache_read_tokens 只能作为观测字段，不再拥有 warm/cold 裁决权。

## 2. 当前权威链

```text
ProviderPayloadManifest
-> prefix_cache_health.evaluate_prefix_cache_health()
-> ProviderCacheBusRecord
-> ProviderCacheBus.build_provider_cache_log_view()
-> API/frontend/microcompact cache state
```

`ProviderCacheBus` 是展示与消费入口，`prefix_cache_health` 是算法权威。`app_runtime` 和 `microcompact` 只能读取裁决结果，不能重新用总命中率推断健康。

## 3. 本片文件

| 文件 | 动作 |
| --- | --- |
| `backend/runtime/prompt_accounting/provider_cache_bus.py` | `current_prefix_covered` 收紧为 `latest_prefix_health.verdict == covered` 且 `latest_under_read_tokens <= 0` |
| `backend/bootstrap/app_runtime.py` | `_microcompact_cache_state()` 改读 `build_provider_cache_log_view()` |
| `backend/context_system/compaction/microcompact.py` | `_cache_temperature()` 改为 prefix coverage / under-read 优先 |
| `backend/runtime/context_management/design_docs/README.md` | 挂入本文档索引 |
| `backend/runtime/context_management/design_docs/execution_plans/agent_control_network_runtime_topology_projection_implementation_20260630.md` | 更新 P1 状态 |
| `frontend/src/app/agent-network/page.tsx` | prefix false 明确显示为 not covered，不再被 `||` 折叠成 unscoped |

## 4. 行为契约

### warm

只在当前 expected prefix 被完整覆盖时返回：

```text
current_prefix_covered == true
latest_under_read_tokens <= 0
latest_prefix_health.verdict == covered
```

### cold

以下情况必须视为 cold 或可重写：

```text
provider_under_read
local_physical_mismatch
cold_start
miss
latest_under_read_tokens > 0
latest_prefix_health.verdict == provider_under_read
```

### unknown

没有 ProviderCacheBus 记录、没有 prefix health、没有可用 ledger 时返回 unknown，不能用 cached tokens 猜 warm。

## 5. 不变量

1. `cached_tokens` 不再作为 warm 裁决条件。
2. `hit_rate` 不再作为 warm 裁决条件。
3. `cache_temperature` 的 source 必须能回到 `ProviderCacheBus` 或明确 external input。
4. `microcompact` 只依据 cache_state 做 local rewrite 允许/阻断，不写 provider cache bus record。
5. 本片不触碰 graph task system。

## 6. 实施记录

2026-06-30 已完成：

- `ProviderCacheBus.summary.current_prefix_covered` 不再接受 `latest_status == hit` 作为覆盖证明。
- `app_runtime._microcompact_cache_state()` 只在 `current_prefix_covered == true`、`latest_under_read_tokens <= 0`、`latest_prefix_health.verdict == covered` 时返回 warm。
- `microcompact._cache_temperature()` 删除 `status == hit or cached_tokens > 0 -> warm`，`cached_tokens/hit_rate` 仅保留在 diagnostics。
- `/agent-network` 的 prefix 状态明确区分 `covered`、`not covered` 和 `unscoped`。

保留说明：

- `cache_anomaly_detector.py` 中的 `cached_tokens > 0` 只用于避免把 provider 已报告缓存读取的记录误报为 “reported miss” anomaly，不参与 warm/cold 健康裁决。

## 7. 验证

```powershell
python -m py_compile backend/runtime/prompt_accounting/provider_cache_bus.py backend/bootstrap/app_runtime.py backend/context_system/compaction/microcompact.py
rg -n "cached_tokens\\s*>\\s*0|status == \"hit\" or cached_tokens|latest_status == \"hit\"" backend/bootstrap backend/context_system backend/runtime/prompt_accounting/provider_cache_bus.py
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8003/api/agent-control-network
```
