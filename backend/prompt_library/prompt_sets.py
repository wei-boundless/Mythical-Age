from __future__ import annotations

from .environment_guidance_prompts import ENVIRONMENT_GUIDANCE_PROMPT_DEFAULTS_BY_ENVIRONMENT
from .models import PromptBindingSlot, PromptSet
from .worker_prompts import WORKER_PROMPT_SPECS


_MAIN_AGENT_WORK_ROLE_REFS_BY_PROFILE = {
    "main_interactive_agent": {
        "single_agent_turn": ("agent.main_interactive_agent.single_agent_turn.work_role",),
        "tool_observation_followup": ("agent.main_interactive_agent.tool_observation_followup.work_role",),
        "task_execution": ("agent.main_interactive_agent.task_execution.work_role",),
    },
    "main_coding_agent": {
        "single_agent_turn": ("agent.main_coding_agent.single_agent_turn.work_role",),
        "tool_observation_followup": ("agent.main_coding_agent.tool_observation_followup.work_role",),
        "task_execution": ("agent.main_coding_agent.task_execution.work_role",),
    },
    "main_office_agent": {
        "single_agent_turn": ("agent.main_office_agent.single_agent_turn.work_role",),
        "tool_observation_followup": ("agent.main_office_agent.tool_observation_followup.work_role",),
        "task_execution": ("agent.main_office_agent.task_execution.work_role",),
    },
}


def list_builtin_prompt_sets() -> tuple[PromptSet, ...]:
    return (
        PromptSet(
            prompt_set_id="prompt_set.runtime.default_turn",
            owner_kind="runtime",
            owner_ref="runtime.turn",
            title="Runtime default turn prompt set",
            slots={
                "runtime_prompt_pack": PromptBindingSlot(
                    slot="runtime_prompt_pack",
                    prompt_pack_refs_by_invocation={
                        "single_agent_turn": ("runtime.pack.single_agent_turn",),
                        "task_execution": ("runtime.pack.task_execution",),
                        "tool_observation_followup": ("runtime.pack.observation_followup",),
                        "semantic_compaction": ("runtime.pack.semantic_compaction",),
                    },
                    owner_layer="runtime",
                    cache_scope="global",
                    locked=True,
                ),
            },
            policies={
                "locked_slots": [
                    "runtime_prompt_pack",
                    "action_protocol_schema",
                    "control_action_schema",
                    "output_commit_schema",
                ],
            },
        ),
        _main_agent_prompt_set(
            prompt_set_id="prompt_set.agent.main_interactive",
            agent_profile_id="main_interactive_agent",
            title="Main interactive agent prompt set",
        ),
        _main_agent_prompt_set(
            prompt_set_id="prompt_set.agent.main_coding",
            agent_profile_id="main_coding_agent",
            title="Main coding agent prompt set",
        ),
        _main_agent_prompt_set(
            prompt_set_id="prompt_set.agent.main_office",
            agent_profile_id="main_office_agent",
            title="Main office agent prompt set",
        ),
        _environment_prompt_set(
            prompt_set_id="prompt_set.environment.general",
            environment_id="env.general.workspace",
            orientation_ref="environment.general.workspace.orientation",
            title="General workspace environment prompt set",
        ),
        _environment_prompt_set(
            prompt_set_id="prompt_set.environment.coding",
            environment_id="env.coding.vibe_workspace",
            orientation_ref="environment.coding.vibe_workspace.orientation",
            title="Coding workspace environment prompt set",
        ),
        _environment_prompt_set(
            prompt_set_id="prompt_set.environment.office",
            environment_id="env.office.file_search",
            orientation_ref="environment.office.file_search.orientation",
            title="Office document processing environment prompt set",
        ),
        _single_invocation_agent_prompt_set(
            prompt_set_id="prompt_set.agent.memory_system",
            agent_profile_id="memory_system_agent",
            invocation_kind="memory_maintenance",
            prompt_ref="agent.memory_system_agent.memory_maintenance.work_role",
            title="Memory system agent prompt set",
        ),
        _single_invocation_agent_prompt_set(
            prompt_set_id="prompt_set.agent.context_compactor",
            agent_profile_id="context_compactor_agent",
            invocation_kind="semantic_compaction",
            prompt_ref="agent.context_compactor_agent.semantic_compaction.work_role",
            title="Context compactor agent prompt set",
        ),
        *tuple(
            _worker_prompt_set(
                prompt_set_id=f"prompt_set.worker.{spec.worker_kind}",
                prompt_ref=spec.prompt_id,
                worker_kind=spec.worker_kind,
                title=f"{spec.title} prompt set",
            )
            for spec in WORKER_PROMPT_SPECS
        ),
    )


def _main_agent_prompt_set(*, prompt_set_id: str, agent_profile_id: str, title: str) -> PromptSet:
    work_role_refs = _main_agent_work_role_refs(agent_profile_id)
    return PromptSet(
        prompt_set_id=prompt_set_id,
        owner_kind="agent",
        owner_ref=agent_profile_id,
        extends=("prompt_set.runtime.default_turn",),
        title=title,
        allowed_agent_refs=(agent_profile_id,),
        slots={
            "agent_work_role": PromptBindingSlot(
                slot="agent_work_role",
                prompt_refs_by_invocation=work_role_refs,
                owner_layer="agent",
                cache_scope="session",
                scope=f"agent:{agent_profile_id}",
            ),
        },
        policies={
            "allow_agent_override": ["agent_work_role", "agent_personality"],
            "locked_slots": ["runtime_prompt_pack", "action_protocol_schema", "output_commit_schema"],
        },
    )


def _main_agent_work_role_refs(agent_profile_id: str) -> dict[str, tuple[str, ...]]:
    normalized = str(agent_profile_id or "").strip()
    refs = _MAIN_AGENT_WORK_ROLE_REFS_BY_PROFILE.get(normalized)
    if refs is None:
        raise ValueError(f"missing main agent work role refs for profile: {normalized}")
    return refs


def _single_invocation_agent_prompt_set(
    *,
    prompt_set_id: str,
    agent_profile_id: str,
    invocation_kind: str,
    prompt_ref: str,
    title: str,
) -> PromptSet:
    return PromptSet(
        prompt_set_id=prompt_set_id,
        owner_kind="agent",
        owner_ref=agent_profile_id,
        extends=("prompt_set.runtime.default_turn",),
        title=title,
        allowed_agent_refs=(agent_profile_id,),
        slots={
            "agent_work_role": PromptBindingSlot(
                slot="agent_work_role",
                prompt_refs_by_invocation={invocation_kind: (prompt_ref,)},
                owner_layer="agent",
                cache_scope="session",
            ),
        },
        policies={
            "locked_slots": ["runtime_prompt_pack", "action_protocol_schema", "output_commit_schema"],
        },
    )


def _worker_prompt_set(*, prompt_set_id: str, prompt_ref: str, worker_kind: str, title: str) -> PromptSet:
    return PromptSet(
        prompt_set_id=prompt_set_id,
        owner_kind="worker",
        owner_ref=worker_kind,
        extends=("prompt_set.runtime.default_turn",),
        title=title,
        slots={
            "agent_work_role": PromptBindingSlot(
                slot="agent_work_role",
                prompt_refs_by_invocation={"task_execution": (prompt_ref,)},
                owner_layer="agent",
                cache_scope="session",
            ),
        },
        metadata={"worker_kind": worker_kind, "worker_prompt_ref": prompt_ref},
    )


def _environment_prompt_set(
    *,
    prompt_set_id: str,
    environment_id: str,
    orientation_ref: str,
    title: str,
) -> PromptSet:
    guidance_slot_refs = dict(ENVIRONMENT_GUIDANCE_PROMPT_DEFAULTS_BY_ENVIRONMENT.get(environment_id) or {})
    return PromptSet(
        prompt_set_id=prompt_set_id,
        owner_kind="environment",
        owner_ref=environment_id,
        title=title,
        allowed_environment_refs=(environment_id,),
        slots={
            "environment_orientation": PromptBindingSlot(
                slot="environment_orientation",
                prompt_refs=(orientation_ref,),
                owner_layer="environment",
                cache_scope="static_environment",
            ),
            "environment_guidance_catalog": PromptBindingSlot(
                slot="environment_guidance_catalog",
                prompt_refs=tuple(guidance_slot_refs.values()),
                owner_layer="environment",
                cache_scope="static_environment",
                visibility="metadata_only",
                contract_priority="owner_guidance",
                conflict_policy="scoped_guidance",
                scope=f"environment:{environment_id}",
                metadata={
                    "environment_id": environment_id,
                    "guidance_slot_refs": guidance_slot_refs,
                    "catalog_role": "wiring_candidate_set",
                },
            ),
        },
        metadata={
            "environment_id": environment_id,
            "environment_guidance_prompt_defaults": guidance_slot_refs,
            "environment_guidance_authority": "prompt_set",
        },
    )
