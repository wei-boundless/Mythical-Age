from __future__ import annotations

from .assembly import PromptAssemblyService
from .descriptor_resolver import PromptDescriptor, PromptDescriptorResolver
from .environment_guidance_prompts import (
    ALL_ENVIRONMENT_GUIDANCE_PROMPT_IDS,
    ENVIRONMENT_GUIDANCE_PROMPT_DEFAULTS_BY_ENVIRONMENT,
    ENVIRONMENT_GUIDANCE_PROMPT_IDS_BY_ENVIRONMENT,
    ENVIRONMENT_GUIDANCE_PROMPT_SLOTS,
    list_builtin_environment_guidance_prompt_resources,
)
from .manifest import RuntimePromptManifest, build_runtime_prompt_manifest
from .models import (
    PromptAssemblyRequest,
    PromptAssemblyResult,
    PromptPack,
    PromptRule,
    PromptRuleAssemblyResult,
    PromptResource,
    PromptResourceOrigin,
    PromptSection,
    PromptSet,
    PromptBindingSlot,
    AgentPromptBinding,
    RuntimePromptWiringPlan,
    PromptWiringBinding,
)
from .taxonomy import (
    CONFLICT_POLICIES,
    CONTRACT_PRIORITIES,
    CONTRACT_PRIORITY_PRECEDENCE,
    PROMPT_LAYERS,
    PROMPT_VISIBILITIES,
    contract_priority_rank,
    normalize_conflict_policy,
    normalize_contract_priority,
    normalize_prompt_scope,
)
from .packs import default_pack_ref_for_invocation, list_builtin_prompt_packs, list_builtin_runtime_prompt_resources
from .personality_prompts import DEFAULT_PERSONALITY_PROMPT_REF, list_builtin_personality_prompt_resources
from .prompt_sets import list_builtin_prompt_sets
from .registry import PromptLibraryRegistry
from .rules import PromptRuleCompiler, list_builtin_prompt_rule_resources
from .system_prompts import FOUNDATION_PROMPT_REFS, list_builtin_system_prompt_resources
from .tool_prompts import list_builtin_tool_prompt_resources, tool_guidance_payload_for_visible_tools
from .strategy_prototypes import StrategyPrototype, get_strategy_prototype, strategy_prototype_for_task_goal
from .utility_prompts import (
    DURABLE_MEMORY_RECALL_SELECTOR_PROMPT,
    EVIDENCE_DISTILLER_PROMPT,
    MCP_CAPABILITY_USAGE_PROMPT,
    MCP_SERVER_INSTRUCTIONS_PROMPT,
    RAG_FINALIZER_SYSTEM_PROMPT,
    READONLY_DELIVERY_VERIFIER_ROLE_PROMPT,
    READONLY_PLANNER_ROLE_PROMPT,
    SESSION_TITLE_GENERATION_PROMPT,
    SINGLE_AGENT_ADMISSION_REPAIR_PROMPT,
    SINGLE_AGENT_PROTOCOL_REPAIR_PROMPT,
    TASK_ACTION_JSON_REPAIR_PROMPT,
    list_builtin_utility_prompt_resources,
)
from .worker_prompts import (
    WORKER_PROMPT_REFS_BY_BLUEPRINT,
    list_builtin_worker_prompt_resources,
    worker_agent_description_for_blueprint,
    worker_prompt_metadata_for_blueprint,
    worker_prompt_ref_for_blueprint,
)
from .wiring import (
    CORE_RUNTIME_SCHEMA_REFS,
    agent_prompt_binding_from_profile,
    build_runtime_prompt_wiring_plan,
)

__all__ = [
    "FOUNDATION_PROMPT_REFS",
    "list_builtin_system_prompt_resources",
    "ALL_ENVIRONMENT_GUIDANCE_PROMPT_IDS",
    "ENVIRONMENT_GUIDANCE_PROMPT_DEFAULTS_BY_ENVIRONMENT",
    "ENVIRONMENT_GUIDANCE_PROMPT_IDS_BY_ENVIRONMENT",
    "ENVIRONMENT_GUIDANCE_PROMPT_SLOTS",
    "list_builtin_environment_guidance_prompt_resources",
    "list_builtin_tool_prompt_resources",
    "tool_guidance_payload_for_visible_tools",
    "StrategyPrototype",
    "get_strategy_prototype",
    "strategy_prototype_for_task_goal",
    "list_builtin_utility_prompt_resources",
    "RAG_FINALIZER_SYSTEM_PROMPT",
    "EVIDENCE_DISTILLER_PROMPT",
    "DURABLE_MEMORY_RECALL_SELECTOR_PROMPT",
    "SESSION_TITLE_GENERATION_PROMPT",
    "READONLY_PLANNER_ROLE_PROMPT",
    "READONLY_DELIVERY_VERIFIER_ROLE_PROMPT",
    "SINGLE_AGENT_ADMISSION_REPAIR_PROMPT",
    "SINGLE_AGENT_PROTOCOL_REPAIR_PROMPT",
    "TASK_ACTION_JSON_REPAIR_PROMPT",
    "MCP_SERVER_INSTRUCTIONS_PROMPT",
    "MCP_CAPABILITY_USAGE_PROMPT",
    "DEFAULT_PERSONALITY_PROMPT_REF",
    "list_builtin_personality_prompt_resources",
    "WORKER_PROMPT_REFS_BY_BLUEPRINT",
    "list_builtin_worker_prompt_resources",
    "worker_agent_description_for_blueprint",
    "worker_prompt_metadata_for_blueprint",
    "worker_prompt_ref_for_blueprint",
    "list_builtin_runtime_prompt_resources",
    "list_builtin_prompt_rule_resources",
    "list_builtin_prompt_packs",
    "list_builtin_prompt_sets",
    "default_pack_ref_for_invocation",
    "PromptLibraryRegistry",
    "PromptAssemblyService",
    "PromptDescriptor",
    "PromptDescriptorResolver",
    "PromptAssemblyRequest",
    "PromptAssemblyResult",
    "PromptPack",
    "PromptRule",
    "PromptRuleAssemblyResult",
    "PromptRuleCompiler",
    "PromptSection",
    "PromptResource",
    "PromptResourceOrigin",
    "PromptSet",
    "PromptBindingSlot",
    "AgentPromptBinding",
    "RuntimePromptWiringPlan",
    "PromptWiringBinding",
    "RuntimePromptManifest",
    "build_runtime_prompt_manifest",
    "PROMPT_LAYERS",
    "PROMPT_VISIBILITIES",
    "CONTRACT_PRIORITIES",
    "CONTRACT_PRIORITY_PRECEDENCE",
    "CONFLICT_POLICIES",
    "contract_priority_rank",
    "normalize_contract_priority",
    "normalize_conflict_policy",
    "normalize_prompt_scope",
    "CORE_RUNTIME_SCHEMA_REFS",
    "agent_prompt_binding_from_profile",
    "build_runtime_prompt_wiring_plan",
]

