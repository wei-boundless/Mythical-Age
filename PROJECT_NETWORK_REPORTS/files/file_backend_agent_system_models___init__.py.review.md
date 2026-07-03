# File Review: models package init

- file_ref: `file://backend/agent_system/models/__init__.py`
- file_path: `backend/agent_system/models/__init__.py`
- file_hash: `bc7d395f48cfce0a21b223f5622000625e932e9f980cf84260490ef9584564a1`
- physical_status: resolved
- confidence: exact

## Semantic Coordinate

- summary: Lazy-import facade for agent_system.models submodules
- control_role: entry_point
- tags: python, init, package, lazy_import, registry

## IO Surface

- exports: ["AgentDescriptor", "AgentLifecycleRecord", "AgentModelProfile", "ModelRequirement", "ResolvedModelSpec", "contains_raw_secret", "parse_agent_model_profile", "parse_model_requirement", "sanitize_model_profile_payload", "ModelProfileResol...
- imports_from_project: ["agent_system.models.agent_models", "agent_system.models.model_profile_models", "agent_system.models.model_profile_resolver"]
- imports_from_stdlib: ["__future__.annotations", "importlib.import_module"]

## Control Nodes

- `file://backend/agent_system/models/__init__.py` [file_module] [resolved/workspace_file] models package init
- `pyast://backend/agent_system/models/__init__.py#module` [py_module] [resolved/workspace_file_anchor] __init__.py module
- `pyast://backend/agent_system/models/__init__.py#py_function:__getattr__` [py_function] [resolved/workspace_file_anchor] __getattr__

## Signal Edges

- `file://backend/agent_system/models/__init__.py` -> `pyast://backend/agent_system/models/__init__.py#module` via `defines_module` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/__init__.py#module` -> `pyast://backend/agent_system/models/__init__.py#py_function:__getattr__` via `defines_function` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/__init__.py#module` -> `None` via `imports_text` [candidate; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/__init__.py#module` -> `None` via `imports_text` [candidate; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/__init__.py#module` -> `None` via `calls_text` [candidate; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/__init__.py#py_function:__getattr__` -> `None` via `calls_text` [candidate; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/__init__.py#py_function:__getattr__` -> `None` via `calls_text` [candidate; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/__init__.py#py_function:__getattr__` -> `None` via `calls_text` [candidate; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/__init__.py#py_function:__getattr__` -> `None` via `calls_text` [candidate; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/__init__.py#py_function:__getattr__` -> `None` via `calls_text` [candidate; evidence=1; anchors=1]

## Limitations

- Interprocedural dataflow not computed
- Dynamic import targets not resolved to specific modules
- Unresolved call/import candidates remain candidates
