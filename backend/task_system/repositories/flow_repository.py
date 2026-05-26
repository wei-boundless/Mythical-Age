from __future__ import annotations

from pathlib import Path
from typing import Callable

from agent_system.identity import normalize_agent_id
from task_system.registry.flow_models import GeneralTaskProfile, TaskFlowDefinition
from task_system.repositories.common import merge_default_overlay_by_key, next_prefixed_id
from task_system.storage import TaskSystemStorage


class FlowRepository:
    def __init__(
        self,
        base_dir: Path,
        *,
        default_flows: Callable[[], tuple[TaskFlowDefinition, ...]],
        default_general_profiles: Callable[[], tuple[GeneralTaskProfile, ...]],
        removed_config_predicate: Callable[[dict[str, object]], bool],
    ) -> None:
        self.storage = TaskSystemStorage(base_dir)
        self.default_flows = default_flows
        self.default_general_profiles = default_general_profiles
        self.removed_config_predicate = removed_config_predicate

    def list_general_profiles(self) -> list[GeneralTaskProfile]:
        payload = self.storage.read_object(
            "general_task_profiles.json",
            {"profiles": [item.to_dict() for item in self.default_general_profiles()]},
        )
        profiles = [
            _general_profile_from_dict(item)
            for item in list(payload.get("profiles") or [])
            if isinstance(item, dict)
        ]
        normalized = [item.to_dict() for item in profiles]
        if payload.get("profiles") != normalized:
            self.storage.write_object("general_task_profiles.json", {"profiles": normalized})
        return profiles

    def get_general_profile(self, profile_id: str) -> GeneralTaskProfile | None:
        target = str(profile_id or "").strip()
        return next((item for item in self.list_general_profiles() if item.profile_id == target), None)

    def upsert_general_profile(
        self,
        *,
        profile_id: str,
        title: str,
        default_agent_id: str,
        default_workflow_id: str,
        default_projection_id: str = "",
        input_contract_id: str = "",
        output_contract_id: str = "",
        conversation_entry_policy: str = "user_dialogue_to_main_agent",
        enabled: bool = True,
        metadata: dict[str, object] | None = None,
    ) -> GeneralTaskProfile:
        target = str(profile_id or "").strip()
        if not target.startswith("general."):
            raise ValueError("profile_id must start with general.")
        profile = GeneralTaskProfile(
            profile_id=target,
            title=str(title or target).strip(),
            entry_channel="main_conversation",
            default_agent_id=normalize_agent_id(str(default_agent_id or "agent:0").strip() or "agent:0"),
            default_workflow_id=str(default_workflow_id or "").strip(),
            default_projection_id=str(default_projection_id or "").strip(),
            input_contract_id=str(input_contract_id or "").strip(),
            output_contract_id=str(output_contract_id or "").strip(),
            conversation_entry_policy=str(conversation_entry_policy or "user_dialogue_to_main_agent").strip(),
            enabled=bool(enabled),
            metadata=dict(metadata or {}),
        )
        profiles = [item for item in self.list_general_profiles() if item.profile_id != target]
        profiles.append(profile)
        self.storage.write_object("general_task_profiles.json", {"profiles": [item.to_dict() for item in profiles]})
        return profile

    def list(self) -> list[TaskFlowDefinition]:
        default_payload = [item.to_dict() for item in self.default_flows()]
        payload = self.storage.read_object("task_flows.json", {"flows": default_payload})
        merged_payload = merge_default_overlay_by_key(
            default_payload,
            [
                item
                for item in list(payload.get("flows") or [])
                if isinstance(item, dict) and not self.removed_config_predicate(item)
            ],
            key="flow_id",
        )
        flows: list[TaskFlowDefinition] = []
        for item in merged_payload:
            flows.append(
                TaskFlowDefinition(
                    flow_id=str(item.get("flow_id") or ""),
                    title=str(item.get("title") or ""),
                    input_contract_id=str(item.get("input_contract_id") or ""),
                    output_contract_id=str(item.get("output_contract_id") or ""),
                    default_agent_id=normalize_agent_id(str(item.get("default_agent_id") or "")),
                    default_workflow_id=str(item.get("default_workflow_id") or ""),
                    default_runtime_lane=str(item.get("default_runtime_lane") or ""),
                    default_memory_scope=str(item.get("default_memory_scope") or ""),
                    enabled=bool(item.get("enabled", True)),
                    metadata=dict(item.get("metadata") or {}),
                )
            )
        normalized = [item.to_dict() for item in flows]
        if payload.get("flows") != normalized:
            self.storage.write_object("task_flows.json", {"flows": normalized})
        return flows

    def get(self, flow_id: str) -> TaskFlowDefinition | None:
        target = str(flow_id or "").strip()
        return next((item for item in self.list() if item.flow_id == target), None)

    def next_id(self) -> str:
        return next_prefixed_id([item.flow_id for item in self.list()], prefix="flow.")

    def upsert(
        self,
        *,
        flow_id: str,
        title: str,
        input_contract_id: str,
        output_contract_id: str,
        default_agent_id: str,
        default_workflow_id: str,
        default_runtime_lane: str,
        default_memory_scope: str,
        enabled: bool = True,
        metadata: dict[str, object] | None = None,
    ) -> TaskFlowDefinition:
        normalized_flow_id = str(flow_id or "").strip()
        if not normalized_flow_id.startswith("flow."):
            raise ValueError("flow_id must start with flow.")
        flow = TaskFlowDefinition(
            flow_id=normalized_flow_id,
            title=str(title or normalized_flow_id).strip(),
            input_contract_id=str(input_contract_id or "").strip(),
            output_contract_id=str(output_contract_id or "").strip(),
            default_agent_id=normalize_agent_id(str(default_agent_id or "").strip()),
            default_workflow_id=str(default_workflow_id or "").strip(),
            default_runtime_lane=str(default_runtime_lane or "").strip(),
            default_memory_scope=str(default_memory_scope or "").strip(),
            enabled=bool(enabled),
            metadata=dict(metadata or {}),
        )
        flows = [item for item in self.list() if item.flow_id != normalized_flow_id]
        flows.append(flow)
        self.storage.write_object("task_flows.json", {"flows": [item.to_dict() for item in flows]})
        return flow

    def delete_many(self, flow_ids: set[str]) -> set[str]:
        targets = {str(item or "").strip() for item in flow_ids if str(item or "").strip()}
        if not targets:
            return set()
        flows = [item for item in self.list() if item.flow_id not in targets]
        self.storage.write_object("task_flows.json", {"flows": [item.to_dict() for item in flows]})
        return targets


def _general_profile_from_dict(item: dict[str, object]) -> GeneralTaskProfile:
    return GeneralTaskProfile(
        profile_id=str(item.get("profile_id") or ""),
        title=str(item.get("title") or ""),
        entry_channel=str(item.get("entry_channel") or "main_conversation"),
        default_agent_id=normalize_agent_id(str(item.get("default_agent_id") or "agent:0")),
        default_workflow_id=str(item.get("default_workflow_id") or ""),
        default_projection_id=str(item.get("default_projection_id") or ""),
        input_contract_id=str(item.get("input_contract_id") or ""),
        output_contract_id=str(item.get("output_contract_id") or ""),
        conversation_entry_policy=str(item.get("conversation_entry_policy") or "user_dialogue_to_main_agent"),
        enabled=bool(item.get("enabled", True)),
        metadata=dict(item.get("metadata") or {}),
    )
