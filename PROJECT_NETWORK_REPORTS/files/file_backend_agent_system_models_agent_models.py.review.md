# File Review: AgentModelsModule

- file_ref: `file://backend/agent_system/models/agent_models.py`
- file_path: `backend/agent_system/models/agent_models.py`
- file_hash: `251a60cfc91fb0f73da1c799de1a5fe5f13e591e14fff031d04fbc7128ac4695`
- physical_status: resolved
- confidence: exact

## Semantic Coordinate

- summary: Defines AgentDescriptor and AgentLifecycleRecord data classes for agent lifecycle management and governance.
- control_role: data_model
- tags: data_model, agent, agent_descriptor, lifecycle

## IO Surface

- inputs: [{"description": "Mapping from agent category to system slug.", "kind": "constant", "name": "AGENT_CATEGORY_TO_SYSTEM_SLUG"}, {"description": "Arbitrary metadata for AgentDescriptor.", "kind": "field", "name": "metadata dict"}]
- outputs: [{"description": "Immutable agent descriptor.", "kind": "class", "name": "AgentDescriptor"}, {"description": "Immutable lifecycle record.", "kind": "class", "name": "AgentLifecycleRecord"}]

## Control Nodes

- `file://backend/agent_system/models/agent_models.py` [file_module] [resolved/workspace_file] AgentModelsModule
- `pyast://backend/agent_system/models/agent_models.py#module` [py_module] [resolved/workspace_file_anchor] agent_models.py
- `pyast://backend/agent_system/models/agent_models.py#class:AgentDescriptor` [py_class] [resolved/workspace_file_anchor] AgentDescriptor
- `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.display_name` [py_method] [resolved/workspace_file_anchor] AgentDescriptor.display_name
- `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.profile_type` [py_method] [resolved/workspace_file_anchor] AgentDescriptor.profile_type
- `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.owner_system` [py_method] [resolved/workspace_file_anchor] AgentDescriptor.owner_system
- `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.builtin_kind` [py_method] [resolved/workspace_file_anchor] AgentDescriptor.builtin_kind
- `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.agent_template_id` [py_method] [resolved/workspace_file_anchor] AgentDescriptor.agent_template_id
- `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.subagent_enabled` [py_method] [resolved/workspace_file_anchor] AgentDescriptor.subagent_enabled
- `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.group_eligible` [py_method] [resolved/workspace_file_anchor] AgentDescriptor.group_eligible
- `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.lifecycle_state` [py_method] [resolved/workspace_file_anchor] AgentDescriptor.lifecycle_state
- `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.definition_source` [py_method] [resolved/workspace_file_anchor] AgentDescriptor.definition_source
- `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.lifecycle_policy` [py_method] [resolved/workspace_file_anchor] AgentDescriptor.lifecycle_policy
- `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.mutable_fields` [py_method] [resolved/workspace_file_anchor] AgentDescriptor.mutable_fields
- `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.governance_status` [py_method] [resolved/workspace_file_anchor] AgentDescriptor.governance_status
- `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.deletable` [py_method] [resolved/workspace_file_anchor] AgentDescriptor.deletable
- `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.disable_allowed` [py_method] [resolved/workspace_file_anchor] AgentDescriptor.disable_allowed
- `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.to_dict` [py_method] [resolved/workspace_file_anchor] AgentDescriptor.to_dict
- `pyast://backend/agent_system/models/agent_models.py#class:AgentLifecycleRecord` [py_class] [resolved/workspace_file_anchor] AgentLifecycleRecord
- `pyast://backend/agent_system/models/agent_models.py#py_method:AgentLifecycleRecord.to_dict` [py_method] [resolved/workspace_file_anchor] AgentLifecycleRecord.to_dict

## Signal Edges

- `file://backend/agent_system/models/agent_models.py` -> `pyast://backend/agent_system/models/agent_models.py#module` via `defines_module` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/agent_models.py#module` -> `pyast://backend/agent_system/models/agent_models.py#class:AgentDescriptor` via `defines_class` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/agent_models.py#module` -> `pyast://backend/agent_system/models/agent_models.py#class:AgentLifecycleRecord` via `defines_class` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/agent_models.py#class:AgentDescriptor` -> `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.display_name` via `defines_method` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/agent_models.py#class:AgentDescriptor` -> `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.profile_type` via `defines_method` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/agent_models.py#class:AgentDescriptor` -> `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.owner_system` via `defines_method` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/agent_models.py#class:AgentDescriptor` -> `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.builtin_kind` via `defines_method` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/agent_models.py#class:AgentDescriptor` -> `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.agent_template_id` via `defines_method` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/agent_models.py#class:AgentDescriptor` -> `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.subagent_enabled` via `defines_method` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/agent_models.py#class:AgentDescriptor` -> `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.group_eligible` via `defines_method` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/agent_models.py#class:AgentDescriptor` -> `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.lifecycle_state` via `defines_method` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/agent_models.py#class:AgentDescriptor` -> `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.definition_source` via `defines_method` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/agent_models.py#class:AgentDescriptor` -> `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.lifecycle_policy` via `defines_method` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/agent_models.py#class:AgentDescriptor` -> `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.mutable_fields` via `defines_method` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/agent_models.py#class:AgentDescriptor` -> `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.governance_status` via `defines_method` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/agent_models.py#class:AgentDescriptor` -> `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.deletable` via `defines_method` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/agent_models.py#class:AgentDescriptor` -> `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.disable_allowed` via `defines_method` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/agent_models.py#class:AgentDescriptor` -> `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.to_dict` via `defines_method` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/agent_models.py#class:AgentLifecycleRecord` -> `pyast://backend/agent_system/models/agent_models.py#py_method:AgentLifecycleRecord.to_dict` via `defines_method` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/agent_models.py#module` -> `None` via `imports` [candidate; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/agent_models.py#module` -> `None` via `imports` [candidate; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/agent_models.py#module` -> `None` via `imports` [candidate; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/agent_models.py#module` -> `None` via `imports` [candidate; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/agent_models.py#module` -> `None` via `imports` [candidate; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/agent_models.py#class:AgentDescriptor` -> `None` via `calls` [candidate; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/agent_models.py#class:AgentLifecycleRecord` -> `None` via `calls` [candidate; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.definition_source` -> `None` via `calls` [candidate; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.definition_source` -> `None` via `calls` [candidate; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.group_eligible` -> `None` via `calls` [candidate; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.group_eligible` -> `None` via `calls` [candidate; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.lifecycle_policy` -> `None` via `calls` [candidate; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.lifecycle_policy` -> `None` via `calls` [candidate; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.to_dict` -> `None` via `calls` [candidate; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.to_dict` -> `None` via `calls` [candidate; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/agent_models.py#py_method:AgentLifecycleRecord.to_dict` -> `None` via `calls` [candidate; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.subagent_enabled` -> `None` via `calls` [candidate; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.subagent_enabled` -> `None` via `calls` [candidate; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.owner_system` -> `None` via `calls` [candidate; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.owner_system` -> `None` via `calls` [candidate; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.owner_system` -> `None` via `calls` [candidate; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.builtin_kind` -> `None` via `calls` [candidate; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.builtin_kind` -> `None` via `calls` [candidate; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.builtin_kind` -> `None` via `calls` [candidate; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.builtin_kind` -> `None` via `calls` [candidate; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.agent_template_id` -> `None` via `calls` [candidate; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.agent_template_id` -> `None` via `calls` [candidate; evidence=1; anchors=1]

## Limitations

- Interprocedural dataflow not computed
- Unresolved import and call candidates remain evidence candidates, not accepted semantic links
- Dynamic imports or runtime dispatch not resolved
- External consumers and callers not identified
