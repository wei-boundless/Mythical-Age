# Project Network Layer: file

- build_id: `agent_system_models_control_network_ast_live_20260702_063038`
- node_count: 6
- edge_count: 14

## Nodes

- `file://backend/agent_system/models/__init__.py` [file_module; resolved] models package init: Lazy-import facade for agent_system.models submodules
- `file://backend/agent_system/models/agent_models.py` [file_module; resolved] AgentModelsModule: Defines AgentDescriptor and AgentLifecycleRecord data classes for agent lifecycle management and governance.
- `file://backend/agent_system/models/model_profile_models.py` [file_module; resolved] model_profile_models: Agent model profile data models and parsing functions: AgentModelProfile, ModelRequirement, ResolvedModelSpec, and associated parsers, sanitizers, and secret detection.
- `file://backend/agent_system/models/model_profile_resolver.py` [file_module; resolved] Model Profile Resolver: Provides model resolution logic: resolves model specs by merging agent runtime profiles, model requirements, and system settings for LLM provider configuration.
- `pyast://backend/agent_system/models/__init__.py#module` [py_module; resolved] models init module: Package init module with lazy-import export table and dynamic __getattr__
- `pyast://backend/agent_system/models/agent_models.py#module` [py_module; resolved] AgentModelsModule: Module containing AgentDescriptor and AgentLifecycleRecord.

## Edges

- `pyast://backend/agent_system/models/agent_models.py#module` -> `pyast://backend/agent_system/models/agent_models.py#class:AgentDescriptor` via `defines_class` [accepted] 
- `folder://backend/agent_system/models` -> `file://backend/agent_system/models/model_profile_resolver.py` via `contains_file` [accepted] Physical containment extracted from the project file tree.
- `file://backend/agent_system/models/agent_models.py` -> `pyast://backend/agent_system/models/agent_models.py#module` via `defines_module` [accepted] 
- `folder://backend/agent_system/models` -> `file://backend/agent_system/models/agent_models.py` via `contains_file` [accepted] Physical containment extracted from the project file tree.
- `folder://backend/agent_system/models` -> `file://backend/agent_system/models/model_profile_models.py` via `contains_file` [accepted] Physical containment extracted from the project file tree.
- `file://backend/agent_system/models/__init__.py` -> `pyast://backend/agent_system/models/__init__.py#module` via `defines_module` [accepted] 
- `file://backend/agent_system/models/model_profile_resolver.py` -> `pyast://backend/agent_system/models/model_profile_resolver.py#module` via `defines_module` [accepted] 
- `pyast://backend/agent_system/models/agent_models.py#module` -> `` via `imports` [candidate] 
- `pyast://backend/agent_system/models/__init__.py#module` -> `` via `imports_text` [candidate] 
- `pyast://backend/agent_system/models/__init__.py#module` -> `pyast://backend/agent_system/models/__init__.py#py_function:__getattr__` via `defines_function` [accepted] 
- `pyast://backend/agent_system/models/__init__.py#module` -> `` via `calls_text` [candidate] 
- `pyast://backend/agent_system/models/agent_models.py#module` -> `pyast://backend/agent_system/models/agent_models.py#class:AgentLifecycleRecord` via `defines_class` [accepted] 
- `file://backend/agent_system/models/model_profile_models.py` -> `pyast://backend/agent_system/models/model_profile_models.py#module` via `defines_module` [accepted] 
- `folder://backend/agent_system/models` -> `file://backend/agent_system/models/__init__.py` via `contains_file` [accepted] Physical containment extracted from the project file tree.
