# File Review: model_profile_models

- file_ref: `file://backend/agent_system/models/model_profile_models.py`
- file_path: `backend/agent_system/models/model_profile_models.py`
- file_hash: `618639ea7287779d291c8f8322a705242139ffc10ccc7cd2bee8b44f7e875c4a`
- physical_status: resolved
- confidence: exact

## Semantic Coordinate

- summary: Agent model profile data models and parsing functions: AgentModelProfile, ModelRequirement, ResolvedModelSpec, and associated parsers, sanitizers, and secret detection.
- control_role: data_model_definition
- tags: agent_system, models, profile, data_model, parser, sanitizer

## IO Surface

- exposed_entry_points: ["parse_agent_model_profile(value: Any) -> AgentModelProfile", "parse_model_requirement(value: Any) -> ModelRequirement", "sanitize_model_profile_payload(value: Any) -> dict[str, Any]", "contains_raw_secret(value: Any) -> bool", "AgentMo...
- internal_helpers: ["_optional_int", "_optional_float", "_optional_bool", "_dict_or_empty", "_unique_texts", "_is_sensitive_key"]
- output_types: ["AgentModelProfile", "ModelRequirement", "ResolvedModelSpec", "dict[str, Any]", "bool"]

## Control Nodes

- `file://backend/agent_system/models/model_profile_models.py` [file_module] [resolved/workspace_file] model_profile_models
- `pyast://backend/agent_system/models/model_profile_models.py#class:AgentModelProfile` [py_class] [resolved/workspace_file_anchor] AgentModelProfile
- `pyast://backend/agent_system/models/model_profile_models.py#class:ModelRequirement` [py_class] [resolved/workspace_file_anchor] ModelRequirement
- `pyast://backend/agent_system/models/model_profile_models.py#class:ResolvedModelSpec` [py_class] [resolved/workspace_file_anchor] ResolvedModelSpec
- `pyast://backend/agent_system/models/model_profile_models.py#py_function:parse_agent_model_profile` [py_function] [resolved/workspace_file_anchor] parse_agent_model_profile
- `pyast://backend/agent_system/models/model_profile_models.py#py_function:parse_model_requirement` [py_function] [resolved/workspace_file_anchor] parse_model_requirement
- `pyast://backend/agent_system/models/model_profile_models.py#py_function:sanitize_model_profile_payload` [py_function] [resolved/workspace_file_anchor] sanitize_model_profile_payload
- `pyast://backend/agent_system/models/model_profile_models.py#py_function:contains_raw_secret` [py_function] [resolved/workspace_file_anchor] contains_raw_secret
- `pyast://backend/agent_system/models/model_profile_models.py#py_function:_is_sensitive_key` [py_function] [resolved/workspace_file_anchor] _is_sensitive_key
- `pyast://backend/agent_system/models/model_profile_models.py#py_function:_optional_int` [py_function] [resolved/workspace_file_anchor] _optional_int
- `pyast://backend/agent_system/models/model_profile_models.py#py_function:_optional_float` [py_function] [resolved/workspace_file_anchor] _optional_float
- `pyast://backend/agent_system/models/model_profile_models.py#py_function:_optional_bool` [py_function] [resolved/workspace_file_anchor] _optional_bool
- `pyast://backend/agent_system/models/model_profile_models.py#py_function:_dict_or_empty` [py_function] [resolved/workspace_file_anchor] _dict_or_empty
- `pyast://backend/agent_system/models/model_profile_models.py#py_function:_unique_texts` [py_function] [resolved/workspace_file_anchor] _unique_texts
- `pyast://backend/agent_system/models/model_profile_models.py#py_method:AgentModelProfile.to_dict` [py_method] [resolved/workspace_file_anchor] AgentModelProfile.to_dict
- `pyast://backend/agent_system/models/model_profile_models.py#py_method:ModelRequirement.to_dict` [py_method] [resolved/workspace_file_anchor] ModelRequirement.to_dict
- `pyast://backend/agent_system/models/model_profile_models.py#py_method:ResolvedModelSpec.to_public_dict` [py_method] [resolved/workspace_file_anchor] ResolvedModelSpec.to_public_dict

## Signal Edges

- `file://backend/agent_system/models/model_profile_models.py` -> `pyast://backend/agent_system/models/model_profile_models.py#module` via `defines_module` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_models.py#module` -> `pyast://backend/agent_system/models/model_profile_models.py#class:AgentModelProfile` via `defines_class` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_models.py#module` -> `pyast://backend/agent_system/models/model_profile_models.py#class:ModelRequirement` via `defines_class` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_models.py#module` -> `pyast://backend/agent_system/models/model_profile_models.py#class:ResolvedModelSpec` via `defines_class` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_models.py#module` -> `pyast://backend/agent_system/models/model_profile_models.py#py_function:_dict_or_empty` via `defines_function` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_models.py#module` -> `pyast://backend/agent_system/models/model_profile_models.py#py_function:_is_sensitive_key` via `defines_function` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_models.py#module` -> `pyast://backend/agent_system/models/model_profile_models.py#py_function:_optional_bool` via `defines_function` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_models.py#module` -> `pyast://backend/agent_system/models/model_profile_models.py#py_function:_optional_float` via `defines_function` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_models.py#module` -> `pyast://backend/agent_system/models/model_profile_models.py#py_function:_optional_int` via `defines_function` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_models.py#module` -> `pyast://backend/agent_system/models/model_profile_models.py#py_function:_unique_texts` via `defines_function` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_models.py#module` -> `pyast://backend/agent_system/models/model_profile_models.py#py_function:contains_raw_secret` via `defines_function` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_models.py#module` -> `pyast://backend/agent_system/models/model_profile_models.py#py_function:parse_agent_model_profile` via `defines_function` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_models.py#module` -> `pyast://backend/agent_system/models/model_profile_models.py#py_function:parse_model_requirement` via `defines_function` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_models.py#module` -> `pyast://backend/agent_system/models/model_profile_models.py#py_function:sanitize_model_profile_payload` via `defines_function` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_models.py#class:AgentModelProfile` -> `pyast://backend/agent_system/models/model_profile_models.py#py_method:AgentModelProfile.to_dict` via `defines_method` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_models.py#class:ModelRequirement` -> `pyast://backend/agent_system/models/model_profile_models.py#py_method:ModelRequirement.to_dict` via `defines_method` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_models.py#class:ResolvedModelSpec` -> `pyast://backend/agent_system/models/model_profile_models.py#py_method:ResolvedModelSpec.to_public_dict` via `defines_method` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_models.py#py_function:parse_model_requirement` -> `pyast://backend/agent_system/models/model_profile_models.py#py_function:_optional_int` via `calls` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_models.py#py_function:parse_model_requirement` -> `pyast://backend/agent_system/models/model_profile_models.py#py_function:_optional_float` via `calls` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_models.py#py_function:parse_model_requirement` -> `pyast://backend/agent_system/models/model_profile_models.py#py_function:_optional_bool` via `calls` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_models.py#py_function:parse_model_requirement` -> `pyast://backend/agent_system/models/model_profile_models.py#py_function:_dict_or_empty` via `calls` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_models.py#py_function:parse_model_requirement` -> `pyast://backend/agent_system/models/model_profile_models.py#py_function:sanitize_model_profile_payload` via `calls` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_models.py#py_function:parse_model_requirement` -> `pyast://backend/agent_system/models/model_profile_models.py#py_function:_unique_texts` via `calls` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_models.py#py_function:parse_model_requirement` -> `pyast://backend/agent_system/models/model_profile_models.py#class:ModelRequirement` via `calls` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_models.py#py_function:parse_agent_model_profile` -> `pyast://backend/agent_system/models/model_profile_models.py#py_function:_optional_int` via `calls` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_models.py#py_function:parse_agent_model_profile` -> `pyast://backend/agent_system/models/model_profile_models.py#py_function:_optional_float` via `calls` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_models.py#py_function:parse_agent_model_profile` -> `pyast://backend/agent_system/models/model_profile_models.py#class:AgentModelProfile` via `calls` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_models.py#py_function:parse_agent_model_profile` -> `pyast://backend/agent_system/models/model_profile_models.py#py_function:_dict_or_empty` via `calls` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_models.py#py_function:parse_agent_model_profile` -> `pyast://backend/agent_system/models/model_profile_models.py#py_function:sanitize_model_profile_payload` via `calls` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_models.py#py_function:parse_agent_model_profile` -> `pyast://backend/agent_system/models/model_profile_models.py#py_function:_unique_texts` via `calls` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_models.py#py_method:AgentModelProfile.to_dict` -> `pyast://backend/agent_system/models/model_profile_models.py#py_function:sanitize_model_profile_payload` via `calls` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_models.py#py_function:contains_raw_secret` -> `pyast://backend/agent_system/models/model_profile_models.py#py_function:_is_sensitive_key` via `calls` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_models.py#py_function:sanitize_model_profile_payload` -> `pyast://backend/agent_system/models/model_profile_models.py#py_function:_is_sensitive_key` via `calls` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_models.py#module` -> `None` via `imports_text` [candidate; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_models.py#module` -> `None` via `imports_text` [candidate; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_models.py#module` -> `None` via `imports_text` [candidate; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_models.py#module` -> `None` via `imports_text` [candidate; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_models.py#module` -> `None` via `imports_text` [candidate; evidence=1; anchors=1]

## Limitations

- Interprocedural dataflow not computed.
- All calls edges derived from local AST text match only; no cross-module call verification.
- Import edges unresolved; target modules not in scope.
- Dynamic imports and runtime dispatch not analyzed.
