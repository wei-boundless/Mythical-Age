# Project Semantic Coordinates

- build_id: `agent_system_models_control_network_ast_live_20260702_063038`
- generated_at: `2026-07-03T12:34:32.949658+00:00`
- coordinate_count: 63

## Coordinates

### Agent System Models Directory

- coordinate_ref: `folder://backend/agent_system/models`
- physical_ref: `folder://backend/agent_system/models`
- layer: directory
- control_role: model_definition_and_resolution
- summary: Defines data models for agent descriptors, lifecycle records, model profiles, and a resolver for LLM model specifications.
- tags: agent_system, models, data_model, LLM_config
- confidence: exact

### Model Profile Resolver

- coordinate_ref: `file://backend/agent_system/models/model_profile_resolver.py`
- physical_ref: `file://backend/agent_system/models/model_profile_resolver.py`
- layer: file
- control_role: resolver
- summary: Provides model resolution logic: resolves model specs by merging agent runtime profiles, model requirements, and system settings for LLM provider configuration.
- tags: agent_system, models, resolver, LLM, provider_config
- confidence: exact

### model_profile_models

- coordinate_ref: `file://backend/agent_system/models/model_profile_models.py`
- physical_ref: `file://backend/agent_system/models/model_profile_models.py`
- layer: file
- control_role: data_model_definition
- summary: Agent model profile data models and parsing functions: AgentModelProfile, ModelRequirement, ResolvedModelSpec, and associated parsers, sanitizers, and secret detection.
- tags: agent_system, models, profile, data_model, parser, sanitizer
- confidence: exact

### AgentModelsModule

- coordinate_ref: `file://backend/agent_system/models/agent_models.py`
- physical_ref: `file://backend/agent_system/models/agent_models.py`
- layer: file
- control_role: data_model
- summary: Defines AgentDescriptor and AgentLifecycleRecord data classes for agent lifecycle management and governance.
- tags: data_model, agent, agent_descriptor, lifecycle
- confidence: exact

### models package init

- coordinate_ref: `file://backend/agent_system/models/__init__.py`
- physical_ref: `file://backend/agent_system/models/__init__.py`
- layer: file
- control_role: entry_point
- summary: Lazy-import facade for agent_system.models submodules
- tags: python, init, package, lazy_import, registry
- confidence: exact

### Workspace root

- coordinate_ref: `folder://.`
- physical_ref: `folder://.`
- layer: semantic
- control_role: -
- summary: Physical root of the project control network.
- tags: physical_structure, system_root
- confidence: system

### backend

- coordinate_ref: `folder://backend`
- physical_ref: `folder://backend`
- layer: directory
- control_role: -
- summary: Physical directory in the project control network.
- tags: physical_structure, directory
- confidence: system

### backend/agent_system

- coordinate_ref: `folder://backend/agent_system`
- physical_ref: `folder://backend/agent_system`
- layer: directory
- control_role: -
- summary: Physical directory in the project control network.
- tags: physical_structure, directory
- confidence: system

### models init module

- coordinate_ref: `pyast://backend/agent_system/models/__init__.py#module`
- physical_ref: `pyast://backend/agent_system/models/__init__.py#module`
- layer: file
- control_role: -
- summary: Package init module with lazy-import export table and dynamic __getattr__
- tags: python, module, init, lazy_import, registry
- confidence: exact

### dynamic import router

- coordinate_ref: `pyast://backend/agent_system/models/__init__.py#py_function:__getattr__`
- physical_ref: `pyast://backend/agent_system/models/__init__.py#py_function:__getattr__`
- layer: semantic
- control_role: -
- summary: Intercepts attribute access on the package, imports the submodule, caches the attribute, and returns it.
- tags: python, function, lazy_import, router
- confidence: exact

### AgentDescriptor

- coordinate_ref: `pyast://backend/agent_system/models/agent_models.py#class:AgentDescriptor`
- physical_ref: `pyast://backend/agent_system/models/agent_models.py#class:AgentDescriptor`
- layer: semantic
- control_role: -
- summary: Frozen dataclass with metadata and computed properties for agent lifecycle, governance, and routing.
- tags: data_class, agent_descriptor
- confidence: exact

### AgentLifecycleRecord

- coordinate_ref: `pyast://backend/agent_system/models/agent_models.py#class:AgentLifecycleRecord`
- physical_ref: `pyast://backend/agent_system/models/agent_models.py#class:AgentLifecycleRecord`
- layer: semantic
- control_role: -
- summary: Frozen dataclass storing agent lifecycle event data and payload.
- tags: data_class, lifecycle
- confidence: exact

### AgentModelsModule

- coordinate_ref: `pyast://backend/agent_system/models/agent_models.py#module`
- physical_ref: `pyast://backend/agent_system/models/agent_models.py#module`
- layer: file
- control_role: -
- summary: Module containing AgentDescriptor and AgentLifecycleRecord.
- tags: module, data_model
- confidence: exact

### AgentDescriptor.agent_template_id

- coordinate_ref: `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.agent_template_id`
- physical_ref: `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.agent_template_id`
- layer: semantic
- control_role: -
- summary: Returns the agent template ID from metadata, stripped.
- tags: property, template
- confidence: exact

### AgentDescriptor.builtin_kind

- coordinate_ref: `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.builtin_kind`
- physical_ref: `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.builtin_kind`
- layer: semantic
- control_role: -
- summary: Returns the builtin subtype (primary, specialist, system_manager) based on metadata and category.
- tags: property, classification
- confidence: exact

### AgentDescriptor.definition_source

- coordinate_ref: `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.definition_source`
- physical_ref: `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.definition_source`
- layer: semantic
- control_role: -
- summary: Returns 'system_builtin' for builtin agents or the definition source from metadata.
- tags: property, source
- confidence: exact

### AgentDescriptor.deletable

- coordinate_ref: `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.deletable`
- physical_ref: `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.deletable`
- layer: semantic
- control_role: -
- summary: Returns 'delete_allowed' constant.
- tags: property, deletion
- confidence: exact

### AgentDescriptor.disable_allowed

- coordinate_ref: `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.disable_allowed`
- physical_ref: `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.disable_allowed`
- layer: semantic
- control_role: -
- summary: Returns True (all agents can be disabled).
- tags: property, disable
- confidence: exact

### AgentDescriptor.display_name

- coordinate_ref: `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.display_name`
- physical_ref: `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.display_name`
- layer: semantic
- control_role: -
- summary: Returns the agent name as display name.
- tags: property, display
- confidence: exact

### AgentDescriptor.governance_status

- coordinate_ref: `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.governance_status`
- physical_ref: `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.governance_status`
- layer: semantic
- control_role: -
- summary: Returns 'system_builtin' or 'task_managed' based on builtin flag.
- tags: property, governance
- confidence: exact

### AgentDescriptor.group_eligible

- coordinate_ref: `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.group_eligible`
- physical_ref: `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.group_eligible`
- layer: semantic
- control_role: -
- summary: Returns whether the agent can be grouped; default for custom agents.
- tags: property, group
- confidence: exact

### AgentDescriptor.lifecycle_policy

- coordinate_ref: `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.lifecycle_policy`
- physical_ref: `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.lifecycle_policy`
- layer: semantic
- control_role: -
- summary: Returns lifecycle policy string from metadata or default based on builtin flag.
- tags: property, policy
- confidence: exact

### AgentDescriptor.lifecycle_state

- coordinate_ref: `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.lifecycle_state`
- physical_ref: `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.lifecycle_state`
- layer: semantic
- control_role: -
- summary: Returns 'system_builtin', 'enabled', or 'disabled' based on builtin/enabled flags.
- tags: property, lifecycle
- confidence: exact

### AgentDescriptor.mutable_fields

- coordinate_ref: `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.mutable_fields`
- physical_ref: `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.mutable_fields`
- layer: semantic
- control_role: -
- summary: Returns tuple of field names that are mutable.
- tags: property, schema
- confidence: exact

### AgentDescriptor.owner_system

- coordinate_ref: `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.owner_system`
- physical_ref: `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.owner_system`
- layer: semantic
- control_role: -
- summary: Determines the owning system slug based on category and metadata.
- tags: property, routing
- confidence: exact

### AgentDescriptor.profile_type

- coordinate_ref: `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.profile_type`
- physical_ref: `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.profile_type`
- layer: semantic
- control_role: -
- summary: Returns the agent category as profile type.
- tags: property, profile
- confidence: exact

### AgentDescriptor.subagent_enabled

- coordinate_ref: `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.subagent_enabled`
- physical_ref: `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.subagent_enabled`
- layer: semantic
- control_role: -
- summary: Determines if subagent is enabled based on explicit flag or category rules.
- tags: property, subagent
- confidence: exact

### AgentDescriptor.to_dict

- coordinate_ref: `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.to_dict`
- physical_ref: `pyast://backend/agent_system/models/agent_models.py#py_method:AgentDescriptor.to_dict`
- layer: semantic
- control_role: -
- summary: Serializes AgentDescriptor to dict including computed properties.
- tags: method, serialization
- confidence: exact

### AgentLifecycleRecord.to_dict

- coordinate_ref: `pyast://backend/agent_system/models/agent_models.py#py_method:AgentLifecycleRecord.to_dict`
- physical_ref: `pyast://backend/agent_system/models/agent_models.py#py_method:AgentLifecycleRecord.to_dict`
- layer: semantic
- control_role: -
- summary: Serializes AgentLifecycleRecord to dict.
- tags: method, serialization
- confidence: exact

### AgentModelProfile

- coordinate_ref: `pyast://backend/agent_system/models/model_profile_models.py#class:AgentModelProfile`
- physical_ref: `pyast://backend/agent_system/models/model_profile_models.py#class:AgentModelProfile`
- layer: semantic
- control_role: -
- summary: Frozen dataclass representing a single agent model profile with provider, model, token limits, thinking modes, streaming policy, response format, and fallback config. to_dict() sanitizes output.
- tags: data_model, profile, frozen
- confidence: exact

### ModelRequirement

- coordinate_ref: `pyast://backend/agent_system/models/model_profile_models.py#class:ModelRequirement`
- physical_ref: `pyast://backend/agent_system/models/model_profile_models.py#class:ModelRequirement`
- layer: semantic
- control_role: -
- summary: Frozen dataclass describing a model requirement with family, capability tags, token ranges, thinking/structure constraints, and fallback policy.
- tags: data_model, requirement, frozen
- confidence: exact

### ResolvedModelSpec

- coordinate_ref: `pyast://backend/agent_system/models/model_profile_models.py#class:ResolvedModelSpec`
- physical_ref: `pyast://backend/agent_system/models/model_profile_models.py#class:ResolvedModelSpec`
- layer: semantic
- control_role: -
- summary: Frozen dataclass representing a fully resolved model specification with provider, model, credentials, token limits, and diagnostics. to_public_dict() produces a safe public view.
- tags: data_model, resolved_spec, frozen
- confidence: exact

### _dict_or_empty

- coordinate_ref: `pyast://backend/agent_system/models/model_profile_models.py#py_function:_dict_or_empty`
- physical_ref: `pyast://backend/agent_system/models/model_profile_models.py#py_function:_dict_or_empty`
- layer: semantic
- control_role: -
- summary: Returns the value if it is a dict, otherwise returns an empty dict.
- tags: utility, type_coercion
- confidence: exact

### _is_sensitive_key

- coordinate_ref: `pyast://backend/agent_system/models/model_profile_models.py#py_function:_is_sensitive_key`
- physical_ref: `pyast://backend/agent_system/models/model_profile_models.py#py_function:_is_sensitive_key`
- layer: semantic
- control_role: -
- summary: Normalizes a key to lowercase and checks if it ends with '_api_key' or is in SENSITIVE_MODEL_PROFILE_KEYS set.
- tags: utility, security, key_detection
- confidence: exact

### _optional_bool

- coordinate_ref: `pyast://backend/agent_system/models/model_profile_models.py#py_function:_optional_bool`
- physical_ref: `pyast://backend/agent_system/models/model_profile_models.py#py_function:_optional_bool`
- layer: semantic
- control_role: -
- summary: Coerces a value to bool if it is an instance of bool; otherwise attempts string parsing for truthy/falsy values or returns None.
- tags: utility, type_coercion
- confidence: exact

### _optional_float

- coordinate_ref: `pyast://backend/agent_system/models/model_profile_models.py#py_function:_optional_float`
- physical_ref: `pyast://backend/agent_system/models/model_profile_models.py#py_function:_optional_float`
- layer: semantic
- control_role: -
- summary: Coerces a value to float if not None; otherwise returns None.
- tags: utility, type_coercion
- confidence: exact

### _optional_int

- coordinate_ref: `pyast://backend/agent_system/models/model_profile_models.py#py_function:_optional_int`
- physical_ref: `pyast://backend/agent_system/models/model_profile_models.py#py_function:_optional_int`
- layer: semantic
- control_role: -
- summary: Coerces a value to int if not None; otherwise returns None.
- tags: utility, type_coercion
- confidence: exact

### _unique_texts

- coordinate_ref: `pyast://backend/agent_system/models/model_profile_models.py#py_function:_unique_texts`
- physical_ref: `pyast://backend/agent_system/models/model_profile_models.py#py_function:_unique_texts`
- layer: semantic
- control_role: -
- summary: Deduplicates a list of strings, preserving order. Returns a new list.
- tags: utility, deduplication
- confidence: exact

### contains_raw_secret

- coordinate_ref: `pyast://backend/agent_system/models/model_profile_models.py#py_function:contains_raw_secret`
- physical_ref: `pyast://backend/agent_system/models/model_profile_models.py#py_function:contains_raw_secret`
- layer: semantic
- control_role: -
- summary: Recursively checks if a value (dict, list, or scalar) contains any sensitive strings (apikey, secret, token, etc.). Calls _is_sensitive_key on dict keys.
- tags: security, detection, recursive
- confidence: exact

### parse_agent_model_profile

- coordinate_ref: `pyast://backend/agent_system/models/model_profile_models.py#py_function:parse_agent_model_profile`
- physical_ref: `pyast://backend/agent_system/models/model_profile_models.py#py_function:parse_agent_model_profile`
- layer: semantic
- control_role: -
- summary: Constructs AgentModelProfile from a raw dict, applying optional type coercion for all fields. Calls sanitize_model_profile_payload on the input.
- tags: parser, constructor, sanitizer
- confidence: exact

### parse_model_requirement

- coordinate_ref: `pyast://backend/agent_system/models/model_profile_models.py#py_function:parse_model_requirement`
- physical_ref: `pyast://backend/agent_system/models/model_profile_models.py#py_function:parse_model_requirement`
- layer: semantic
- control_role: -
- summary: Constructs ModelRequirement from a raw dict, applying optional type coercion. Calls sanitize_model_profile_payload on the input.
- tags: parser, constructor, sanitizer
- confidence: exact

### sanitize_model_profile_payload

- coordinate_ref: `pyast://backend/agent_system/models/model_profile_models.py#py_function:sanitize_model_profile_payload`
- physical_ref: `pyast://backend/agent_system/models/model_profile_models.py#py_function:sanitize_model_profile_payload`
- layer: semantic
- control_role: -
- summary: Recursively traverses a dict, stripping keys that match sensitive patterns via _is_sensitive_key. Used by to_dict() and both parse functions.
- tags: sanitizer, security, recursive
- confidence: exact

### AgentModelProfile.to_dict

- coordinate_ref: `pyast://backend/agent_system/models/model_profile_models.py#py_method:AgentModelProfile.to_dict`
- physical_ref: `pyast://backend/agent_system/models/model_profile_models.py#py_method:AgentModelProfile.to_dict`
- layer: semantic
- control_role: -
- summary: Converts the frozen dataclass to a dict via asdict, converts capability_tags tuple to list, then sanitizes via sanitize_model_profile_payload.
- tags: serialization, sanitization
- confidence: exact

### ModelRequirement.to_dict

- coordinate_ref: `pyast://backend/agent_system/models/model_profile_models.py#py_method:ModelRequirement.to_dict`
- physical_ref: `pyast://backend/agent_system/models/model_profile_models.py#py_method:ModelRequirement.to_dict`
- layer: semantic
- control_role: -
- summary: Converts the frozen dataclass to a dict via asdict, converts capability_tags tuple to list.
- tags: serialization
- confidence: exact

### ResolvedModelSpec.to_public_dict

- coordinate_ref: `pyast://backend/agent_system/models/model_profile_models.py#py_method:ResolvedModelSpec.to_public_dict`
- physical_ref: `pyast://backend/agent_system/models/model_profile_models.py#py_method:ResolvedModelSpec.to_public_dict`
- layer: semantic
- control_role: -
- summary: Returns a safe public dict with flattened fields, base_url_configured and credential_configured booleans, and source_chain as list.
- tags: serialization, public_view
- confidence: exact

### Model Profile Resolver Class

- coordinate_ref: `pyast://backend/agent_system/models/model_profile_resolver.py#class:ModelProfileResolver`
- physical_ref: `pyast://backend/agent_system/models/model_profile_resolver.py#class:ModelProfileResolver`
- layer: semantic
- control_role: -
- summary: Main class for resolving model specifications. Takes an AppSettingsService, provides methods to resolve base URLs, credentials, and full model specs.
- tags: agent_system, models, resolver
- confidence: exact

### _credential_ref_catalog

- coordinate_ref: `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_credential_ref_catalog`
- physical_ref: `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_credential_ref_catalog`
- layer: semantic
- control_role: -
- summary: Builds a list of credential ref entries for all providers and system slots, indicating configured status.
- tags: agent_system, models, resolver, helper
- confidence: exact

### _first_env_for_provider

- coordinate_ref: `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_first_env_for_provider`
- physical_ref: `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_first_env_for_provider`
- layer: semantic
- control_role: -
- summary: Returns the first non-empty environment variable value from the provider's env names list.
- tags: agent_system, models, resolver, helper
- confidence: exact

### _float_or

- coordinate_ref: `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_float_or`
- physical_ref: `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_float_or`
- layer: semantic
- control_role: -
- summary: Helper to coerce value to a float or return default.
- tags: agent_system, models, resolver, helper
- confidence: exact

### _nonnegative_int

- coordinate_ref: `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_nonnegative_int`
- physical_ref: `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_nonnegative_int`
- layer: semantic
- control_role: -
- summary: Helper to coerce value to a nonnegative integer with default.
- tags: agent_system, models, resolver, helper
- confidence: exact

### _normalize_reasoning_effort

- coordinate_ref: `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_normalize_reasoning_effort`
- physical_ref: `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_normalize_reasoning_effort`
- layer: semantic
- control_role: -
- summary: Helper to normalize reasoning effort string to lowercase stripped.
- tags: agent_system, models, resolver, helper
- confidence: exact

### _optional_positive_float

- coordinate_ref: `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_optional_positive_float`
- physical_ref: `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_optional_positive_float`
- layer: semantic
- control_role: -
- summary: Helper to coerce value to optional positive float (None if missing, min 0.01).
- tags: agent_system, models, resolver, helper
- confidence: exact

### _optional_positive_int

- coordinate_ref: `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_optional_positive_int`
- physical_ref: `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_optional_positive_int`
- layer: semantic
- control_role: -
- summary: Helper to coerce value to optional positive int (None if missing, min 1).
- tags: agent_system, models, resolver, helper
- confidence: exact

### _positive_float

- coordinate_ref: `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_positive_float`
- physical_ref: `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_positive_float`
- layer: semantic
- control_role: -
- summary: Helper to coerce value to a positive float with default (min 0.01).
- tags: agent_system, models, resolver, helper
- confidence: exact

### _positive_int

- coordinate_ref: `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_positive_int`
- physical_ref: `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_positive_int`
- layer: semantic
- control_role: -
- summary: Helper to coerce value to a positive integer with default (min 1).
- tags: agent_system, models, resolver, helper
- confidence: exact

### _provider_credential_configured

- coordinate_ref: `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_provider_credential_configured`
- physical_ref: `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_provider_credential_configured`
- layer: semantic
- control_role: -
- summary: Checks if a provider's credential is configured via system settings or environment variables.
- tags: agent_system, models, resolver, helper
- confidence: exact

### _provider_env_names

- coordinate_ref: `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_provider_env_names`
- physical_ref: `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_provider_env_names`
- layer: semantic
- control_role: -
- summary: Returns the list of environment variable names for a provider's credential from LLM_PROVIDER_DEFAULTS.
- tags: agent_system, models, resolver, helper
- confidence: exact

### _stream_policy_for_requirement

- coordinate_ref: `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_stream_policy_for_requirement`
- physical_ref: `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:_stream_policy_for_requirement`
- layer: semantic
- control_role: -
- summary: Helper to generate a stream policy dict from agent policy and requirement streaming flag.
- tags: agent_system, models, resolver, helper
- confidence: exact

### Build Provider Catalog

- coordinate_ref: `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:build_provider_catalog`
- physical_ref: `pyast://backend/agent_system/models/model_profile_resolver.py#py_function:build_provider_catalog`
- layer: semantic
- control_role: -
- summary: Builds a dictionary of LLM provider configurations from LLM_PROVIDER_DEFAULTS and system settings, including credential status.
- tags: agent_system, models, resolver, provider_catalog
- confidence: exact

### ModelProfileResolver.__init__

- coordinate_ref: `pyast://backend/agent_system/models/model_profile_resolver.py#py_method:ModelProfileResolver.__init__`
- physical_ref: `pyast://backend/agent_system/models/model_profile_resolver.py#py_method:ModelProfileResolver.__init__`
- layer: semantic
- control_role: -
- summary: Constructor that stores the settings_service instance.
- tags: agent_system, models, resolver, init
- confidence: exact

### ModelProfileResolver.resolve_credential_ref

- coordinate_ref: `pyast://backend/agent_system/models/model_profile_resolver.py#py_method:ModelProfileResolver.resolve_credential_ref`
- physical_ref: `pyast://backend/agent_system/models/model_profile_resolver.py#py_method:ModelProfileResolver.resolve_credential_ref`
- layer: semantic
- control_role: -
- summary: Resolves an API key from a credential ref string (provider:slot, env:VAR_NAME, system:provider:slot). Falls back to system settings or environment variables.
- tags: agent_system, models, resolver, credential
- confidence: exact

### ModelProfileResolver.resolve_model_spec

- coordinate_ref: `pyast://backend/agent_system/models/model_profile_resolver.py#py_method:ModelProfileResolver.resolve_model_spec`
- physical_ref: `pyast://backend/agent_system/models/model_profile_resolver.py#py_method:ModelProfileResolver.resolve_model_spec`
- layer: semantic
- control_role: -
- summary: Core resolution method that merges agent runtime profile, model requirement, and graph runtime defaults to produce a ResolvedModelSpec. Resolves provider, model, credential, and all numeric/string settings.
- tags: agent_system, models, resolver, core
- confidence: exact

### ModelProfileResolver.resolve_provider_base_url

- coordinate_ref: `pyast://backend/agent_system/models/model_profile_resolver.py#py_method:ModelProfileResolver.resolve_provider_base_url`
- physical_ref: `pyast://backend/agent_system/models/model_profile_resolver.py#py_method:ModelProfileResolver.resolve_provider_base_url`
- layer: semantic
- control_role: -
- summary: Resolves the base URL for a given provider from provider defaults, graph runtime defaults, or system settings (llm_base_url).
- tags: agent_system, models, resolver, base_url
- confidence: exact
