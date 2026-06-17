# Artifact System

This package owns artifact identity, materialization records, repository indexes,
projection, and storage governance. It does not own task scheduling, graph
execution, model decisions, or cache deletion.

## Authority Chain

```text
ArtifactCandidate
-> ArtifactNamespacePolicy
-> ArtifactMaterializer / ArtifactRepositoryService
-> ArtifactRepositoryStore
-> ArtifactResolver / ArtifactAuthority projection
-> ArtifactGovernance
```

## Module Index

| Module | Role | Must Not Do |
| --- | --- | --- |
| `namespace_policy.py` | Classifies artifact namespaces, storage owners, durability classes, and retention tiers. | Copy files, create records, or delete data. |
| `materialization_receipts.py` | Defines durable receipts for artifact materialization events. | Decide artifact paths or verify files. |
| `artifact_repository_models.py` | Defines repository and artifact record data contracts. | Perform IO. |
| `artifact_repository_store.py` | Persists repositories, artifact records, and materialization receipts in SQLite. | Infer artifacts from runtime events. |
| `artifact_repository_service.py` | Records materializations, computes hashes, and writes repository records. | Treat model text or event refs as accepted artifacts without materialization. |
| `artifact_authority.py` | Resolves and projects existing artifact refs for API/model/UI consumers. | Create official artifact facts. |
| `governance.py` | Classifies artifact/runtime/cache roots for inventory and retention systems. | Delete project artifacts directly. |

## Artifact Classes

- `user_asset`: user-owned durable assets; never deleted by cache maintenance.
- `project_artifact`: accepted project output, such as graph task instance chapters; never treated as rebuildable cache.
- `runtime_artifact`: recoverable runtime output that may be summarized or cold-archived.
- `runtime_fact`: execution facts such as checkpoints, event logs, and accounting ledgers.
- `diagnostic_artifact`: logs, traces, screenshots, and legacy diagnostics with TTL.
- `rebuildable_cache`: sandbox/build/cache data that can be deleted by policy.

## Runtime Cache Integration

Cache maintenance must consume artifact classifications from `governance.py` and
runtime storage policy. It must not guess from path strings alone. In particular,
`storage/graph_task_instances/.../artifacts` is project artifact storage, not a
cache directory.

Related planning documents:

- `docs/系统架构/161-产物系统权威重整计划书-20260617.md`
- `docs/系统架构/160-运行数据缓存分级治理计划书-20260617.md`

Focused regression tests:

- `backend/tests/artifact_repository_scope_regression.py`
- `backend/tests/artifact_authority_regression.py`
- `backend/tests/artifact_governance_inventory_test.py`

## Current Migration Rule

Runtime events, task diagnostics, tool observations, and agent results may expose
candidate `artifact_refs`. They are not the final artifact authority. A reference
becomes an accepted artifact only after it is recorded through the repository
materialization path and receives a materialization receipt.
