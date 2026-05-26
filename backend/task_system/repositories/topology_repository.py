from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from agent_system.identity import normalize_agent_id, normalize_agent_id_sequence
from task_system.registry.flow_models import TopologyTemplate
from task_system.repositories.common import merge_authoritative_defaults_by_key, next_prefixed_id
from task_system.storage import TaskSystemStorage


class TopologyRepository:
    def __init__(
        self,
        base_dir: Path,
        *,
        default_topologies: Callable[[], tuple[TopologyTemplate, ...]],
    ) -> None:
        self.storage = TaskSystemStorage(base_dir)
        self.default_topologies = default_topologies

    def list(self) -> list[TopologyTemplate]:
        default_payload = [item.to_dict() for item in self.default_topologies()]
        payload = self.storage.read_object(
            "topology_templates.json",
            {"topology_templates": default_payload},
        )
        merged_payload = merge_authoritative_defaults_by_key(
            default_payload,
            [item for item in list(payload.get("topology_templates") or []) if isinstance(item, dict)],
            key="template_id",
        )
        templates: list[TopologyTemplate] = []
        for item in merged_payload:
            templates.append(
                TopologyTemplate(
                    template_id=str(item.get("template_id") or ""),
                    title=str(item.get("title") or ""),
                    nodes=tuple(_normalize_agent_refs_in_mapping(dict(value)) for value in list(item.get("nodes") or []) if isinstance(value, dict)),
                    edges=tuple(dict(value) for value in list(item.get("edges") or []) if isinstance(value, dict)),
                    handoff_rules=tuple(dict(value) for value in list(item.get("handoff_rules") or []) if isinstance(value, dict)),
                    join_policy=str(item.get("join_policy") or "explicit_join"),
                    failure_policy=str(item.get("failure_policy") or "fail_closed"),
                    terminal_policy=str(item.get("terminal_policy") or "coordinator_terminal"),
                    enabled=bool(item.get("enabled", False)),
                    metadata=dict(item.get("metadata") or {}),
                )
            )
        normalized = [item.to_dict() for item in templates]
        if payload.get("topology_templates") != normalized:
            self.storage.write_object("topology_templates.json", {"topology_templates": normalized})
        return templates

    def get(self, template_id: str) -> TopologyTemplate | None:
        target = str(template_id or "").strip()
        return next((item for item in self.list() if item.template_id == target), None)

    def next_id(self) -> str:
        return next_prefixed_id([item.template_id for item in self.list()], prefix="topology.")

    def upsert(
        self,
        *,
        template_id: str,
        title: str,
        nodes: tuple[dict[str, Any], ...] = (),
        edges: tuple[dict[str, Any], ...] = (),
        handoff_rules: tuple[dict[str, Any], ...] = (),
        join_policy: str = "explicit_join",
        failure_policy: str = "fail_closed",
        terminal_policy: str = "coordinator_terminal",
        enabled: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> TopologyTemplate:
        target = str(template_id or "").strip()
        if not target.startswith("topology."):
            raise ValueError("template_id must start with topology.")
        template = TopologyTemplate(
            template_id=target,
            title=str(title or target).strip(),
            nodes=tuple(_normalize_agent_refs_in_mapping(dict(item)) for item in nodes if isinstance(item, dict)),
            edges=tuple(dict(item) for item in edges if isinstance(item, dict)),
            handoff_rules=tuple(dict(item) for item in handoff_rules if isinstance(item, dict)),
            join_policy=str(join_policy or "explicit_join").strip(),
            failure_policy=str(failure_policy or "fail_closed").strip(),
            terminal_policy=str(terminal_policy or "coordinator_terminal").strip(),
            enabled=bool(enabled),
            metadata=dict(metadata or {}),
        )
        templates = [item for item in self.list() if item.template_id != target]
        templates.append(template)
        self.storage.write_object("topology_templates.json", {"topology_templates": [item.to_dict() for item in templates]})
        return template

    def delete_many(self, template_ids: set[str]) -> set[str]:
        targets = {str(item or "").strip() for item in template_ids if str(item or "").strip()}
        if not targets:
            return set()
        templates = [item for item in self.list() if item.template_id not in targets]
        self.storage.write_object("topology_templates.json", {"topology_templates": [item.to_dict() for item in templates]})
        return targets


def _normalize_agent_refs_in_mapping(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    if "agent_id" in normalized:
        normalized["agent_id"] = normalize_agent_id(str(normalized.get("agent_id") or ""))
    if "agent_ids" in normalized:
        normalized["agent_ids"] = list(normalize_agent_id_sequence(str(item) for item in list(normalized.get("agent_ids") or [])))
    if "participant_agent_ids" in normalized:
        normalized["participant_agent_ids"] = list(
            normalize_agent_id_sequence(str(item) for item in list(normalized.get("participant_agent_ids") or []))
        )
    return normalized
