from __future__ import annotations

from .assembly import PromptAssemblyService
from .environment_lifecycle_prompts import (
    ALL_ENVIRONMENT_LIFECYCLE_PROMPT_IDS,
    ENVIRONMENT_LIFECYCLE_PROMPT_DEFAULTS_BY_ENVIRONMENT,
    ENVIRONMENT_LIFECYCLE_PROMPT_IDS_BY_ENVIRONMENT,
    ENVIRONMENT_LIFECYCLE_PROMPT_SLOTS,
    list_builtin_environment_lifecycle_prompt_resources,
)
from .manifest import RuntimePromptManifest, build_runtime_prompt_manifest
from .models import (
    PromptAssemblyRequest,
    PromptAssemblyResult,
    PromptPack,
    PromptRule,
    PromptRuleAssemblyResult,
    PromptResource,
    PromptSection,
)
from .packs import default_pack_ref_for_invocation, list_builtin_prompt_packs, list_builtin_runtime_prompt_resources
from .personality_prompts import DEFAULT_PERSONALITY_PROMPT_REF, list_builtin_personality_prompt_resources
from .registry import PromptLibraryRegistry
from .rules import PromptRuleCompiler, list_builtin_prompt_rule_resources
from .system_prompts import FOUNDATION_PROMPT_REFS, list_builtin_system_prompt_resources
from .tool_prompts import list_builtin_tool_prompt_resources, tool_guidance_payload_for_visible_tools
from .utility_prompts import (
    DURABLE_MEMORY_RECALL_SELECTOR_PROMPT,
    EVIDENCE_DISTILLER_PROMPT,
    HISTORY_SUMMARY_RECOVERY_PROMPT,
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

__all__ = [
    "FOUNDATION_PROMPT_REFS",
    "list_builtin_system_prompt_resources",
    "ALL_ENVIRONMENT_LIFECYCLE_PROMPT_IDS",
    "ENVIRONMENT_LIFECYCLE_PROMPT_DEFAULTS_BY_ENVIRONMENT",
    "ENVIRONMENT_LIFECYCLE_PROMPT_IDS_BY_ENVIRONMENT",
    "ENVIRONMENT_LIFECYCLE_PROMPT_SLOTS",
    "list_builtin_environment_lifecycle_prompt_resources",
    "list_builtin_tool_prompt_resources",
    "tool_guidance_payload_for_visible_tools",
    "list_builtin_utility_prompt_resources",
    "RAG_FINALIZER_SYSTEM_PROMPT",
    "EVIDENCE_DISTILLER_PROMPT",
    "DURABLE_MEMORY_RECALL_SELECTOR_PROMPT",
    "SESSION_TITLE_GENERATION_PROMPT",
    "HISTORY_SUMMARY_RECOVERY_PROMPT",
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
    "default_pack_ref_for_invocation",
    "PromptLibraryRegistry",
    "PromptAssemblyService",
    "PromptAssemblyRequest",
    "PromptAssemblyResult",
    "PromptPack",
    "PromptRule",
    "PromptRuleAssemblyResult",
    "PromptRuleCompiler",
    "PromptSection",
    "PromptResource",
    "RuntimePromptManifest",
    "build_runtime_prompt_manifest",
]


