from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, replace
from typing import Any

from runtime.shared.models import TurnRun
from runtime.shared.queued_user_input_store import QueuedUserInput

logger = logging.getLogger(__name__)

_ACTIVE_TURN_STEER_CLAIM_LIMIT = 8


@dataclass(frozen=True, slots=True)
class ActiveTurnQueuedUserSteers:
    items: tuple[QueuedUserInput, ...] = ()
    model_message: dict[str, Any] | None = None
    events: tuple[dict[str, Any], ...] = ()


async def claim_active_turn_queued_user_steers(
    runtime_host: Any | None,
    *,
    session_id: str,
    turn_id: str,
    turn_run: TurnRun | None = None,
    stream_run_id: str = "",
    packet_ref: str = "",
    phase: str,
    include_model_message: bool = True,
    source_authority: str = "harness.loop.active_turn_steer",
) -> ActiveTurnQueuedUserSteers:
    if runtime_host is None:
        return ActiveTurnQueuedUserSteers()
    active_turn = _resolve_active_turn_for_queued_steer(
        runtime_host,
        session_id=session_id,
        turn_id=turn_id,
    )
    if active_turn is None:
        return ActiveTurnQueuedUserSteers()
    store = getattr(runtime_host, "queued_user_inputs", None)
    claim = getattr(store, "claim_for_active_turn", None)
    if not callable(claim):
        return ActiveTurnQueuedUserSteers()
    items = await asyncio.to_thread(
        claim,
        session_id,
        turn_id=turn_id,
        limit=_ACTIVE_TURN_STEER_CLAIM_LIMIT,
    )
    claimed = tuple(item for item in list(items or []) if isinstance(item, QueuedUserInput))
    if not claimed:
        return ActiveTurnQueuedUserSteers()
    stream_ref = str(stream_run_id or getattr(active_turn, "stream_run_id", "") or "").strip()
    dispatch_ref = stream_ref or (turn_run.turn_run_id if turn_run is not None else turn_id)
    for item in claimed:
        _persist_queued_user_steer_as_turn_message(
            runtime_host,
            item,
            turn_id=turn_id,
            source=f"{source_authority}.message",
        )
        marker = getattr(store, "mark_dispatched", None)
        if callable(marker):
            await asyncio.to_thread(marker, item.session_id, item.queue_item_id, stream_run_id=dispatch_ref)
    dispatched = claimed
    task_environment_id = _first_task_environment_id(dispatched)
    _record_claimed_steers_in_turn_memory(
        runtime_host,
        session_id=session_id,
        turn_id=turn_id,
        turn_run=turn_run,
        active_turn=active_turn,
        claimed=dispatched,
    )
    model_message = (
        _queued_user_steer_model_message(dispatched, turn_id=turn_id, task_environment_id=task_environment_id, phase=phase)
        if include_model_message
        else None
    )
    lifecycle_event = _record_active_turn_steer_included_event(
        runtime_host,
        turn_run=turn_run,
        turn_id=turn_id,
        stream_ref=stream_ref,
        packet_ref=packet_ref,
        task_environment_id=task_environment_id,
        phase=phase,
        claimed=dispatched,
        source_authority=source_authority,
    )
    public_event = {
        "type": "active_turn_steer_included",
        "turn_id": turn_id,
        "turn_run_id": turn_run.turn_run_id if turn_run is not None else "",
        "packet_ref": str(packet_ref or ""),
        "phase": str(phase or ""),
        "queued_user_steers": [_queued_user_steer_payload(item) for item in dispatched],
        **({"task_environment_id": task_environment_id} if task_environment_id else {}),
        **({"event": lifecycle_event} if lifecycle_event else {}),
    }
    return ActiveTurnQueuedUserSteers(
        items=dispatched,
        model_message=model_message,
        events=(public_event,),
    )


def _record_claimed_steers_in_turn_memory(
    runtime_host: Any,
    *,
    session_id: str,
    turn_id: str,
    turn_run: TurnRun | None,
    active_turn: Any,
    claimed: tuple[QueuedUserInput, ...],
) -> None:
    store = getattr(runtime_host, "turn_memory_store", None)
    create_or_get = getattr(store, "create_or_get_turn", None)
    add_steer_ref = getattr(store, "add_steer_ref", None)
    if not callable(create_or_get) or not callable(add_steer_ref):
        return
    try:
        create_or_get(
            session_id=session_id,
            turn_id=turn_id,
            turn_run_id=turn_run.turn_run_id if turn_run is not None else "",
            branch_id=str(getattr(active_turn, "branch_id", "") or session_id),
        )
        for item in claimed:
            add_steer_ref(
                session_id=session_id,
                turn_id=turn_id,
                steer_ref=str(item.queue_item_id or item.client_message_id or ""),
            )
    except Exception:
        logger.debug("failed to record active turn steer refs in turn memory", exc_info=True)


def _resolve_active_turn_for_queued_steer(
    runtime_host: Any,
    *,
    session_id: str,
    turn_id: str,
) -> Any | None:
    active_registry = getattr(runtime_host, "active_turn_registry", None)
    resolver = getattr(active_registry, "resolve_current", None)
    if not callable(resolver):
        return None
    try:
        active_turn = resolver(str(session_id or "").strip())
    except Exception:
        return None
    if active_turn is None:
        return None
    if str(getattr(active_turn, "turn_id", "") or "").strip() != str(turn_id or "").strip():
        return None
    if not bool(getattr(active_turn, "steerable", False)):
        return None
    return active_turn


def _persist_queued_user_steer_as_turn_message(
    runtime_host: Any,
    item: QueuedUserInput,
    *,
    turn_id: str,
    source: str,
) -> None:
    session_manager = getattr(runtime_host, "session_manager", None)
    append_messages = getattr(session_manager, "append_messages", None)
    if not callable(append_messages):
        return
    message_id = str(item.client_message_id or item.queue_item_id or "").strip()
    if _session_already_contains_queued_user_steer(session_manager, item.session_id, item.queue_item_id, message_id):
        return
    payload = {
        "id": message_id,
        "message_id": message_id,
        "role": "user",
        "content": item.content,
        "turn_id": turn_id,
        "queued_input_id": item.queue_item_id,
        "client_message_id": item.client_message_id,
        "active_turn_steer": True,
        "source": source,
    }
    try:
        append_messages(item.session_id, [payload])
        append_provider_protocol = getattr(session_manager, "append_provider_protocol_messages", None)
        if callable(append_provider_protocol):
            append_provider_protocol(item.session_id, [payload])
    except Exception:
        logger.debug("failed to persist active turn queued user steer message", exc_info=True)


def _session_already_contains_queued_user_steer(
    session_manager: Any,
    session_id: str,
    queue_item_id: str,
    message_id: str,
) -> bool:
    loader = getattr(session_manager, "load_session", None)
    if not callable(loader):
        return False
    try:
        messages = list(loader(session_id) or [])
    except Exception:
        return False
    for message in messages:
        if not isinstance(message, dict):
            continue
        if queue_item_id and str(message.get("queued_input_id") or "").strip() == queue_item_id:
            return True
        if message_id and str(message.get("id") or message.get("message_id") or "").strip() == message_id:
            return True
    return False


def _record_active_turn_steer_included_event(
    runtime_host: Any,
    *,
    turn_run: TurnRun | None,
    turn_id: str,
    stream_ref: str,
    packet_ref: str,
    task_environment_id: str,
    phase: str,
    claimed: tuple[QueuedUserInput, ...],
    source_authority: str,
) -> dict[str, Any]:
    if turn_run is None:
        return {}
    try:
        event = runtime_host.event_log.append(
            turn_run.turn_run_id,
            "active_turn_steer_included",
            payload={
                "turn_id": turn_id,
                "phase": str(phase or ""),
                "packet_ref": str(packet_ref or ""),
                "stream_run_id": stream_ref,
                "task_environment_id": task_environment_id,
                "queued_user_steers": [_queued_user_steer_payload(item) for item in claimed],
                "authority": source_authority,
            },
            refs={
                "turn_ref": turn_id,
                "turn_run_ref": turn_run.turn_run_id,
                "runtime_invocation_packet_ref": str(packet_ref or ""),
                "queued_user_input_refs": [item.queue_item_id for item in claimed],
                **({"task_environment_ref": task_environment_id} if task_environment_id else {}),
            },
        )
        _update_turn_run_event_offset(runtime_host, turn_run=turn_run, event=event)
        return event.to_dict()
    except Exception:
        logger.debug("failed to record active turn queued user steer lifecycle", exc_info=True)
        return {}


def _update_turn_run_event_offset(runtime_host: Any, *, turn_run: TurnRun, event: Any) -> None:
    try:
        current = runtime_host.state_index.get_turn_run(turn_run.turn_run_id) or turn_run
        runtime_host.state_index.upsert_turn_run(
            replace(
                current,
                updated_at=float(getattr(event, "created_at", 0.0) or getattr(current, "updated_at", 0.0) or 0.0),
                latest_event_offset=int(getattr(event, "offset", 0) or getattr(current, "latest_event_offset", 0) or 0),
            )
        )
    except Exception:
        logger.debug("failed to update active turn run event offset", exc_info=True)


def _queued_user_steer_model_message(
    items: tuple[QueuedUserInput, ...],
    *,
    turn_id: str,
    task_environment_id: str,
    phase: str,
) -> dict[str, Any]:
    payload = {
        "turn_id": str(turn_id or ""),
        "task_environment_id": str(task_environment_id or ""),
        "phase": str(phase or ""),
        "steers": [_queued_user_steer_payload(item) for item in items],
        "authority": "harness.loop.active_turn_steer",
    }
    instruction = (
        "用户在本轮 agent 运行期间追加了以下补充要求。"
        "这些内容属于当前 active turn 的最新用户上下文，不是新的独立任务，也不是下一轮聊天。"
        "你必须在继续调用工具、提交最终回复或启动/控制任务之前先吸收这些要求；"
        "如果用户希望改变目标、范围、优先级、验收标准或约束，后续行动必须以这些最新要求为准。"
        "如果之前的计划或刚生成的动作与补充要求冲突，放弃旧动作并重新判断。"
        "吸收补充要求后，只能按本阶段 output contract 继续。"
        "如果只是回应用户，并且本阶段允许 assistant 正文作为 respond，可以直接自然回复；"
        "如果需要工具、控制当前工作、询问用户或说明阻塞，必须提交本阶段允许的结构化动作，正文分别写入对应动作字段。"
    )
    return {
        "role": "user",
        "content": f"{instruction}\n{json.dumps(payload, ensure_ascii=False, sort_keys=True)}",
        "turn_id": turn_id,
    }


def _queued_user_steer_payload(item: QueuedUserInput) -> dict[str, Any]:
    return {
        "queue_item_id": item.queue_item_id,
        "client_message_id": item.client_message_id,
        "content": item.content,
        "input_policy": item.input_policy,
        "expected_active_turn_id": item.expected_active_turn_id,
        "task_environment_id": item.task_environment_id,
        "created_at": item.created_at,
        "editor_context": dict(item.editor_context or {}),
    }


def _first_task_environment_id(items: tuple[QueuedUserInput, ...]) -> str:
    for item in items:
        task_environment_id = str(getattr(item, "task_environment_id", "") or "").strip()
        if task_environment_id:
            return task_environment_id
    return ""
