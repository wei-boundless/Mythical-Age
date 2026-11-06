# Project Signal Chain Review

- build_id: `agent_system_models_control_network_ast_live_20260702_063038`
- generated_at: `2026-07-03T12:34:32.949658+00:00`
- chain_count: 38
- accepted_edges: 95
- candidate_edges: 17
- conflict_edges: 0
- audit_signals: 48

## Chains

### models package init

- source_ref: `file://backend/agent_system/models/__init__.py`
- outgoing_count: 1
- accepted_count: 1
- candidate_count: 0
- conflict_count: 0

- `defines_module` -> `pyast://backend/agent_system/models/__init__.py#module` [accepted]

### AgentModelsModule

- source_ref: `file://backend/agent_system/models/agent_models.py`
- outgoing_count: 1
- accepted_count: 1
- candidate_count: 0
- conflict_count: 0

- `defines_module` -> `pyast://backend/agent_system/models/agent_models.py#module` [accepted]

### model_profile_models

- source_ref: `file://backend/agent_system/models/model_profile_models.py`
- outgoing_count: 1
- accepted_count: 1
- candidate_count: 0
- conflict_count: 0

- `defines_module` -> `pyast://backend/agent_system/models/model_profile_models.py#module` [accepted]

### Model Profile Resolver Module

- source_ref: `file://backend/agent_system/models/model_profile_resolver.py`
- outgoing_count: 1
- accepted_count: 1
- candidate_count: 0
- conflict_count: 0

- `defines_module` -> `pyast://backend/agent_system/models/model_profile_resolver.py#module` [accepted]

### Workspace root

- source_ref: `folder://.`
- outgoing_count: 1
- accepted_count: 1
- candidate_count: 0
- conflict_count: 0

- `contains_directory` -> `folder://backend` [accepted]

### backend

- source_ref: `folder://backend`
- outgoing_count: 1
- accepted_count: 1
- candidate_count: 0
- conflict_count: 0

- `contains_directory` -> `folder://backend/agent_system` [accepted]

### backend/agent_system

- source_ref: `folder://backend/agent_system`
- outgoing_count: 1
- accepted_count: 1
- candidate_count: 0
- conflict_count: 0

- `contains_directory` -> `folder://backend/agent_system/models` [accepted]

### Agent System Models Directory

- source_ref: `folder://backend/agent_system/models`
- outgoing_count: 4
- accepted_count: 4
- candidate_count: 0
- conflict_count: 0

- `contains_file` -> `file://backend/agent_system/models/model_profile_resolver.py` [accepted]
- `contains_file` -> `file://backend/agent_system/models/model_profile_models.py` [accepted]
- `contains_file` -> `file://backend/agent_system/models/agent_models.py` [accepted]
- `contains_file` -> `file://backend/agent_system/models/__init__.py` [accepted]

### models init module

- source_ref: `pyast://backend/agent_system/models/__init__.py#module`
- outgoing_count: 3
- accepted_count: 1
- candidate_count: 2
- conflict_count: 0

- `defines_function` -> `pyast://backend/agent_system/models/__init__.py#py_function:__getattr__` [accepted]
- `imports_text` -> `None` [candidate]
- `calls_text` -> `None` [candidate]

### dynamic import router

- source_ref: `pyast://backend/agent_system/models/__init__.py#py_function:__getattr__`
- outgoing_count: 1
- accepted_count: 0
- candidate_count: 1
- conflict_count: 0

- `calls_text` -> `None` [candidate]

### AgentDescriptor

- source_ref: `pyast://backend/agent_system/models/agent_models.py#class:AgentDescriptor`
- outgoing_count: 16
- accepted_count: 15
- candidate_count: 1
- conflict_count: 0

- `defines_method` -> `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.display_name` [accepted]
- `defines_method` -> `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.profile_type` [accepted]
- `defines_method` -> `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.owner_system` [accepted]
- `defines_method` -> `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.builtin_kind` [accepted]
- `defines_method` -> `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.agent_template_id` [accepted]
- `defines_method` -> `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.subagent_enabled` [accepted]
- `defines_method` -> `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.group_eligible` [accepted]
- `defines_method` -> `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.lifecycle_state` [accepted]
- `defines_method` -> `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.definition_source` [accepted]
- `defines_method` -> `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.lifecycle_policy` [accepted]
- `defines_method` -> `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.mutable_fields` [accepted]
- `defines_method` -> `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.governance_status` [accepted]

### AgentLifecycleRecord

- source_ref: `pyast://backend/agent_system/models/agent_models.py#class:AgentLifecycleRecord`
- outgoing_count: 2
- accepted_count: 1
- candidate_count: 1
- conflict_count: 0

- `defines_method` -> `pyast://backend/agent_system/models/agent_models.py#py_method:AgentLifecycleRecord.to_dict` [accepted]
- `calls` -> `None` [candidate]

### AgentModelsModule

- source_ref: `pyast://backend/agent_system/models/agent_models.py#module`
- outgoing_count: 3
- accepted_count: 2
- candidate_count: 1
- conflict_count: 0

- `defines_class` -> `pyast://backend/agent_system/models/agent_models.py#class:AgentDescriptor` [accepted]
- `defines_class` -> `pyast://backend/agent_system/models/agent_models.py#class:AgentLifecycleRecord` [accepted]
- `imports` -> `None` [candidate]

### AgentDescriptor.agent_template_id

- source_ref: `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.agent_template_id`
- outgoing_count: 1
- accepted_count: 0
- candidate_count: 1
- conflict_count: 0

- `calls` -> `None` [candidate]

### AgentDescriptor.builtin_kind

- source_ref: `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.builtin_kind`
- outgoing_count: 1
- accepted_count: 0
- candidate_count: 1
- conflict_count: 0

- `calls` -> `None` [candidate]

### AgentDescriptor.definition_source

- source_ref: `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.definition_source`
- outgoing_count: 1
- accepted_count: 0
- candidate_count: 1
- conflict_count: 0

- `calls` -> `None` [candidate]

### AgentDescriptor.group_eligible

- source_ref: `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.group_eligible`
- outgoing_count: 1
- accepted_count: 0
- candidate_count: 1
- conflict_count: 0

- `calls` -> `None` [candidate]

### AgentDescriptor.lifecycle_policy

- source_ref: `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.lifecycle_policy`
- outgoing_count: 1
- accepted_count: 0
- candidate_count: 1
- conflict_count: 0

- `calls` -> `None` [candidate]

### AgentDescriptor.owner_system

- source_ref: `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.owner_system`
- outgoing_count: 1
- accepted_count: 0
- candidate_count: 1
- conflict_count: 0

- `calls` -> `None` [candidate]

### AgentDescriptor.subagent_enabled

- source_ref: `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.subagent_enabled`
- outgoing_count: 1
- accepted_count: 0
- candidate_count: 1
- conflict_count: 0

- `calls` -> `None` [candidate]

### AgentDescriptor.to_dict

- source_ref: `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.to_dict`
- outgoing_count: 1
- accepted_count: 0
- candidate_count: 1
- conflict_count: 0

- `calls` -> `None` [candidate]

### AgentLifecycleRecord.to_dict

- source_ref: `pyast://backend/agent_system/models/agent_models.py#py_method:AgentLifecycleRecord.to_dict`
- outgoing_count: 1
- accepted_count: 0
- candidate_count: 1
- conflict_count: 0

- `calls` -> `None` [candidate]

### AgentModelProfile

- source_ref: `pyast://backend/agent_system/models/model_profile_models.py#class:AgentModelProfile`
- outgoing_count: 1
- accepted_count: 1
- candidate_count: 0
- conflict_count: 0

- `defines_method` -> `pyast://backend/agent_system/models/model_profile_models.py#py_method:AgentModelProfile.to_dict` [accepted]

### ModelRequirement

- source_ref: `pyast://backend/agent_system/models/model_profile_models.py#class:ModelRequirement`
- outgoing_count: 1
- accepted_count: 1
- candidate_count: 0
- conflict_count: 0

- `defines_method` -> `pyast://backend/agent_system/models/model_profile_models.py#py_method:ModelRequirement.to_dict` [accepted]

### ResolvedModelSpec

- source_ref: `pyast://backend/agent_system/models/model_profile_models.py#class:ResolvedModelSpec`
- outgoing_count: 1
- accepted_count: 1
- candidate_count: 0
- conflict_count: 0

- `defines_method` -> `pyast://backend/agent_system/models/model_profile_models.py#py_method:ResolvedModelSpec.to_public_dict` [accepted]

### pyast://backend/agent_system/models/model_profile_models.py#module

- source_ref: `pyast://backend/agent_system/models/model_profile_models.py#module`
- outgoing_count: 14
- accepted_count: 13
- candidate_count: 1
- conflict_count: 0

- `defines_class` -> `pyast://backend/agent_system/models/model_profile_models.py#class:AgentModelProfile` [accepted]
- `defines_class` -> `pyast://backend/agent_system/models/model_profile_models.py#class:ModelRequirement` [accepted]
- `defines_class` -> `pyast://backend/agent_system/models/model_profile_models.py#class:ResolvedModelSpec` [accepted]
- `defines_function` -> `pyast://backend/agent_system/models/model_profile_models.py#py_function:_dict_or_empty` [accepted]
- `defines_function` -> `pyast://backend/agent_system/models/model_profile_models.py#py_function:_is_sensitive_key` [accepted]
- `defines_function` -> `pyast://backend/agent_system/models/model_profile_models.py#py_function:_optional_bool` [accepted]
- `defines_function` -> `pyast://backend/agent_system/models/model_profile_models.py#py_function:_optional_float` [accepted]
- `defines_function` -> `pyast://backend/agent_system/models/model_profile_models.py#py_function:_optional_int` [accepted]
- `defines_function` -> `pyast://backend/agent_system/models/model_profile_models.py#py_function:_unique_texts` [accepted]
- `defines_function` -> `pyast://backend/agent_system/models/model_profile_models.py#py_function:contains_raw_secret` [accepted]
- `defines_function` -> `pyast://backend/agent_system/models/model_profile_models.py#py_function:parse_agent_model_profile` [accepted]
- `defines_function` -> `pyast://backend/agent_system/models/model_profile_models.py#py_function:parse_model_requirement` [accepted]

### contains_raw_secret

- source_ref: `pyast://backend/agent_system/models/model_profile_models.py#py_function:contains_raw_secret`
- outgoing_count: 1
- accepted_count: 1
- candidate_count: 0
- conflict_count: 0

- `calls` -> `pyast://backend/agent_system/models/model_profile_models.py#py_function:_is_sensitive_key` [accepted]

### parse_agent_model_profile

- source_ref: `pyast://backend/agent_system/models/model_profile_models.py#py_function:parse_agent_model_profile`
- outgoing_count: 6
- accepted_count: 6
- candidate_count: 0
- conflict_count: 0

- `calls` -> `pyast://backend/agent_system/models/model_profile_models.py#py_function:_optional_int` [accepted]
- `calls` -> `pyast://backend/agent_system/models/model_profile_models.py#py_function:_optional_float` [accepted]
- `calls` -> `pyast://backend/agent_system/models/model_profile_models.py#class:AgentModelProfile` [accepted]
- `calls` -> `pyast://backend/agent_system/models/model_profile_models.py#py_function:_dict_or_empty` [accepted]
- `calls` -> `pyast://backend/agent_system/models/model_profile_models.py#py_function:sanitize_model_profile_payload` [accepted]
- `calls` -> `pyast://backend/agent_system/models/model_profile_models.py#py_function:_unique_texts` [accepted]

### parse_model_requirement

- source_ref: `pyast://backend/agent_system/models/model_profile_models.py#py_function:parse_model_requirement`
- outgoing_count: 7
- accepted_count: 7
- candidate_count: 0
- conflict_count: 0

- `calls` -> `pyast://backend/agent_system/models/model_profile_models.py#py_function:_optional_int` [accepted]
- `calls` -> `pyast://backend/agent_system/models/model_profile_models.py#py_function:_optional_float` [accepted]
- `calls` -> `pyast://backend/agent_system/models/model_profile_models.py#py_function:_optional_bool` [accepted]
- `calls` -> `pyast://backend/agent_system/models/model_profile_models.py#py_function:_dict_or_empty` [accepted]
- `calls` -> `pyast://backend/agent_system/models/model_profile_models.py#py_function:sanitize_model_profile_payload` [accepted]
- `calls` -> `pyast://backend/agent_system/models/model_profile_models.py#py_function:_unique_texts` [accepted]
- `calls` -> `pyast://backend/agent_system/models/model_profile_models.py#class:ModelRequirement` [accepted]

### sanitize_model_profile_payload

- source_ref: `pyast://backend/agent_system/models/model_profile_models.py#py_function:sanitize_model_profile_payload`
- outgoing_count: 1
- accepted_count: 1
- candidate_count: 0
- conflict_count: 0

- `calls` -> `pyast://backend/agent_system/models/model_profile_models.py#py_function:_is_sensitive_key` [accepted]

### AgentModelProfile.to_dict

- source_ref: `pyast://backend/agent_system/models/model_profile_models.py#py_method:AgentModelProfile.to_dict`
- outgoing_count: 1
- accepted_count: 1
- candidate_count: 0
- conflict_count: 0

- `calls` -> `pyast://backend/agent_system/models/model_profile_models.py#py_function:sanitize_model_profile_payload` [accepted]

### Model Profile Resolver Class

- source_ref: `pyast://backend/agent_system/models/model_profile_resolver.py#class:ModelProfileResolver`
- outgoing_count: 4
- accepted_count: 4
- candidate_count: 0
- conflict_count: 0

- `defines_method` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_method:ModelProfileResolver.__init__` [accepted]
- `defines_method` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_method:ModelProfileResolver.resolve_provider_base_url` [accepted]
- `defines_method` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_method:ModelProfileResolver.resolve_model_spec` [accepted]
- `defines_method` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_method:ModelProfileResolver.resolve_credential_ref` [accepted]

### pyast://backend/agent_system/models/model_profile_resolver.py#module

- source_ref: `pyast://backend/agent_system/models/model_profile_resolver.py#module`
- outgoing_count: 15
- accepted_count: 14
- candidate_count: 1
- conflict_count: 0

- `defines_class` -> `pyast://backend/agent_system/models/model_profile_resolver.py#class:ModelProfileResolver` [accepted]
- `defines_function` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_nonnegative_int` [accepted]
- `defines_function` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_provider_env_names` [accepted]
- `defines_function` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_normalize_reasoning_effort` [accepted]
- `defines_function` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_optional_positive_float` [accepted]
- `defines_function` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_credential_ref_catalog` [accepted]
- `defines_function` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_positive_float` [accepted]
- `defines_function` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_optional_positive_int` [accepted]
- `defines_function` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_provider_credential_configured` [accepted]
- `defines_function` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_positive_int` [accepted]
- `defines_function` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_float_or` [accepted]
- `defines_function` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_stream_policy_for_requirement` [accepted]

### _credential_ref_catalog

- source_ref: `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_credential_ref_catalog`
- outgoing_count: 1
- accepted_count: 1
- candidate_count: 0
- conflict_count: 0

- `calls` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_provider_credential_configured` [accepted]

### _first_env_for_provider

- source_ref: `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_first_env_for_provider`
- outgoing_count: 1
- accepted_count: 1
- candidate_count: 0
- conflict_count: 0

- `calls` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_provider_env_names` [accepted]

### _provider_credential_configured

- source_ref: `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_provider_credential_configured`
- outgoing_count: 1
- accepted_count: 1
- candidate_count: 0
- conflict_count: 0

- `calls` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_first_env_for_provider` [accepted]

### Build Provider Catalog

- source_ref: `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:build_provider_catalog`
- outgoing_count: 2
- accepted_count: 2
- candidate_count: 0
- conflict_count: 0

- `calls` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_credential_ref_catalog` [accepted]
- `calls` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_provider_credential_configured` [accepted]

### ModelProfileResolver.resolve_model_spec

- source_ref: `pyast://backend/agent_system/models/model_profile_resolver.py#py_method:ModelProfileResolver.resolve_model_spec`
- outgoing_count: 10
- accepted_count: 10
- candidate_count: 0
- conflict_count: 0

- `calls` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_nonnegative_int` [accepted]
- `calls` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_normalize_reasoning_effort` [accepted]
- `calls` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_optional_positive_float` [accepted]
- `calls` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_positive_float` [accepted]
- `calls` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_optional_positive_int` [accepted]
- `calls` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_positive_int` [accepted]
- `calls` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_method:ModelProfileResolver.resolve_provider_base_url` [accepted]
- `calls` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_float_or` [accepted]
- `calls` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_stream_policy_for_requirement` [accepted]
- `calls` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_method:ModelProfileResolver.resolve_credential_ref` [accepted]

## Audit Signals

- [info] out_of_scope_target_ref `pyast://backend/agent_system/models/model_profile_resolver.py#module`
- [info] out_of_scope_source_ref `pyast://backend/agent_system/models/model_profile_resolver.py#module`
- [info] out_of_scope_source_ref `pyast://backend/agent_system/models/model_profile_resolver.py#module`
- [info] out_of_scope_source_ref `pyast://backend/agent_system/models/model_profile_resolver.py#module`
- [info] out_of_scope_source_ref `pyast://backend/agent_system/models/model_profile_resolver.py#module`
- [info] out_of_scope_source_ref `pyast://backend/agent_system/models/model_profile_resolver.py#module`
- [info] out_of_scope_source_ref `pyast://backend/agent_system/models/model_profile_resolver.py#module`
- [info] out_of_scope_source_ref `pyast://backend/agent_system/models/model_profile_resolver.py#module`
- [info] out_of_scope_source_ref `pyast://backend/agent_system/models/model_profile_resolver.py#module`
- [info] out_of_scope_source_ref `pyast://backend/agent_system/models/model_profile_resolver.py#module`
- [info] out_of_scope_source_ref `pyast://backend/agent_system/models/model_profile_resolver.py#module`
- [info] out_of_scope_source_ref `pyast://backend/agent_system/models/model_profile_resolver.py#module`
- [info] out_of_scope_source_ref `pyast://backend/agent_system/models/model_profile_resolver.py#module`
- [info] out_of_scope_source_ref `pyast://backend/agent_system/models/model_profile_resolver.py#module`
- [info] out_of_scope_source_ref `pyast://backend/agent_system/models/model_profile_resolver.py#module`
- [info] out_of_scope_source_ref `pyast://backend/agent_system/models/model_profile_resolver.py#module`
- [info] candidate_relation_needs_resolution `pnedge:ebb1f1e427ab2cd4f4f7`
- [info] out_of_scope_target_ref `pyast://backend/agent_system/models/model_profile_models.py#module`
- [info] out_of_scope_source_ref `pyast://backend/agent_system/models/model_profile_models.py#module`
- [info] out_of_scope_source_ref `pyast://backend/agent_system/models/model_profile_models.py#module`
- [info] out_of_scope_source_ref `pyast://backend/agent_system/models/model_profile_models.py#module`
- [info] out_of_scope_source_ref `pyast://backend/agent_system/models/model_profile_models.py#module`
- [info] out_of_scope_source_ref `pyast://backend/agent_system/models/model_profile_models.py#module`
- [info] out_of_scope_source_ref `pyast://backend/agent_system/models/model_profile_models.py#module`
- [info] out_of_scope_source_ref `pyast://backend/agent_system/models/model_profile_models.py#module`
- [info] out_of_scope_source_ref `pyast://backend/agent_system/models/model_profile_models.py#module`
- [info] out_of_scope_source_ref `pyast://backend/agent_system/models/model_profile_models.py#module`
- [info] out_of_scope_source_ref `pyast://backend/agent_system/models/model_profile_models.py#module`
- [info] out_of_scope_source_ref `pyast://backend/agent_system/models/model_profile_models.py#module`
- [info] out_of_scope_source_ref `pyast://backend/agent_system/models/model_profile_models.py#module`
- [info] out_of_scope_source_ref `pyast://backend/agent_system/models/model_profile_models.py#module`
- [info] out_of_scope_source_ref `pyast://backend/agent_system/models/model_profile_models.py#module`
- [info] candidate_relation_needs_resolution `pnedge:c0d50ca44a99fbd74700`
- [info] candidate_relation_needs_resolution `pnedge:7c15424a06071bba606f`
- [info] candidate_relation_needs_resolution `pnedge:c6d7366376cbd324f58c`
- [info] candidate_relation_needs_resolution `pnedge:143d54b64979a504d355`
- [info] candidate_relation_needs_resolution `pnedge:44b07822d154c07a7709`
- [info] candidate_relation_needs_resolution `pnedge:31ee666dfc96c4684ff6`
- [info] candidate_relation_needs_resolution `pnedge:f89cac972563e114fe34`
- [info] candidate_relation_needs_resolution `pnedge:8d2d22b3e17960d7b437`
- [info] candidate_relation_needs_resolution `pnedge:5f9cdefa1fc62f220b0c`
- [info] candidate_relation_needs_resolution `pnedge:64a103ab0fdc0a2c606c`
- [info] candidate_relation_needs_resolution `pnedge:908d9f4a219dc4f51a1b`
- [info] candidate_relation_needs_resolution `pnedge:111f4792fce905de68e8`
- [info] candidate_relation_needs_resolution `pnedge:910db2ec8d30b2a6bbc7`
- [info] candidate_relation_needs_resolution `pnedge:7ca633f5065182dc9ff1`
- [info] candidate_relation_needs_resolution `pnedge:9808eb36172022137c6e`
- [info] candidate_relation_needs_resolution `pnedge:61beaa0d05d1e942db9c`
