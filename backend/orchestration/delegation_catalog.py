from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from agent_system import AgentGroupRegistry, AgentRegistry, AgentRuntimeRegistry


_DEFAULT_CONTEXT_POLICY = {
    "parent_context": "minimal_task_brief",
    "child_context": "delegation_scoped",
    "return_policy": "summary_and_refs_only",
}


@dataclass(frozen=True, slots=True)
class DelegationCard:
    agent_id: str
    agent_name: str
    agent_category: str
    enabled: bool
    callable: bool
    availability_state: str
    unavailable_reasons: tuple[str, ...] = ()
    group_ids: tuple[str, ...] = ()
    when_to_use: str = ""
    delegation_kinds: tuple[str, ...] = ()
    allowed_operations: tuple[str, ...] = ()
    blocked_operations: tuple[str, ...] = ()
    context_policy: dict[str, Any] = field(default_factory=dict)
    input_contract: dict[str, Any] = field(default_factory=dict)
    output_contract: dict[str, Any] = field(default_factory=dict)
    runtime_profile_ref: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "orchestration.delegation_card"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in ("unavailable_reasons", "group_ids", "delegation_kinds", "allowed_operations", "blocked_operations"):
            payload[key] = list(payload[key])
        return payload


class DelegationCatalogBuilder:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.agent_registry = AgentRegistry(self.base_dir)
        self.runtime_registry = AgentRuntimeRegistry(self.base_dir)
        self.group_registry = AgentGroupRegistry(self.base_dir)

    def build(self, *, parent_agent_id: str = "") -> dict[str, Any]:
        agents = self.agent_registry.list_agents()
        profiles = {item.agent_id: item for item in self.runtime_registry.list_profiles()}
        group_ids_by_agent = self._group_ids_by_agent()
        parent_profile = self.runtime_registry.get_profile(parent_agent_id) if str(parent_agent_id or "").strip() else None
        parent_gate = self._parent_gate(parent_agent_id=parent_agent_id, parent_profile=parent_profile)
        if parent_gate["blocked_reasons"]:
            return {
                "authority": "orchestration.delegation_catalog",
                "delegate_cards": [],
                "summary": {
                    "delegate_card_count": 0,
                    "callable_count": 0,
                    "blocked_count": 0,
                    "parent_agent_id": str(parent_agent_id or "").strip(),
                    "blocked_reasons": list(parent_gate["blocked_reasons"]),
                },
            }
        cards = tuple(
            self._card_for_agent(
                agent=agent,
                runtime_profile=profiles.get(agent.agent_id),
                group_ids=tuple(group_ids_by_agent.get(agent.agent_id, ())),
                parent_gate=parent_gate,
            )
            for agent in agents
            if agent.delegation_enabled
        )
        return {
            "authority": "orchestration.delegation_catalog",
            "delegate_cards": [item.to_dict() for item in cards],
            "summary": {
                "delegate_card_count": len(cards),
                "callable_count": sum(1 for item in cards if item.callable),
                "blocked_count": sum(1 for item in cards if not item.callable),
                "parent_agent_id": str(parent_agent_id or "").strip(),
            },
        }

    def preview(self, *, target_agent_id: str, delegation_kind: str = "", parent_agent_id: str = "") -> dict[str, Any]:
        catalog = self.build(parent_agent_id=parent_agent_id)
        cards = [dict(item) for item in list(catalog.get("delegate_cards") or [])]
        target = str(target_agent_id or "").strip()
        card = next((item for item in cards if str(item.get("agent_id") or "") == target), None)
        if card is None:
            blocked = list(dict(catalog.get("summary") or {}).get("blocked_reasons") or [])
            return {
                "callable": False,
                "blocked_reasons": blocked or ["target_agent_unavailable"],
                "effective_operations": [],
                "missing_requirements": blocked or ["target_agent_not_in_delegation_catalog"],
                "authority": "orchestration.delegation_catalog_preview",
            }
        blocked_reasons = list(card.get("unavailable_reasons") or [])
        kind = str(delegation_kind or "").strip()
        if kind and kind not in set(str(item) for item in list(card.get("delegation_kinds") or [])):
            blocked_reasons.append("delegation_kind_not_allowed")
        return {
            "callable": bool(card.get("callable") is True and not blocked_reasons),
            "blocked_reasons": blocked_reasons,
            "effective_operations": _effective_operations(
                tuple(str(item) for item in list(card.get("allowed_operations") or [])),
                tuple(str(item) for item in list(card.get("blocked_operations") or [])),
            ),
            "missing_requirements": blocked_reasons,
            "card": card,
            "authority": "orchestration.delegation_catalog_preview",
        }

    def _card_for_agent(
        self,
        *,
        agent: Any,
        runtime_profile: Any | None,
        group_ids: tuple[str, ...],
        parent_gate: dict[str, Any] | None = None,
    ) -> DelegationCard:
        unavailable: list[str] = []
        if not bool(getattr(agent, "enabled", False)):
            unavailable.append("target_agent_disabled")
        if not bool(getattr(agent, "delegation_enabled", False)):
            unavailable.append("target_agent_delegation_disabled")
        parent_gate = dict(parent_gate or {})
        allowed_ids = set(str(item).strip() for item in list(parent_gate.get("allowed_delegate_agent_ids") or []) if str(item).strip())
        agent_id = str(getattr(agent, "agent_id", "") or "")
        if allowed_ids and agent_id not in allowed_ids:
            unavailable.append("target_agent_not_allowed_by_parent")
        if runtime_profile is None:
            unavailable.append("target_runtime_profile_missing")
            allowed_operations: tuple[str, ...] = ()
            blocked_operations: tuple[str, ...] = ()
            runtime_profile_ref = ""
            metadata: dict[str, Any] = {}
        else:
            if str(getattr(runtime_profile, "lifecycle_policy", "") or "") == "disabled":
                unavailable.append("target_runtime_profile_disabled")
            allowed_operations = tuple(getattr(runtime_profile, "allowed_operations", ()) or ())
            blocked_operations = tuple(getattr(runtime_profile, "blocked_operations", ()) or ())
            runtime_profile_ref = str(getattr(runtime_profile, "agent_profile_id", "") or "")
            metadata = dict(getattr(runtime_profile, "metadata", {}) or {})
        effective_operations = _effective_operations(allowed_operations, blocked_operations)
        if not effective_operations:
            unavailable.append("target_operations_empty")
        delegation_kinds = _delegation_kinds(metadata, allowed_operations)
        return DelegationCard(
            agent_id=str(getattr(agent, "agent_id", "") or ""),
            agent_name=str(getattr(agent, "agent_name", "") or ""),
            agent_category=str(getattr(agent, "agent_category", "") or ""),
            enabled=bool(getattr(agent, "enabled", False)),
            callable=not unavailable,
            availability_state="available" if not unavailable else "blocked",
            unavailable_reasons=tuple(dict.fromkeys(unavailable)),
            group_ids=group_ids,
            when_to_use=_when_to_use(agent=agent, metadata=metadata),
            delegation_kinds=delegation_kinds,
            allowed_operations=allowed_operations,
            blocked_operations=blocked_operations,
            context_policy=dict(_DEFAULT_CONTEXT_POLICY),
            input_contract={
                "required": ["question"],
                "optional": ["scope", "expected_output", "constraints", "file_refs", "data_refs"],
            },
            output_contract={
                "required": ["summary"],
                "optional": ["answer_candidate", "evidence_refs", "artifact_refs", "confidence", "limitations"],
            },
            runtime_profile_ref=runtime_profile_ref,
            metadata={
                key: value
                for key, value in metadata.items()
                if key in {"worker_kind", "delegation_kind", "delegation_kinds"}
            },
        )

    def _group_ids_by_agent(self) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for group in self.group_registry.list_groups():
            for agent_id in tuple(getattr(group, "member_agent_ids", ()) or ()):
                result.setdefault(agent_id, []).append(group.group_id)
        return result

    def _parent_gate(self, *, parent_agent_id: str, parent_profile: Any | None) -> dict[str, Any]:
        target = str(parent_agent_id or "").strip()
        if not target:
            return {
                "blocked_reasons": [],
                "allowed_delegate_agent_ids": (),
            }
        blocked_reasons: list[str] = []
        if parent_profile is None:
            blocked_reasons.append("parent_runtime_profile_missing")
            return {
                "blocked_reasons": blocked_reasons,
                "allowed_delegate_agent_ids": (),
            }
        if not bool(getattr(parent_profile, "can_delegate_to_agents", False)):
            blocked_reasons.append("parent_delegation_not_authorized")
        allowed_operations = {str(item).strip() for item in tuple(getattr(parent_profile, "allowed_operations", ()) or ()) if str(item).strip()}
        blocked_operations = {str(item).strip() for item in tuple(getattr(parent_profile, "blocked_operations", ()) or ()) if str(item).strip()}
        if "op.delegate_to_agent" not in allowed_operations or "op.delegate_to_agent" in blocked_operations:
            blocked_reasons.append("parent_delegate_operation_not_allowed")
        return {
            "blocked_reasons": list(dict.fromkeys(blocked_reasons)),
            "allowed_delegate_agent_ids": tuple(getattr(parent_profile, "allowed_delegate_agent_ids", ()) or ()),
        }


def build_delegation_catalog(base_dir: Path) -> dict[str, Any]:
    return DelegationCatalogBuilder(base_dir).build()


def _effective_operations(allowed: tuple[str, ...], blocked: tuple[str, ...]) -> list[str]:
    blocked_set = {str(item).strip() for item in blocked if str(item).strip()}
    return [
        str(item).strip()
        for item in allowed
        if str(item).strip() and str(item).strip() not in blocked_set
    ]


def _delegation_kinds(metadata: dict[str, Any], allowed_operations: tuple[str, ...]) -> tuple[str, ...]:
    explicit = [
        str(item).strip()
        for item in list(metadata.get("delegation_kinds") or [])
        if str(item).strip()
    ]
    single = str(metadata.get("delegation_kind") or "").strip()
    if single:
        explicit.append(single)
    if explicit:
        return tuple(dict.fromkeys(explicit))
    operations = set(allowed_operations)
    kinds: list[str] = []
    if "op.mcp_retrieval" in operations:
        kinds.append("evidence_lookup")
    if "op.mcp_pdf" in operations:
        kinds.append("pdf_reading")
    if "op.mcp_structured_data" in operations:
        kinds.append("structured_data_lookup")
    return tuple(kinds or ["bounded_analysis"])


def _when_to_use(*, agent: Any, metadata: dict[str, Any]) -> str:
    hint = str(metadata.get("when_to_use") or "").strip()
    if hint:
        return hint
    worker_kind = str(metadata.get("worker_kind") or "").strip()
    if worker_kind == "rag_analysis":
        return "当任务需要检索本地知识库并返回可引用证据摘要时使用。"
    if worker_kind == "pdf_analysis":
        return "当任务需要阅读 PDF、定位页码或抽取文档证据时使用。"
    if worker_kind == "structured_data_analysis":
        return "当任务需要读取表格或结构化数据并返回统计依据时使用。"
    return str(getattr(agent, "description", "") or "").strip()
