# Project Network Layer: directory

- build_id: `agent_system_models_control_network_ast_live_20260702_063038`
- node_count: 3
- edge_count: 7

## Nodes

- `folder://backend` [directory; resolved] backend: Physical directory in the project control network.
- `folder://backend/agent_system` [directory; resolved] backend/agent_system: Physical directory in the project control network.
- `folder://backend/agent_system/models` [directory; resolved] Agent System Models Directory: Defines data models for agent descriptors, lifecycle records, model profiles, and a resolver for LLM model specifications.

## Edges

- `folder://backend/agent_system/models` -> `file://backend/agent_system/models/model_profile_resolver.py` via `contains_file` [accepted] Physical containment extracted from the project file tree.
- `folder://backend/agent_system/models` -> `file://backend/agent_system/models/agent_models.py` via `contains_file` [accepted] Physical containment extracted from the project file tree.
- `folder://backend/agent_system/models` -> `file://backend/agent_system/models/model_profile_models.py` via `contains_file` [accepted] Physical containment extracted from the project file tree.
- `folder://backend` -> `folder://backend/agent_system` via `contains_directory` [accepted] Physical containment extracted from the project file tree.
- `folder://backend/agent_system` -> `folder://backend/agent_system/models` via `contains_directory` [accepted] Physical containment extracted from the project file tree.
- `folder://.` -> `folder://backend` via `contains_directory` [accepted] Physical containment extracted from the project file tree.
- `folder://backend/agent_system/models` -> `file://backend/agent_system/models/__init__.py` via `contains_file` [accepted] Physical containment extracted from the project file tree.
