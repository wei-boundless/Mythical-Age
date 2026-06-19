from __future__ import annotations

import logging
from typing import Any, Callable

from request_intent.memory_intent import analyze_memory_intent

from .environment_context import resolve_memory_environment_context
from .runtime_view import normalize_memory_layers


class RuntimeMemoryContextProvider:
    """Bridge runtime turn facts into the read-only memory bundle service."""

    def __init__(
        self,
        *,
        bundle_service_getter: Callable[[], Any],
        session_record_loader: Callable[[str], dict[str, Any]],
        recent_messages_loader: Callable[[str], list[dict[str, Any]]] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._bundle_service_getter = bundle_service_getter
        self._session_record_loader = session_record_loader
        self._recent_messages_loader = recent_messages_loader
        self._logger = logger or logging.getLogger(__name__)

    def environment_context(
        self,
        *,
        session_id: str,
        turn_id: str = "",
        task_run_id: str = "",
        main_context: dict[str, Any] | None = None,
        environment_binding: dict[str, Any] | None = None,
        active_work_context: dict[str, Any] | None = None,
        recent_work_outcome: dict[str, Any] | None = None,
        runtime_assembly: Any | None = None,
    ) -> dict[str, Any]:
        return resolve_memory_environment_context(
            main_context=main_context,
            runtime_assembly=runtime_assembly,
            session_record=self._load_session_record(session_id),
            turn_id=turn_id,
            task_run_id=task_run_id,
            environment_binding=environment_binding,
            active_work_context=active_work_context,
            recent_work_outcome=recent_work_outcome,
        ).to_dict()

    async def for_turn(
        self,
        *,
        session_id: str,
        turn_id: str,
        user_message: str,
        session_context: dict[str, Any],
        agent_runtime_profile: Any,
        runtime_assembly: Any,
        environment_binding: dict[str, Any] | None,
        active_work_context: dict[str, Any] | None,
        recent_work_outcome: dict[str, Any] | None,
    ) -> dict[str, Any]:
        memory_intent = analyze_memory_intent(user_message)
        if bool(getattr(memory_intent, "ignore_memory", False)):
            return {}
        environment_context = self.environment_context(
            session_id=session_id,
            turn_id=turn_id,
            environment_binding=environment_binding,
            active_work_context=active_work_context,
            recent_work_outcome=recent_work_outcome,
            runtime_assembly=runtime_assembly,
        )
        allow_long_term = _profile_allows_long_term_memory(agent_runtime_profile) and (
            _memory_intent_requests_read(memory_intent)
            or should_consider_long_term_memory(
                user_message=user_message,
                active_work_context=active_work_context,
                recent_work_outcome=recent_work_outcome,
            )
        )
        requested_layers = ["state"]
        if allow_long_term:
            requested_layers.append("long_term")
        memory_request_profile = {
            "profile_id": f"runtime-memory:{_agent_profile_ref(agent_runtime_profile)}:single_agent_turn",
            "task_id": "single_agent_turn",
            "requested_memory_layers": requested_layers,
            "requested_topics": _runtime_memory_topics(
                environment_context=environment_context,
                memory_intent=memory_intent,
                fallback="single_agent_turn",
            ),
            "allow_long_term_memory": allow_long_term,
            "memory_read_mode": str(getattr(memory_intent, "memory_read_mode", "") or ("task_relevant" if allow_long_term else "state")),
            "task_environment_id": str(environment_context.get("task_environment_id") or ""),
            "environment_kind": str(environment_context.get("environment_kind") or ""),
            "project_id": str(environment_context.get("project_id") or ""),
            "turn_environment_snapshot": dict(environment_context),
            "global_common_allowed": True,
            "session_summary": str(session_context.get("compressed_context") or ""),
            "main_context": _runtime_memory_main_context(
                invocation_kind="single_agent_turn",
                environment_context=environment_context,
                active_work_context=active_work_context,
                recent_work_outcome=recent_work_outcome,
                turn_input_facts=dict(session_context.get("turn_input_facts") or {}),
            ),
            "recent_tools": _recent_tool_names_from_messages(self._load_recent_messages(session_id)),
        }
        return await self._build_runtime_memory_context(
            session_id=session_id,
            query=user_message,
            memory_intent=memory_intent,
            memory_request_profile=memory_request_profile,
        )

    async def for_task_execution(self, payload: dict[str, Any]) -> dict[str, Any]:
        task_run = dict(payload.get("task_run") or {})
        contract = dict(payload.get("contract") or {})
        runtime_assembly = payload.get("runtime_assembly")
        assembly_payload = runtime_assembly.to_dict() if hasattr(runtime_assembly, "to_dict") else dict(runtime_assembly or {})
        agent_profile = payload.get("agent_runtime_profile")
        session_id = str(payload.get("session_id") or task_run.get("session_id") or "")
        task_run_id = str(task_run.get("task_run_id") or payload.get("task_run_id") or "")
        turn_id = str(dict(task_run.get("diagnostics") or {}).get("turn_id") or task_run.get("task_id") or task_run_id)
        inherited_start_context = dict(payload.get("inherited_start_context") or {})
        inherited_memory_context = _inherited_memory_context_for_profile(inherited_start_context)
        environment_context = self.environment_context(
            session_id=session_id,
            turn_id=turn_id,
            task_run_id=task_run_id,
            main_context={
                "task_environment": dict(assembly_payload.get("task_environment") or {}),
                "task_run_id": task_run_id,
            },
            runtime_assembly=assembly_payload,
        )
        base_profile = _task_memory_request_profile_from_payload(task_run=task_run, contract=contract)
        requested_layers = _task_runtime_requested_memory_layers(
            base_profile,
            agent_runtime_profile=agent_profile,
        )
        if not requested_layers:
            return {}
        allow_long_term = "long_term" in requested_layers and not bool(base_profile.get("ignore_memory", False))
        memory_request_profile = {
            **base_profile,
            "profile_id": str(base_profile.get("profile_id") or f"runtime-memory:{task_run_id}:task_execution"),
            "task_id": str(base_profile.get("task_id") or task_run.get("task_id") or task_run_id or "task_execution"),
            "task_run_id": task_run_id,
            "requested_memory_layers": requested_layers,
            "requested_topics": _dedupe_strings(
                [
                    *list(base_profile.get("requested_topics") or ()),
                    *_runtime_memory_topics(
                        environment_context=environment_context,
                        memory_intent=None,
                        fallback=str(task_run.get("task_id") or "task_execution"),
                    ),
                ]
            ),
            "allow_long_term_memory": allow_long_term,
            "memory_read_mode": str(base_profile.get("memory_read_mode") or ("task_relevant" if allow_long_term else "state")),
            "task_environment_id": str(environment_context.get("task_environment_id") or ""),
            "environment_kind": str(environment_context.get("environment_kind") or ""),
            "project_id": str(environment_context.get("project_id") or ""),
            "turn_environment_snapshot": dict(environment_context),
            "global_common_allowed": bool(base_profile.get("global_common_allowed", True)),
            "main_context": _runtime_memory_main_context(
                invocation_kind="task_execution",
                environment_context=environment_context,
                active_work_context=None,
                recent_work_outcome=None,
                turn_input_facts={},
                task_run=task_run,
                contract=contract,
                inherited_start_context=inherited_start_context,
            ),
            "inherited_context": inherited_memory_context,
            "task_summaries": _dedupe_task_summaries(
                [
                    *_task_memory_summaries_from_inherited_context(inherited_start_context),
                    *_task_memory_summaries_from_observations(payload.get("observations")),
                ]
            ),
            "recent_tools": _dedupe_strings(
                [
                    *_recent_tool_names_from_inherited_context(inherited_start_context),
                    *_recent_tool_names_from_observations(payload.get("observations")),
                ]
            )[-8:],
        }
        query = _task_memory_query(task_run=task_run, contract=contract)
        return await self._build_runtime_memory_context(
            session_id=session_id,
            query=query,
            memory_intent=None,
            memory_request_profile=memory_request_profile,
        )

    async def _build_runtime_memory_context(
        self,
        *,
        session_id: str,
        query: str,
        memory_intent: Any | None,
        memory_request_profile: dict[str, Any],
        note_limit: int = 5,
    ) -> dict[str, Any]:
        bundle_service = self._bundle_service_getter()
        if bundle_service is None:
            return _unavailable_runtime_memory_context_payload(
                memory_request_profile,
                reason_code="memory_bundle_service_unavailable",
            )
        try:
            memory_view = await bundle_service.abuild_memory_runtime_view(
                session_id=session_id,
                query=query,
                memory_intent=memory_intent,
                memory_request_profile=memory_request_profile,
                note_limit=note_limit,
            )
            context_result = await bundle_service.abuild_memory_context_package_result(
                session_id=session_id,
                query=query,
                memory_intent=memory_intent,
                memory_request_profile=memory_request_profile,
                memory_view=memory_view,
                note_limit=note_limit,
            )
        except ValueError:
            self._logger.exception("runtime memory context profile rejected")
            raise
        except Exception as exc:
            self._logger.warning("runtime memory context supply failed: %s", exc, exc_info=True)
            return _unavailable_runtime_memory_context_payload(
                memory_request_profile,
                reason_code="memory_context_supply_failed",
            )
        return _runtime_memory_context_payload(context_result, memory_view)

    def _load_session_record(self, session_id: str) -> dict[str, Any]:
        try:
            record = self._session_record_loader(session_id)
        except Exception:
            return {}
        return dict(record or {}) if isinstance(record, dict) else {}

    def _load_recent_messages(self, session_id: str) -> list[dict[str, Any]]:
        if self._recent_messages_loader is None:
            return []
        try:
            return [
                dict(item)
                for item in list(self._recent_messages_loader(session_id) or [])
                if isinstance(item, dict)
            ]
        except Exception:
            return []


def should_inject_session_emphasis(
    *,
    user_message: str,
    active_work_context: dict[str, Any] | None,
    recent_work_outcome: dict[str, Any] | None,
) -> bool:
    if active_work_context or recent_work_outcome:
        return True
    content = str(user_message or "").strip().lower()
    if not content:
        return False
    task_terms = (
        "继续",
        "执行",
        "开始",
        "修改",
        "修复",
        "重构",
        "实现",
        "落地",
        "测试",
        "检查",
        "审查",
        "计划",
        "继续做",
        "continue",
        "implement",
        "fix",
        "refactor",
        "test",
        "review",
    )
    return any(term in content for term in task_terms)


def should_consider_long_term_memory(
    *,
    user_message: str,
    active_work_context: dict[str, Any] | None,
    recent_work_outcome: dict[str, Any] | None,
) -> bool:
    if active_work_context or recent_work_outcome:
        return True
    content = str(user_message or "").strip().lower()
    if not content:
        return False
    memory_terms = (
        "长期记忆",
        "记忆",
        "记住",
        "请记住",
        "偏好",
        "以后",
        "始终",
        "上次",
        "之前",
        "以前",
        "历史",
        "规则",
        "约定",
        "remember",
        "memory",
        "preference",
        "always",
        "previous",
        "history",
    )
    return any(term in content for term in memory_terms)


def _profile_allows_long_term_memory(agent_runtime_profile: Any) -> bool:
    scopes = {
        str(item or "").strip()
        for item in list(getattr(agent_runtime_profile, "allowed_memory_scopes", ()) or ())
        if str(item or "").strip()
    }
    return bool(scopes & {"long_term", "long_term_candidate", "durable", "durable_candidate"})


def _agent_profile_ref(agent_runtime_profile: Any) -> str:
    return str(
        getattr(agent_runtime_profile, "agent_profile_id", "")
        or getattr(agent_runtime_profile, "agent_id", "")
        or "agent"
    )


def _memory_intent_requests_read(memory_intent: Any | None) -> bool:
    if memory_intent is None:
        return False
    mode = str(getattr(memory_intent, "memory_read_mode", "") or "").strip()
    return bool(mode and mode != "none") or bool(getattr(memory_intent, "explicit_read_inventory", False))


def _runtime_memory_topics(
    *,
    environment_context: dict[str, Any],
    memory_intent: Any | None,
    fallback: str,
) -> list[str]:
    topics = [
        str(environment_context.get("task_environment_id") or ""),
        str(environment_context.get("environment_kind") or ""),
        str(environment_context.get("project_id") or ""),
        str(fallback or ""),
    ]
    if memory_intent is not None:
        topics.extend(str(item) for item in list(getattr(memory_intent, "preferred_types", []) or ()))
        topics.extend(str(item) for item in list(getattr(memory_intent, "preferred_memory_classes", []) or ()))
    return _dedupe_strings(topics)


def _runtime_memory_main_context(
    *,
    invocation_kind: str,
    environment_context: dict[str, Any],
    active_work_context: dict[str, Any] | None,
    recent_work_outcome: dict[str, Any] | None,
    turn_input_facts: dict[str, Any],
    task_run: dict[str, Any] | None = None,
    contract: dict[str, Any] | None = None,
    inherited_start_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "invocation_kind": invocation_kind,
        "task_environment": {
            "task_environment_id": str(environment_context.get("task_environment_id") or ""),
            "environment_kind": str(environment_context.get("environment_kind") or ""),
            "project_id": str(environment_context.get("project_id") or ""),
        },
        "turn_input": _compact_mapping(turn_input_facts, keys=("user_intent", "environment_binding", "expected_active_turn_id")),
        "active_work": _compact_mapping(
            active_work_context or {},
            keys=("task_run_id", "task_id", "status", "current_step", "summary"),
        ),
        "recent_work_outcome": _compact_mapping(
            recent_work_outcome or {},
            keys=("task_run_id", "task_id", "status", "terminal_reason", "summary"),
        ),
    }
    if task_run:
        payload["task_run"] = _compact_mapping(
            task_run,
            keys=("task_run_id", "task_id", "status", "agent_id", "agent_profile_id"),
        )
    if contract:
        payload["contract"] = _compact_mapping(
            contract,
            keys=("title", "task_title", "goal", "objective", "instructions", "summary", "task_id"),
            value_limit=600,
        )
    inherited = _inherited_memory_context_for_profile(inherited_start_context or {})
    if inherited:
        payload["inherited_start_context"] = inherited
    return {key: value for key, value in payload.items() if value}


def _compact_mapping(value: Any, *, keys: tuple[str, ...], value_limit: int = 240) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    compacted: dict[str, Any] = {}
    for key in keys:
        item = value.get(key)
        if isinstance(item, (str, int, float, bool)) and str(item).strip():
            compacted[key] = _trim_text(item, limit=value_limit)
        elif isinstance(item, dict) and item:
            compacted[key] = {
                str(child_key): _trim_text(child_value, limit=value_limit)
                for child_key, child_value in item.items()
                if isinstance(child_value, (str, int, float, bool)) and str(child_value).strip()
            }
    return {key: value for key, value in compacted.items() if value}


def _task_memory_request_profile_from_payload(*, task_run: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    candidates = [
        dict(contract.get("memory_request_profile") or {}) if isinstance(contract.get("memory_request_profile"), dict) else {},
        dict(contract.get("memory_scope") or {}) if isinstance(contract.get("memory_scope"), dict) else {},
        dict(dict(task_run.get("diagnostics") or {}).get("task_memory_request_profile") or {}),
        dict(dict(task_run.get("diagnostics") or {}).get("memory_request_profile") or {}),
    ]
    for candidate in candidates:
        if candidate:
            return dict(candidate)
    return {}


def _task_runtime_requested_memory_layers(
    memory_request_profile: dict[str, Any],
    *,
    agent_runtime_profile: Any,
) -> list[str]:
    requested = list(normalize_memory_layers(memory_request_profile.get("requested_memory_layers") or ()))
    if not requested:
        requested = ["state"]
    allow_long_term = (
        bool(memory_request_profile.get("allow_long_term_memory", False))
        or "long_term" in requested
        or _profile_allows_long_term_memory(agent_runtime_profile)
    )
    if allow_long_term and "long_term" not in requested:
        requested.append("long_term")
    return requested


def _task_memory_query(*, task_run: dict[str, Any], contract: dict[str, Any]) -> str:
    parts = [
        task_run.get("task_id"),
        task_run.get("title"),
        contract.get("title"),
        contract.get("task_title"),
        contract.get("goal"),
        contract.get("objective"),
        contract.get("instructions"),
        contract.get("summary"),
    ]
    return "\n".join(_trim_text(item, limit=800) for item in parts if str(item or "").strip())


def _task_memory_summaries_from_observations(value: Any) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for item in list(value or [])[-6:]:
        if not isinstance(item, dict):
            continue
        summaries.append(
            {
                "tool_name": _trim_text(item.get("tool_name") or item.get("name"), limit=120),
                "status": _trim_text(item.get("status"), limit=80),
                "summary": _trim_text(item.get("summary") or item.get("text") or item.get("error"), limit=300),
            }
        )
    return [item for item in summaries if any(item.values())]


def _task_memory_summaries_from_inherited_context(value: Any) -> list[dict[str, Any]]:
    payload = dict(value or {}) if isinstance(value, dict) else {}
    summaries: list[dict[str, Any]] = []
    for item in list(payload.get("observations") or [])[-6:]:
        if not isinstance(item, dict):
            continue
        observation_payload = dict(item.get("payload") or {})
        envelope = dict(observation_payload.get("result_envelope") or {})
        summaries.append(
            {
                "tool_name": _trim_text(
                    item.get("tool_name") or observation_payload.get("tool_name") or envelope.get("tool_name"),
                    limit=120,
                ),
                "status": _trim_text(
                    item.get("status") or observation_payload.get("status") or envelope.get("status"),
                    limit=80,
                ),
                "summary": _trim_text(
                    item.get("summary") or envelope.get("summary") or envelope.get("text") or observation_payload.get("text"),
                    limit=300,
                ),
                "source": "turn_to_task_context_handoff",
            }
        )
    return [item for item in summaries if any(item.values())]


def _dedupe_task_summaries(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in values:
        key = (
            str(item.get("tool_name") or ""),
            str(item.get("status") or ""),
            str(item.get("summary") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(dict(item))
    return result[-8:]


def _recent_tool_names_from_observations(value: Any) -> list[str]:
    names: list[str] = []
    for item in list(value or [])[-12:]:
        if isinstance(item, dict):
            names.append(str(item.get("tool_name") or item.get("name") or "").strip())
    return _dedupe_strings(names)[-8:]


def _recent_tool_names_from_inherited_context(value: Any) -> list[str]:
    payload = dict(value or {}) if isinstance(value, dict) else {}
    names: list[str] = []
    for item in list(payload.get("observations") or [])[-12:]:
        if isinstance(item, dict):
            observation_payload = dict(item.get("payload") or {})
            envelope = dict(observation_payload.get("result_envelope") or {})
            names.append(str(item.get("tool_name") or observation_payload.get("tool_name") or envelope.get("tool_name") or "").strip())
    return _dedupe_strings(names)[-8:]


def _inherited_memory_context_for_profile(value: Any) -> dict[str, Any]:
    payload = dict(value or {}) if isinstance(value, dict) else {}
    memory_context = dict(payload.get("memory_context") or {})
    memory_refs = dict(payload.get("memory_context_refs") or {})
    if not memory_context and not memory_refs:
        return {}
    visible_sections = dict(memory_context.get("model_visible_sections") or {})
    projected_sections: dict[str, list[str]] = {}
    for section, items in visible_sections.items():
        clean = [
            _trim_text(item, limit=1200)
            for item in list(items or [])[:8]
            if str(item).strip()
        ]
        if clean:
            projected_sections[str(section)] = clean
    return {
        key: value
        for key, value in {
            "source": "turn_to_task_context_handoff",
            "handoff_ref": str(payload.get("handoff_ref") or ""),
            "source_packet_ref": str(payload.get("source_packet_ref") or ""),
            "memory_runtime_view_ref": str(memory_refs.get("memory_runtime_view_ref") or memory_context.get("memory_runtime_view_ref") or ""),
            "context_package_ref": str(memory_refs.get("context_package_ref") or memory_context.get("context_package_ref") or ""),
            "selected_sections": [
                str(item)
                for item in list(memory_context.get("selected_sections") or projected_sections.keys())
                if str(item) in projected_sections
            ],
            "model_visible_sections": projected_sections,
            "diagnostics": _compact_mapping(
                memory_context.get("diagnostics"),
                keys=("read_namespaces", "requested_memory_layers", "long_term_candidate_count", "state_candidate_count", "context_candidate_count"),
                value_limit=600,
            ),
            "authority": "memory_system.runtime_context_provider.inherited_start_context",
        }.items()
        if value not in ("", None, [], {})
    }


def _recent_tool_names_from_messages(messages: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for item in list(messages or [])[-20:]:
        if not isinstance(item, dict):
            continue
        for call in list(item.get("tool_calls") or ()):
            if isinstance(call, dict):
                function = call.get("function")
                if isinstance(function, dict):
                    names.append(str(function.get("name") or "").strip())
                names.append(str(call.get("name") or "").strip())
        names.append(str(item.get("name") or "").strip())
    return _dedupe_strings(names)[-8:]


def _runtime_memory_context_payload(context_result: Any, memory_view: Any) -> dict[str, Any]:
    result_payload = context_result.to_dict() if hasattr(context_result, "to_dict") else dict(context_result or {})
    package = dict(result_payload.get("package") or {})
    sections = dict(package.get("model_visible_sections") or {})
    visible_sections = _filtered_model_visible_memory_sections(sections)
    memory_view_payload = memory_view.to_dict() if hasattr(memory_view, "to_dict") else dict(memory_view or {})
    diagnostics = dict(memory_view_payload.get("diagnostics") or {})
    read_plan = dict(diagnostics.get("read_plan") or {})
    sealed_receipt = dict(package.get("sealed_receipt") or result_payload.get("sealed_receipt") or {})
    selected_sections = [
        str(item)
        for item in list(package.get("selected_sections") or visible_sections.keys())
        if str(item) in visible_sections
    ]
    status = _memory_context_status(
        visible_sections=visible_sections,
        diagnostics=diagnostics,
        read_plan=read_plan,
    )
    return {
        "authority": "memory_system.runtime_memory_context",
        "memory_runtime_view_ref": str(memory_view_payload.get("view_id") or ""),
        "context_package_ref": str(sealed_receipt.get("receipt_id") or ""),
        "selected_sections": selected_sections,
        "model_visible_sections": visible_sections,
        "memory_context_status": status,
        "diagnostics": {
            "read_namespaces": list(read_plan.get("read_namespaces") or ()),
            "requested_memory_layers": list(read_plan.get("requested_memory_layers") or ()),
            "long_term_candidate_count": int(diagnostics.get("long_term_candidate_count") or 0),
            "state_candidate_count": int(diagnostics.get("state_candidate_count") or 0),
            "context_candidate_count": int(diagnostics.get("context_candidate_count") or 0),
        },
    }


def _memory_context_status(
    *,
    visible_sections: dict[str, list[str]],
    diagnostics: dict[str, Any],
    read_plan: dict[str, Any],
) -> dict[str, Any]:
    visible_item_count = sum(len(items) for items in visible_sections.values())
    candidate_count = int(diagnostics.get("context_candidate_count") or 0)
    requested_layers = [
        str(item)
        for item in list(read_plan.get("requested_memory_layers") or ())
        if str(item).strip()
    ]
    if visible_item_count:
        reason_code = "model_visible_memory_selected"
    elif candidate_count:
        reason_code = "memory_candidates_not_selected_for_context"
    elif requested_layers:
        reason_code = "memory_read_plan_evaluated_no_visible_records"
    else:
        reason_code = "memory_read_plan_not_requested"
    return {
        "status": "available" if visible_item_count else "empty",
        "reason_code": reason_code,
        "has_model_visible_records": bool(visible_item_count),
        "visible_section_count": len(visible_sections),
        "visible_item_count": visible_item_count,
        "context_candidate_count": candidate_count,
        "requested_memory_layers": requested_layers,
        "agent_use_contract": "Use listed memory records when present; if none are listed, do not infer that previous facts are known from memory.",
    }


def _unavailable_runtime_memory_context_payload(
    memory_request_profile: dict[str, Any],
    *,
    reason_code: str,
) -> dict[str, Any]:
    requested_layers = [
        str(item)
        for item in list(dict(memory_request_profile or {}).get("requested_memory_layers") or ())
        if str(item).strip()
    ]
    return {
        "authority": "memory_system.runtime_memory_context",
        "selected_sections": [],
        "model_visible_sections": {},
        "memory_context_status": {
            "status": "unavailable",
            "reason_code": str(reason_code or "memory_context_unavailable"),
            "has_model_visible_records": False,
            "visible_section_count": 0,
            "visible_item_count": 0,
            "context_candidate_count": 0,
            "requested_memory_layers": requested_layers,
            "agent_use_contract": "Memory context was requested but is unavailable; do not assume prior memory facts are visible.",
        },
        "diagnostics": {
            "read_namespaces": [],
            "requested_memory_layers": requested_layers,
            "long_term_candidate_count": 0,
            "state_candidate_count": 0,
            "context_candidate_count": 0,
        },
    }


def _filtered_model_visible_memory_sections(sections: dict[str, Any]) -> dict[str, list[str]]:
    allowed = (
        "active_process_context",
        "hot_truth_window",
        "retrieval_evidence",
        "warm_snapshots",
        "exact_durable_context",
        "relevant_durable_context",
    )
    filtered: dict[str, list[str]] = {}
    for section in allowed:
        items = [
            str(item).strip()
            for item in list(sections.get(section) or ())
            if str(item).strip()
        ]
        if items:
            filtered[section] = items
    return filtered


def _dedupe_strings(values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in list(values or ()):
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _trim_text(value: Any, *, limit: int = 240) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "..."
