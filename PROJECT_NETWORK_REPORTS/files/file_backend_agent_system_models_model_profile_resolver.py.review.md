# File Review: Model Profile Resolver

- file_ref: `file://backend/agent_system/models/model_profile_resolver.py`
- file_path: `backend/agent_system/models/model_profile_resolver.py`
- file_hash: `e37d4c6292420722fc1b522a3f9f5ab5d82d888338c148df24859fd709d5de90`
- physical_status: resolved
- confidence: exact

## Semantic Coordinate

- summary: Provides model resolution logic: resolves model specs by merging agent runtime profiles, model requirements, and system settings for LLM provider configuration.
- control_role: resolver
- tags: agent_system, models, resolver, LLM, provider_config

## IO Surface

- entry_points: ["pyast://backend/agent_system/models/model_profile_resolver.py#py_function:build_provider_catalog", "pyast://backend/agent_system/models/model_profile_resolver.py#py_method:ModelProfileResolver.__init__", "pyast://backend/agent_system/m...
- external_reads: ["bootstrap.settings.AppSettingsService", "core.config.LLM_PROVIDER_DEFAULTS", "profiles.runtime_profile_models.AgentRuntimeProfile", "model_profile_models.AgentModelProfile", "model_profile_models.ModelRequirement", "model_profile_model...
- external_writes: []

## Control Nodes

- `file://backend/agent_system/models/model_profile_resolver.py` [file_module] [resolved/workspace_file] Model Profile Resolver Module
- `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:build_provider_catalog` [py_function] [resolved/workspace_file_anchor] build_provider_catalog
- `pyast://backend/agent_system/models/model_profile_resolver.py#class:ModelProfileResolver` [py_class] [resolved/workspace_file_anchor] ModelProfileResolver
- `pyast://backend/agent_system/models/model_profile_resolver.py#py_method:ModelProfileResolver.__init__` [py_method] [resolved/workspace_file_anchor] __init__
- `pyast://backend/agent_system/models/model_profile_resolver.py#py_method:ModelProfileResolver.resolve_model_spec` [py_method] [resolved/workspace_file_anchor] resolve_model_spec
- `pyast://backend/agent_system/models/model_profile_resolver.py#py_method:ModelProfileResolver.resolve_provider_base_url` [py_method] [resolved/workspace_file_anchor] resolve_provider_base_url
- `pyast://backend/agent_system/models/model_profile_resolver.py#py_method:ModelProfileResolver.resolve_credential_ref` [py_method] [resolved/workspace_file_anchor] resolve_credential_ref
- `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_nonnegative_int` [py_function] [resolved/workspace_file_anchor] _nonnegative_int
- `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_positive_int` [py_function] [resolved/workspace_file_anchor] _positive_int
- `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_positive_float` [py_function] [resolved/workspace_file_anchor] _positive_float
- `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_optional_positive_int` [py_function] [resolved/workspace_file_anchor] _optional_positive_int
- `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_optional_positive_float` [py_function] [resolved/workspace_file_anchor] _optional_positive_float
- `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_normalize_reasoning_effort` [py_function] [resolved/workspace_file_anchor] _normalize_reasoning_effort
- `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_float_or` [py_function] [resolved/workspace_file_anchor] _float_or
- `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_stream_policy_for_requirement` [py_function] [resolved/workspace_file_anchor] _stream_policy_for_requirement
- `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_credential_ref_catalog` [py_function] [resolved/workspace_file_anchor] _credential_ref_catalog
- `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_provider_credential_configured` [py_function] [resolved/workspace_file_anchor] _provider_credential_configured
- `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_first_env_for_provider` [py_function] [resolved/workspace_file_anchor] _first_env_for_provider
- `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_provider_env_names` [py_function] [resolved/workspace_file_anchor] _provider_env_names

## Signal Edges

- `file://backend/agent_system/models/model_profile_resolver.py` -> `pyast://backend/agent_system/models/model_profile_resolver.py#module` via `defines_module` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_resolver.py#module` -> `pyast://backend/agent_system/models/model_profile_resolver.py#class:ModelProfileResolver` via `defines_class` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_resolver.py#module` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_nonnegative_int` via `defines_function` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_resolver.py#module` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_provider_env_names` via `defines_function` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_resolver.py#module` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_normalize_reasoning_effort` via `defines_function` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_resolver.py#module` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_optional_positive_float` via `defines_function` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_resolver.py#module` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_credential_ref_catalog` via `defines_function` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_resolver.py#module` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_positive_float` via `defines_function` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_resolver.py#module` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_optional_positive_int` via `defines_function` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_resolver.py#module` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_provider_credential_configured` via `defines_function` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_resolver.py#module` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_positive_int` via `defines_function` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_resolver.py#module` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_float_or` via `defines_function` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_resolver.py#module` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_stream_policy_for_requirement` via `defines_function` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_resolver.py#module` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:build_provider_catalog` via `defines_function` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_resolver.py#module` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_first_env_for_provider` via `defines_function` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_resolver.py#class:ModelProfileResolver` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_method:ModelProfileResolver.__init__` via `defines_method` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_resolver.py#class:ModelProfileResolver` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_method:ModelProfileResolver.resolve_provider_base_url` via `defines_method` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_resolver.py#class:ModelProfileResolver` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_method:ModelProfileResolver.resolve_model_spec` via `defines_method` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_resolver.py#class:ModelProfileResolver` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_method:ModelProfileResolver.resolve_credential_ref` via `defines_method` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_credential_ref_catalog` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_provider_credential_configured` via `calls` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_provider_credential_configured` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_first_env_for_provider` via `calls` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_first_env_for_provider` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_provider_env_names` via `calls` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:build_provider_catalog` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_credential_ref_catalog` via `calls` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:build_provider_catalog` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_provider_credential_configured` via `calls` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_resolver.py#py_method:ModelProfileResolver.resolve_model_spec` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_nonnegative_int` via `calls` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_resolver.py#py_method:ModelProfileResolver.resolve_model_spec` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_normalize_reasoning_effort` via `calls` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_resolver.py#py_method:ModelProfileResolver.resolve_model_spec` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_optional_positive_float` via `calls` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_resolver.py#py_method:ModelProfileResolver.resolve_model_spec` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_positive_float` via `calls` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_resolver.py#py_method:ModelProfileResolver.resolve_model_spec` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_optional_positive_int` via `calls` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_resolver.py#py_method:ModelProfileResolver.resolve_model_spec` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_positive_int` via `calls` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_resolver.py#py_method:ModelProfileResolver.resolve_model_spec` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_method:ModelProfileResolver.resolve_provider_base_url` via `calls` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_resolver.py#py_method:ModelProfileResolver.resolve_model_spec` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_float_or` via `calls` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_resolver.py#py_method:ModelProfileResolver.resolve_model_spec` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_stream_policy_for_requirement` via `calls` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_resolver.py#py_method:ModelProfileResolver.resolve_model_spec` -> `pyast://backend/agent_system/models/model_profile_resolver.py#py_method:ModelProfileResolver.resolve_credential_ref` via `calls` [accepted; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_resolver.py#module` -> `None` via `imports` [candidate; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_resolver.py#module` -> `None` via `imports` [candidate; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_resolver.py#module` -> `None` via `imports` [candidate; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_resolver.py#module` -> `None` via `imports` [candidate; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_resolver.py#module` -> `None` via `imports` [candidate; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_resolver.py#module` -> `None` via `imports` [candidate; evidence=1; anchors=1]
- `pyast://backend/agent_system/models/model_profile_resolver.py#module` -> `None` via `imports` [candidate; evidence=1; anchors=1]

## Limitations

- Interprocedural dataflow not computed. Unresolved call/import candidates remain evidence candidates
- not accepted semantic links. Many builtin calls (str
- float
- int
- max
- bool
- isinstance
- getattr
- len
- set
- list
- tuple
- dict.fromkeys
- any
- all) remain unresolved.
