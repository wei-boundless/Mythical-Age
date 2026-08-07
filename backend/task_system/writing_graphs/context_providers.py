from __future__ import annotations

import re
from typing import Any

from graph_system.context_provider_registry import GraphContextProvider, GraphContextProviderContribution
from graph_system.models import ExecutableGraphConfig, GraphLoopState


AUTHORITY = "task_system.writing_graphs.context_provider"


def register_context_providers(register) -> None:
    register(
        GraphContextProvider(
            provider_id="writing_graph_context",
            provide=provide_writing_graph_context,
            priority=200,
            initial_input_keys=(
                "active_chapter_count",
                "active_chapter_end_index",
                "active_chapter_range",
                "active_chapter_start_index",
                "batch_chapter_list",
                "batch_chapter_numbers",
                "batch_chapter_range",
                "batch_end_index_padded",
                "batch_index_padded",
                "batch_label",
                "batch_start_index_padded",
                "batch_target_measure",
                "chapter_batch_iteration",
                "chapter_file_prefix",
                "chapter_index_padded",
                "chapter_label",
                "chapter_unit_completed_count",
                "current_chapter_index",
                "current_chapter_index_padded",
                "current_chapter_label",
                "current_chapter_file_prefix",
                "current_chapter_outline",
                "current_chapter_outline_title",
                "current_chapter_outline_source",
                "revision_execution_range",
                "revision_required",
                "chapter_revision_requirements",
                "quality_gate_feedback",
                "previous_chapter_review_ref",
                "previous_chapter_draft_ref",
                "batch_chapter_ledger",
                "batch_chapter_ledger_authority",
                "group_current_measure",
                "group_target_measure",
                "last_batch_words",
                "metric_label",
                "target_group_count",
                "target_measure_units",
                "target_unit_count",
                "target_unit_measure",
                "total_current_measure",
                "unit_count",
                "unit_index",
                "unit_start_index",
                "unit_end_index",
                "unit_target_measure",
                "units_per_batch",
                "units_per_group",
                "volume_index",
                "volume_index_padded",
                "volume_label",
            ),
            runtime_scope_keys=(
                "chapter_index",
                "current_chapter_index",
                "active_chapter_range",
                "revision_execution_range",
            ),
            loop_contract_input_keys=(
                "chapter_index",
                "current_chapter_index",
                "batch_start_index",
                "batch_end_index",
                "batch_chapter_range",
                "batch_index",
                "group_current_measure",
                "group_target_measure",
                "target_measure_units",
                "target_unit_measure",
                "active_chapter_range",
                "current_chapter_file_prefix",
                "current_chapter_index_padded",
                "current_chapter_label",
                "unit_count",
                "unit_end_index",
                "unit_start_index",
                "unit_target_measure",
                "units_per_batch",
                "revision_queue_chapter_indexes",
                "revision_execution_range",
            ),
        )
    )


def provide_writing_graph_context(
    *,
    graph_config: ExecutableGraphConfig,
    state: GraphLoopState,
    node: dict[str, Any],
    services: Any | None,
    initial_inputs: dict[str, Any],
    inbound_context: list[dict[str, Any]],
) -> GraphContextProviderContribution:
    del services
    node_id = str(node.get("node_id") or "")
    base_inputs = dict(initial_inputs or {})
    current_inputs = dict(base_inputs)
    updates: dict[str, Any] = {}
    visible_inbound = [dict(item) for item in list(inbound_context or []) if isinstance(item, dict)]

    for patch in (
        _current_chapter_execution_inputs(current_inputs),
        _revision_request_inputs(node=node, inbound_context=visible_inbound, initial_inputs=current_inputs),
        _quality_revision_inputs(node=node, inbound_context=visible_inbound, initial_inputs=current_inputs),
        _current_chapter_outline_inputs(initial_inputs=current_inputs, inbound_context=visible_inbound),
    ):
        if patch:
            updates.update(dict(patch))
            current_inputs.update(dict(patch))

    visible_inbound = _project_chapter_draft_context_to_current_chapter(
        node_id=node_id,
        graph_run_id=state.graph_run_id,
        initial_inputs=current_inputs,
        inbound_context=visible_inbound,
    )
    visible_inbound = _sanitize_revision_context_for_current_chapter(
        node_id=node_id,
        initial_inputs=current_inputs,
        inbound_context=visible_inbound,
    )
    ledger_patch = _batch_chapter_ledger_inputs_for_node(
        graph_config=graph_config,
        state=state,
        node_id=node_id,
        inbound_context=visible_inbound,
    )
    if ledger_patch:
        updates.update(ledger_patch)
        visible_inbound = _with_batch_chapter_ledger_context(
            node_id=node_id,
            graph_run_id=state.graph_run_id,
            inbound_context=visible_inbound,
            ledger=dict(ledger_patch.get("batch_chapter_ledger") or {}),
        )

    return GraphContextProviderContribution(
        initial_inputs=updates,
        inbound_context=visible_inbound,
    )


def _current_chapter_execution_inputs(initial_inputs: dict[str, Any]) -> dict[str, Any]:
    chapter = _int_value(initial_inputs.get("chapter_index"), None)
    if chapter is None:
        return {}
    patch: dict[str, Any] = {
        "chapter_index": chapter,
        "chapter_index_padded": f"{chapter:03d}",
        "chapter_label": f"第{chapter}章",
        "chapter_file_prefix": f"chapter_{chapter:03d}",
        "current_chapter_index": chapter,
        "current_chapter_index_padded": f"{chapter:03d}",
        "current_chapter_label": f"第{chapter}章",
        "current_chapter_file_prefix": f"chapter_{chapter:03d}",
    }
    revision_range = str(initial_inputs.get("revision_execution_range") or "").strip()
    active_range = str(initial_inputs.get("active_chapter_range") or "").strip()
    if revision_range:
        patch["revision_execution_range"] = revision_range
    elif active_range:
        patch["revision_execution_range"] = active_range
    return patch


def _revision_request_inputs(
    *,
    node: dict[str, Any],
    inbound_context: list[dict[str, Any]],
    initial_inputs: dict[str, Any],
) -> dict[str, Any]:
    requirements_key = _node_revision_requirements_key(node)
    if not requirements_key:
        return {}
    revision = _first_inbound_revision_request(inbound_context)
    if not revision:
        return {}
    current_chapter = _int_value(initial_inputs.get("current_chapter_index") or initial_inputs.get("chapter_index"), None)
    revision_text = _revision_request_text(revision, current_chapter=current_chapter)
    if not revision_text:
        return {}
    payload = {
        requirements_key: revision_text,
        "revision_required": True,
    }
    artifact_refs = _artifact_ref_values(revision.get("artifact_refs"))
    if artifact_refs:
        payload["previous_chapter_review_ref"] = {"artifact_refs": artifact_refs}
    return payload


def _node_revision_requirements_key(node: dict[str, Any]) -> str:
    retry_policy = dict(node.get("retry") or {})
    key = str(retry_policy.get("requirements_input_key") or "").strip()
    if key:
        return key
    executor_policy = dict(node.get("executor_policy") or {})
    replay_policy = dict(executor_policy.get("replay_sanitization_policy") or {})
    return str(replay_policy.get("requirements_key") or "").strip()


def _quality_revision_inputs(
    *,
    node: dict[str, Any],
    inbound_context: list[dict[str, Any]],
    initial_inputs: dict[str, Any],
) -> dict[str, Any]:
    retry_policy = dict(node.get("retry") or {})
    requirements_key = str(retry_policy.get("requirements_input_key") or "").strip()
    template = str(retry_policy.get("requirements_template") or "").strip()
    if not requirements_key or not template or requirements_key in initial_inputs:
        return {}
    quality = _first_inbound_quality_failure(inbound_context)
    if not quality:
        return {}
    unit_start = initial_inputs.get("chapter_index") or initial_inputs.get("unit_start_index") or initial_inputs.get("batch_start_index") or ""
    unit_end = initial_inputs.get("chapter_index") or initial_inputs.get("unit_end_index") or initial_inputs.get("batch_end_index") or ""
    values = {
        **dict(initial_inputs or {}),
        "quality_issues": "; ".join(str(item) for item in list(quality.get("issues") or []) if str(item)),
        "quality_issue_summary": str(quality.get("quality_issue_summary") or ""),
        "start": unit_start,
        "end": unit_end,
        "count": initial_inputs.get("units_per_batch") or initial_inputs.get("unit_count") or "",
        "unit_target": initial_inputs.get("unit_target_measure") or initial_inputs.get("target_unit_measure") or "",
    }
    revision_inputs = {
        requirements_key: _format_revision_template(template, values),
        "quality_gate_feedback": quality,
    }
    carry_key = str(retry_policy.get("carry_current_output_as") or "").strip()
    if carry_key and carry_key not in initial_inputs:
        previous_output = _quality_failure_previous_output(quality)
        if previous_output:
            revision_inputs[carry_key] = previous_output
    return revision_inputs


def _current_chapter_outline_inputs(*, initial_inputs: dict[str, Any], inbound_context: list[dict[str, Any]]) -> dict[str, Any]:
    chapter = _int_value(initial_inputs.get("current_chapter_index") or initial_inputs.get("chapter_index"), None)
    if chapter is None:
        return {}
    for text in _inbound_artifact_texts(inbound_context, current_chapter=chapter):
        section = _extract_chapter_outline_section(text, chapter)
        if not section:
            continue
        title = _chapter_outline_title(section, chapter)
        return _drop_empty(
            {
                "current_chapter_outline": section,
                "current_chapter_outline_title": title,
                "current_chapter_outline_source": "inbound_artifact_projection",
            }
        )
    return {}


def _project_chapter_draft_context_to_current_chapter(
    *,
    node_id: str,
    graph_run_id: str,
    initial_inputs: dict[str, Any],
    inbound_context: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if _node_tail(node_id) != "chapter_draft":
        return inbound_context
    chapter = _int_value(initial_inputs.get("current_chapter_index") or initial_inputs.get("chapter_index"), None)
    if chapter is None:
        return inbound_context
    outline = str(initial_inputs.get("current_chapter_outline") or "").strip()
    outline_title = str(initial_inputs.get("current_chapter_outline_title") or f"第{chapter:03d}章").strip()
    projected: list[dict[str, Any]] = []
    inserted_projection = False
    for raw in inbound_context:
        item = dict(raw or {})
        if not _is_chapter_outline_context(item):
            projected.append(item)
            continue
        payload = dict(item.get("payload") or {})
        refs = _artifact_ref_values(item.get("artifact_refs") or payload.get("artifact_refs"))
        selected_payloads: list[dict[str, Any]] = []
        for artifact_payload in _artifact_payload_dicts(item):
            text = str(artifact_payload.get("content") or artifact_payload.get("text") or "").strip()
            section = _extract_chapter_outline_section(text, chapter)
            if not section:
                continue
            selected_payloads.append(
                _drop_empty(
                    {
                        **dict(artifact_payload),
                        "content": section,
                        "text": section,
                        "projection": "current_chapter_outline_only",
                        "projected_chapter_index": chapter,
                        "authority": f"{AUTHORITY}.current_chapter_outline_projection",
                    }
                )
            )
        if outline and not selected_payloads:
            selected_payloads.append(
                {
                    "artifact_ref": refs[0] if refs else "",
                    "content": outline,
                    "text": outline,
                    "projection": "current_chapter_outline_only",
                    "projected_chapter_index": chapter,
                    "authority": f"{AUTHORITY}.current_chapter_outline_projection",
                }
            )
        if selected_payloads:
            projected.append(
                _drop_empty(
                    {
                        **item,
                        "context_id": f"writing_current_chapter_outline:{_safe_id(graph_run_id)}:{_safe_id(node_id)}:{chapter}",
                        "packet_type": "writing.current_chapter_outline_projection",
                        "target_context_key": "当前章细纲",
                        "target_input_slot": "current_chapter_outline",
                        "delivery_policy": "current_chapter_outline_projection",
                        "payload": {
                            **payload,
                            "current_chapter_index": chapter,
                            "current_chapter_label": initial_inputs.get("current_chapter_label") or f"第{chapter}章",
                            "current_chapter_outline_title": outline_title,
                            "artifact_payloads": selected_payloads,
                            "artifact_refs": refs,
                            "authority": f"{AUTHORITY}.current_chapter_outline_payload",
                        },
                        "artifact_refs": [{"path": ref} for ref in refs],
                        "visibility": {
                            "source": "writing_graph_context_provider.current_chapter_outline_projection",
                            "artifact_text_projection": "current_chapter_only",
                            "authority": f"{AUTHORITY}.current_chapter_outline_visibility",
                        },
                        "authority": f"{AUTHORITY}.current_chapter_outline_context",
                    }
                )
            )
            inserted_projection = True
            continue
        payload.pop("artifact_payloads", None)
        item["payload"] = _drop_empty(
            {
                **payload,
                "current_chapter_index": chapter,
                "current_chapter_outline_projection": "missing",
            }
        )
        visibility = dict(item.get("visibility") or {})
        visibility["artifact_text_projection"] = "suppressed_for_single_chapter_execution"
        visibility["authority"] = f"{AUTHORITY}.chapter_outline_projection_visibility"
        item["visibility"] = visibility
        projected.append(item)
    if outline and not inserted_projection:
        projected.insert(
            0,
            {
                "context_id": f"writing_current_chapter_outline:{_safe_id(graph_run_id)}:{_safe_id(node_id)}:{chapter}",
                "packet_type": "writing.current_chapter_outline_projection",
                "source_node_id": "__writing_context_provider__",
                "target_node_id": node_id,
                "edge_id": f"writing_current_chapter_outline::{node_id}",
                "payload_contract_id": "task_system.writing.current_chapter_outline.v1",
                "packet_contract_id": "task_system.writing.current_chapter_outline.v1",
                "target_context_key": "当前章细纲",
                "target_input_slot": "current_chapter_outline",
                "delivery_policy": "current_chapter_outline_projection",
                "payload": {
                    "current_chapter_index": chapter,
                    "current_chapter_label": initial_inputs.get("current_chapter_label") or f"第{chapter}章",
                    "current_chapter_outline_title": outline_title,
                    "artifact_payloads": [
                        {
                            "artifact_ref": str(initial_inputs.get("current_chapter_outline_source") or "current_chapter_outline"),
                            "content": outline,
                            "text": outline,
                            "projection": "current_chapter_outline_only",
                            "projected_chapter_index": chapter,
                            "authority": f"{AUTHORITY}.current_chapter_outline_projection",
                        }
                    ],
                    "authority": f"{AUTHORITY}.current_chapter_outline_payload",
                },
                "artifact_refs": [],
                "memory_refs": [],
                "result_refs": [],
                "receipt_refs": [],
                "visibility": {
                    "source": "writing_graph_context_provider.current_chapter_outline_projection",
                    "artifact_text_projection": "current_chapter_only",
                    "authority": f"{AUTHORITY}.current_chapter_outline_visibility",
                },
                "authority": f"{AUTHORITY}.current_chapter_outline_context",
            },
        )
    return projected


def _is_chapter_outline_context(inbound: dict[str, Any]) -> bool:
    source_tail = _node_tail(str(inbound.get("source_node_id") or ""))
    edge_id = str(inbound.get("edge_id") or inbound.get("source_edge_id") or "").lower()
    target_key = str(inbound.get("target_context_key") or inbound.get("target_input_slot") or "")
    if source_tail == "chapter_outline":
        return True
    if "outline" in edge_id and "draft" in edge_id:
        return True
    return target_key in {"上游交接包", "chapter_outline", "当前批次细纲"}


def _artifact_payload_dicts(inbound: dict[str, Any]) -> list[dict[str, Any]]:
    payload = dict(inbound.get("payload") or {})
    result: list[dict[str, Any]] = []
    for container in (inbound, payload):
        for raw in list(dict(container).get("artifact_payloads") or []):
            if isinstance(raw, dict):
                result.append(dict(raw))
    return result


def _sanitize_revision_context_for_current_chapter(
    *,
    node_id: str,
    initial_inputs: dict[str, Any],
    inbound_context: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if _node_tail(node_id) != "chapter_draft" or not initial_inputs.get("revision_queue_chapter_indexes"):
        return inbound_context
    chapter = _int_value(initial_inputs.get("current_chapter_index") or initial_inputs.get("chapter_index"), None)
    if chapter is None:
        return inbound_context
    sanitized: list[dict[str, Any]] = []
    for raw in inbound_context:
        item = dict(raw or {})
        packet_type = str(item.get("packet_type") or "").lower()
        edge_id = str(item.get("edge_id") or "").lower()
        target_key = str(item.get("target_context_key") or item.get("target_input_slot") or "")
        is_revision = "revision" in packet_type or ".revision." in edge_id or target_key == "返修交接包"
        if not is_revision:
            sanitized.append(item)
            continue
        payload = dict(item.get("payload") or {})
        refs = _artifact_ref_values(item.get("artifact_refs") or payload.get("artifact_refs"))
        payload.pop("artifact_payloads", None)
        payload["handoff_summary"] = str(initial_inputs.get("chapter_revision_requirements") or payload.get("handoff_summary") or "")[:8000]
        payload["current_chapter_index"] = chapter
        payload["revision_execution_range"] = str(initial_inputs.get("revision_execution_range") or "")
        item["payload"] = _drop_empty(payload)
        item["artifact_refs"] = [{"path": ref} for ref in refs]
        item["delivery_policy"] = "current_chapter_revision_summary_and_refs"
        visibility = dict(item.get("visibility") or {})
        visibility["artifact_text_projection"] = "suppressed_for_current_chapter_revision_packet"
        visibility["authority"] = f"{AUTHORITY}.current_chapter_revision_visibility"
        item["visibility"] = visibility
        sanitized.append(item)
    return sanitized


def _batch_chapter_ledger_inputs_for_node(
    *,
    graph_config: ExecutableGraphConfig,
    state: GraphLoopState,
    node_id: str,
    inbound_context: list[dict[str, Any]],
) -> dict[str, Any]:
    if _node_tail(node_id) != "chapter_batch_assemble":
        return {}
    generated = _batch_chapter_ledger(graph_config=graph_config, state=state, exit_node_id=node_id)
    if generated:
        return {
            "batch_chapter_ledger": _compact_batch_chapter_ledger(generated),
            "batch_chapter_ledger_authority": f"{AUTHORITY}.batch_chapter_ledger",
        }
    for raw in inbound_context:
        if not isinstance(raw, dict):
            continue
        payload = dict(raw.get("payload") or {})
        ledger = payload.get("batch_chapter_ledger")
        if isinstance(ledger, dict) and ledger:
            return {
                "batch_chapter_ledger": _compact_batch_chapter_ledger(dict(ledger)),
                "batch_chapter_ledger_authority": f"{AUTHORITY}.batch_chapter_ledger",
            }
    return {}


def _with_batch_chapter_ledger_context(
    *,
    node_id: str,
    graph_run_id: str,
    inbound_context: list[dict[str, Any]],
    ledger: dict[str, Any],
) -> list[dict[str, Any]]:
    if not ledger:
        return inbound_context
    artifact_refs = _artifact_ref_values(ledger.get("artifact_refs"))
    context = _drop_empty(
        {
            "context_id": f"writing_batch_chapter_ledger:{_safe_id(graph_run_id)}:{_safe_id(node_id)}",
            "packet_type": "writing.batch_chapter_ledger",
            "source_node_id": "__writing_context_provider__",
            "target_node_id": node_id,
            "edge_id": f"writing_batch_chapter_ledger::{node_id}",
            "payload_contract_id": "task_system.writing.batch_chapter_ledger.v1",
            "packet_contract_id": "task_system.writing.batch_chapter_ledger.v1",
            "target_context_key": "batch_chapter_ledger",
            "target_input_slot": "batch_chapter_ledger",
            "delivery_policy": "writing_batch_ledger_and_artifact_payloads",
            "payload": {
                "batch_chapter_ledger": ledger,
                "artifact_refs": artifact_refs,
                "artifact_payloads": _artifact_payloads_for_refs(artifact_refs, max_refs=24, max_chars=12000),
                "authority": f"{AUTHORITY}.batch_chapter_ledger_context_payload",
            },
            "artifact_refs": [{"path": ref} for ref in artifact_refs],
            "memory_refs": [],
            "result_refs": [],
            "receipt_refs": [],
            "visibility": {
                "source": "writing_graph_context_provider.batch_chapter_ledger",
                "artifact_text_projection": "bounded",
                "authority": f"{AUTHORITY}.batch_chapter_ledger_context.visibility",
            },
            "authority": f"{AUTHORITY}.batch_chapter_ledger_context",
        }
    )
    return [*inbound_context, context]


def _inbound_artifact_texts(inbound_context: list[dict[str, Any]], *, current_chapter: int | None = None) -> list[str]:
    texts: list[str] = []
    for raw in inbound_context:
        item = dict(raw or {})
        payload = dict(item.get("payload") or {})
        for container in (item, payload):
            for artifact_payload in list(dict(container).get("artifact_payloads") or []):
                if not isinstance(artifact_payload, dict):
                    continue
                text = str(artifact_payload.get("content") or artifact_payload.get("text") or "").strip()
                if text:
                    texts.append(text)
        if current_chapter is not None:
            revision_text = str(payload.get("handoff_summary") or "").strip()
            current_requirements = _extract_current_chapter_revision_requirements(revision_text, current_chapter)
            if current_requirements:
                texts.append(current_requirements)
    return texts


def _first_inbound_revision_request(inbound_context: list[dict[str, Any]]) -> dict[str, Any]:
    for item in inbound_context:
        context = dict(item or {})
        packet_type = str(context.get("packet_type") or "").strip().lower()
        target_key = str(context.get("target_context_key") or context.get("target_input_slot") or "").strip()
        edge_id = str(context.get("edge_id") or "").strip().lower()
        if "revision" not in packet_type and target_key != "返修交接包" and ".revision." not in edge_id:
            continue
        payload = dict(context.get("payload") or {})
        if not payload:
            continue
        return {
            **payload,
            "artifact_refs": _artifact_ref_values(context.get("artifact_refs") or payload.get("artifact_refs")),
            "authority": f"{AUTHORITY}.revision_request_inputs",
        }
    return {}


def _first_inbound_quality_failure(inbound_context: list[dict[str, Any]]) -> dict[str, Any]:
    for item in inbound_context:
        payload = dict(dict(item or {}).get("payload") or {})
        source_error = dict(payload.get("source_error") or {})
        quality = dict(payload.get("quality_acceptance") or {})
        if str(source_error.get("reason") or "") != "quality_gate_failed" and bool(quality.get("accepted") is not False):
            continue
        return {
            **quality,
            "quality_issue_summary": str(source_error.get("quality_issue_summary") or quality.get("quality_issue_summary") or ""),
            "issues": list(source_error.get("issues") or quality.get("issues") or []),
            "source_error": source_error,
            "artifact_refs": _artifact_ref_values(payload.get("artifact_refs")),
            "artifact_payloads": [
                dict(item)
                for item in list(payload.get("artifact_payloads") or [])
                if isinstance(item, dict)
            ],
            "handoff_summary": str(payload.get("handoff_summary") or ""),
            "authority": f"{AUTHORITY}.quality_revision_inputs",
        }
    return {}


def _quality_failure_previous_output(quality: dict[str, Any]) -> dict[str, Any]:
    return _drop_empty(
        {
            "artifact_refs": _artifact_ref_values(quality.get("artifact_refs")),
            "artifact_payloads": [
                _drop_empty(
                    {
                        "artifact_ref": str(dict(item).get("artifact_ref") or ""),
                        "content": str(dict(item).get("content") or dict(item).get("text") or "")[:30000],
                        "truncated": bool(dict(item).get("truncated") is True),
                        "max_chars": int(dict(item).get("max_chars") or 30000),
                    }
                )
                for item in list(quality.get("artifact_payloads") or [])[:8]
                if isinstance(item, dict)
            ],
            "handoff_summary": str(quality.get("handoff_summary") or "")[:1200],
            "authority": f"{AUTHORITY}.previous_quality_failure_output",
        }
    )


def _batch_chapter_ledger(
    *,
    graph_config: ExecutableGraphConfig,
    state: GraphLoopState,
    exit_node_id: str,
) -> dict[str, Any]:
    frame, iteration_entries = _loop_iteration_entries_for_exit(state=state, exit_node_id=exit_node_id)
    initial_inputs = dict(state.initial_inputs or {})
    start = _int_value(initial_inputs.get("batch_start_index"), None)
    end = _int_value(initial_inputs.get("batch_end_index"), start)
    if start is None or end is None:
        return {}
    if end < start:
        start, end = end, start
    if end - start > 100:
        return {}
    existing_by_chapter: dict[int, dict[str, Any]] = {}
    for entry in iteration_entries:
        chapter = _chapter_index_from_iteration_entry(entry)
        if chapter is not None and start <= chapter <= end and chapter not in existing_by_chapter:
            existing_by_chapter[chapter] = dict(entry)
    scope_nodes = [str(item) for item in list(frame.get("scope_node_ids") or []) if str(item)]
    draft_node_id = _node_id_for_tail(graph_config=graph_config, scope_node_ids=scope_nodes, tail="chapter_draft")
    router_node_id = _node_id_for_tail(graph_config=graph_config, scope_node_ids=scope_nodes, tail="chapter_unit_router")
    history_index = _batch_chapter_artifact_index(
        state=state,
        start=start,
        end=end,
        draft_node_id=draft_node_id,
        router_node_id=router_node_id,
    )
    chapter_entries: list[dict[str, Any]] = []
    all_refs: list[Any] = []
    for chapter in range(start, end + 1):
        loop_entry = dict(existing_by_chapter.get(chapter) or {})
        loop_results = _chapter_node_results_by_tail(loop_entry)
        history_results = {
            tail: dict(summary)
            for tail, summary in dict(history_index.get(chapter) or {}).items()
            if isinstance(summary, dict)
        }
        draft_entry = dict(loop_results.get("chapter_draft") or history_results.get("chapter_draft") or {})
        router_entry = dict(loop_results.get("chapter_unit_router") or history_results.get("chapter_unit_router") or {})
        draft_refs = _artifact_ref_values(draft_entry.get("artifact_refs"))
        router_refs = _artifact_ref_values(router_entry.get("artifact_refs"))
        all_refs.extend(draft_refs)
        all_refs.extend(router_refs)
        warnings: list[str] = []
        if not loop_entry and (draft_refs or router_refs):
            warnings.append("artifact_found_without_loop_iteration_result")
        if not draft_refs:
            warnings.append("draft_artifact_missing")
        if not router_refs:
            warnings.append("route_artifact_missing")
        chapter_entries.append(
            _drop_empty(
                {
                    "chapter_index": chapter,
                    "chapter_index_padded": f"{chapter:03d}",
                    "iteration_id": str(loop_entry.get("iteration_id") or f"chapter-{chapter}"),
                    "loop_iteration_present": bool(loop_entry),
                    "status": "complete" if draft_refs and router_refs else "incomplete",
                    "draft": _ledger_node_result_projection(draft_entry, source="loop_iteration_results" if loop_results.get("chapter_draft") else "result_history"),
                    "route": _ledger_node_result_projection(router_entry, source="loop_iteration_results" if loop_results.get("chapter_unit_router") else "result_history"),
                    "warnings": warnings,
                }
            )
        )
    complete = [entry["chapter_index"] for entry in chapter_entries if entry.get("status") == "complete"]
    missing = [entry["chapter_index"] for entry in chapter_entries if entry.get("status") != "complete"]
    return _drop_empty(
        {
            "authority": f"{AUTHORITY}.batch_chapter_ledger",
            "source": "loop_iteration_results_plus_completed_result_history",
            "batch_start_index": start,
            "batch_end_index": end,
            "expected_chapter_indexes": list(range(start, end + 1)),
            "complete_chapter_indexes": complete,
            "missing_chapter_indexes": missing,
            "chapters": chapter_entries,
            "artifact_refs": _artifact_ref_values(all_refs),
        }
    )


def _loop_iteration_entries_for_exit(*, state: GraphLoopState, exit_node_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    loop_state = dict(state.loop_state or {})
    frames = {
        str(frame_id): dict(frame)
        for frame_id, frame in dict(loop_state.get("frames") or {}).items()
        if isinstance(frame, dict)
    }
    iteration_results = {
        str(frame_id): dict(frame_results)
        for frame_id, frame_results in dict(loop_state.get("iteration_results") or {}).items()
        if isinstance(frame_results, dict)
    }
    for frame in frames.values():
        frame_id = str(frame.get("frame_id") or frame.get("scope_id") or "").strip()
        scope_id = str(frame.get("scope_id") or frame_id).strip()
        if not frame_id or str(frame.get("exit_node_id") or "").strip() != exit_node_id:
            continue
        frame_results = dict(iteration_results.get(frame_id) or iteration_results.get(scope_id) or {})
        entries: list[dict[str, Any]] = []
        for iteration_id, raw_node_results in _ordered_iteration_items(frame_results):
            node_entries = [
                _node_result_context_entry(result_node_id=str(result_node_id), summary=dict(raw_summary))
                for result_node_id, raw_summary in dict(raw_node_results or {}).items()
                if isinstance(raw_summary, dict)
            ]
            if node_entries:
                entries.append({"iteration_id": str(iteration_id or ""), "node_results": node_entries})
        return frame, entries
    return {}, []


def _node_result_context_entry(*, result_node_id: str, summary: dict[str, Any]) -> dict[str, Any]:
    return _drop_empty(
        {
            "node_id": str(result_node_id or summary.get("node_id") or ""),
            "status": str(summary.get("status") or ""),
            "result_ref": str(summary.get("result_ref") or ""),
            "artifact_refs": _artifact_ref_values(summary.get("artifact_refs")),
            "handoff_summary": str(summary.get("handoff_summary") or "")[:1200],
        }
    )


def _chapter_node_results_by_tail(entry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for raw in list(dict(entry or {}).get("node_results") or []):
        if not isinstance(raw, dict):
            continue
        node_result = dict(raw)
        tail = _node_tail(str(node_result.get("node_id") or ""))
        if tail in {"chapter_draft", "chapter_unit_router"} and tail not in results:
            results[tail] = node_result
    return results


def _ledger_node_result_projection(entry: dict[str, Any], *, source: str) -> dict[str, Any]:
    if not entry:
        return {}
    return _drop_empty(
        {
            "source": source,
            "node_id": str(entry.get("node_id") or ""),
            "status": str(entry.get("status") or ""),
            "result_ref": str(entry.get("result_ref") or ""),
            "artifact_refs": _artifact_ref_values(entry.get("artifact_refs")),
            "handoff_summary": str(entry.get("handoff_summary") or "")[:800],
        }
    )


def _batch_chapter_artifact_index(
    *,
    state: GraphLoopState,
    start: int,
    end: int,
    draft_node_id: str,
    router_node_id: str,
) -> dict[int, dict[str, dict[str, Any]]]:
    index: dict[int, dict[str, dict[str, Any]]] = {chapter: {} for chapter in range(start, end + 1)}
    for node_id, summaries in dict(state.result_history or {}).items():
        tail = _node_tail(str(node_id or ""))
        if tail not in {"chapter_draft", "chapter_unit_router"}:
            continue
        marker = "draft_round_" if tail == "chapter_draft" else "unit_route_round_"
        fallback_node_id = draft_node_id if tail == "chapter_draft" else router_node_id
        for raw_summary in list(summaries or []):
            if not isinstance(raw_summary, dict):
                continue
            if str(raw_summary.get("status") or "") != "completed":
                continue
            for chapter, refs in _chapter_artifact_refs_from_summary(raw_summary, marker=marker, start=start, end=end).items():
                summary = {
                    **dict(raw_summary),
                    "node_id": str(raw_summary.get("node_id") or fallback_node_id),
                    "artifact_refs": refs,
                    "source": "result_history",
                    "context_authority": f"{AUTHORITY}.batch_chapter_artifact_index",
                }
                current = dict(index.get(chapter, {}).get(tail) or {})
                if not current or _chapter_summary_is_newer(summary, current):
                    index.setdefault(chapter, {})[tail] = summary
    return index


def _chapter_artifact_refs_from_summary(
    summary: dict[str, Any],
    *,
    marker: str,
    start: int,
    end: int,
) -> dict[int, list[str]]:
    refs_by_chapter: dict[int, list[str]] = {}
    for ref in _artifact_ref_values(summary.get("artifact_refs")):
        if marker not in str(ref):
            continue
        chapter = _chapter_index_from_artifact_ref(ref)
        if chapter is None or chapter < start or chapter > end:
            continue
        refs_by_chapter.setdefault(chapter, []).append(ref)
    return refs_by_chapter


def _chapter_index_from_iteration_entry(entry: dict[str, Any]) -> int | None:
    chapter = _chapter_index_from_iteration_id(str(dict(entry or {}).get("iteration_id") or ""))
    if chapter is not None:
        return chapter
    for node_result in list(dict(entry or {}).get("node_results") or []):
        if not isinstance(node_result, dict):
            continue
        for ref in _artifact_ref_values(node_result.get("artifact_refs")):
            chapter = _chapter_index_from_artifact_ref(ref)
            if chapter is not None:
                return chapter
    return None


def _chapter_index_from_iteration_id(iteration_id: str) -> int | None:
    match = re.search(r"(?:^|[^A-Za-z])chapter[-_:](\d{1,4})(?:$|[^0-9])", str(iteration_id or ""))
    return int(match.group(1)) if match else None


def _chapter_index_from_artifact_ref(ref: str) -> int | None:
    match = re.search(r"(?:^|[\\/])chapter_(\d{3,4})(?:[\\/]|$)", str(ref or ""))
    return int(match.group(1)) if match else None


def _chapter_summary_is_newer(candidate: dict[str, Any], current: dict[str, Any]) -> bool:
    return _chapter_summary_sort_key(candidate) > _chapter_summary_sort_key(current)


def _chapter_summary_sort_key(summary: dict[str, Any]) -> tuple[float, int, str]:
    refs = _artifact_ref_values(summary.get("artifact_refs"))
    identity = str(summary.get("result_id") or (refs[-1] if refs else ""))
    return (
        float(summary.get("created_at") or 0.0),
        max([_round_index_from_ref(ref) for ref in refs] or [0]),
        identity,
    )


def _round_index_from_ref(ref: str) -> int:
    numbers = [int(match) for match in re.findall(r"round_(\d+)", str(ref or ""))]
    return max(numbers) if numbers else 0


def _node_id_for_tail(*, graph_config: ExecutableGraphConfig, scope_node_ids: list[str], tail: str) -> str:
    for node_id in scope_node_ids:
        if _node_tail(node_id) == tail:
            return node_id
    for node in graph_config.nodes:
        node_id = str(dict(node or {}).get("node_id") or "")
        if _node_tail(node_id) == tail:
            return node_id
    return tail


def _ordered_iteration_items(frame_results: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    items = [
        (str(iteration_id), dict(node_results))
        for iteration_id, node_results in frame_results.items()
        if isinstance(node_results, dict)
    ]
    return sorted(items, key=lambda item: _iteration_sort_key(item[0]))


def _iteration_sort_key(iteration_id: str) -> tuple[int, str]:
    numbers = [int(match) for match in re.findall(r"\d+", str(iteration_id or ""))]
    return (numbers[-1] if numbers else 0, str(iteration_id or ""))


def _revision_request_text(revision: dict[str, Any], *, current_chapter: int | None = None) -> str:
    parts: list[str] = []
    summary = str(revision.get("handoff_summary") or "").strip()
    if summary:
        parts.append(summary)
    current_parts: list[str] = []
    for item in list(revision.get("artifact_payloads") or []):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or item.get("content") or "").strip()
        if not text:
            continue
        if current_chapter is not None:
            current_text = _extract_current_chapter_revision_requirements(text, current_chapter)
            if current_text:
                current_parts.append(current_text)
                continue
            scoped = _revision_requirement_or_blocking_sections(text)
            if scoped:
                parts.append(scoped)
                continue
        else:
            parts.append(text)
    if current_parts:
        prefix = f"当前返修章：第{current_chapter}章。以下要求只用于当前章重写；返修队列中的其他章节由图循环逐章调度。"
        return "\n\n".join(dict.fromkeys([prefix, *current_parts])).strip()
    return "\n\n".join(dict.fromkeys(parts)).strip()


def _revision_requirement_or_blocking_sections(text: str) -> str:
    normalized = str(text or "")
    sections: list[str] = []
    for heading in ("返修要求", "必须修改项", "阻塞性问题", "问题清单"):
        pattern = re.compile(rf"(?m)^#{{1,4}}\s*{heading}\b.*$")
        match = pattern.search(normalized)
        if not match:
            continue
        tail = normalized[match.start() :]
        first_newline = tail.find("\n")
        search_tail = tail[first_newline + 1 :] if first_newline >= 0 else ""
        next_heading = re.search(r"(?m)^#{1,4}\s+", search_tail)
        section = tail[: first_newline + 1 + next_heading.start()] if next_heading and first_newline >= 0 else tail
        if section.strip():
            sections.append(section.strip())
    return "\n\n".join(dict.fromkeys(sections)).strip()[:8000]


def _extract_current_chapter_revision_requirements(text: str, chapter: int) -> str:
    normalized = str(text or "").strip()
    if not normalized:
        return ""
    lines = normalized.splitlines()
    selected: list[str] = []
    chapter_pattern = re.compile(rf"第\s*0*{chapter}\s*章")
    next_chapter_pattern = re.compile(r"第\s*0*\d{1,4}\s*章")
    capture = False
    for line in lines:
        if chapter_pattern.search(line):
            capture = True
            selected.append(line)
            continue
        if capture and next_chapter_pattern.search(line) and not chapter_pattern.search(line):
            break
        if capture:
            selected.append(line)
    if not selected:
        return ""
    return "\n".join(selected).strip()[:6000]


def _extract_chapter_outline_section(text: str, chapter: int) -> str:
    normalized = str(text or "")
    if not normalized:
        return ""
    pattern = re.compile(rf"(?m)^###\s*第0*{chapter}\s*章[：:].*$")
    match = pattern.search(normalized)
    if not match:
        return ""
    tail = normalized[match.start() :]
    next_match = re.search(r"(?m)^###\s*第0*\d{1,4}\s*章[：:].*$", tail[1:])
    section = tail[: next_match.start() + 1] if next_match else tail
    return section.strip()[:6000]


def _chapter_outline_title(section: str, chapter: int) -> str:
    first = str(section or "").strip().splitlines()[0] if str(section or "").strip() else ""
    return first.lstrip("#").strip() or f"第{chapter}章"


def _compact_batch_chapter_ledger(ledger: dict[str, Any]) -> dict[str, Any]:
    chapters: list[dict[str, Any]] = []
    for raw in list(ledger.get("chapters") or []):
        if not isinstance(raw, dict):
            continue
        draft = dict(raw.get("draft") or {})
        route = dict(raw.get("route") or {})
        chapters.append(
            _drop_empty(
                {
                    "chapter_index": raw.get("chapter_index"),
                    "status": str(raw.get("status") or ""),
                    "draft_artifact_refs": _artifact_ref_values(draft.get("artifact_refs")),
                    "route_artifact_refs": _artifact_ref_values(route.get("artifact_refs")),
                    "draft_source": str(draft.get("source") or ""),
                    "route_source": str(route.get("source") or ""),
                    "warnings": [str(item) for item in list(raw.get("warnings") or []) if str(item)],
                }
            )
        )
    return _drop_empty(
        {
            "authority": f"{AUTHORITY}.batch_chapter_ledger",
            "source": str(ledger.get("source") or ""),
            "batch_start_index": ledger.get("batch_start_index"),
            "batch_end_index": ledger.get("batch_end_index"),
            "expected_chapter_indexes": [int(item) for item in list(ledger.get("expected_chapter_indexes") or []) if _int_value(item, None) is not None],
            "complete_chapter_indexes": [int(item) for item in list(ledger.get("complete_chapter_indexes") or []) if _int_value(item, None) is not None],
            "missing_chapter_indexes": [int(item) for item in list(ledger.get("missing_chapter_indexes") or []) if _int_value(item, None) is not None],
            "chapters": chapters,
        }
    )


def _format_revision_template(template: str, values: dict[str, Any]) -> str:
    class _Missing(dict):
        def __missing__(self, key: str) -> str:
            return ""

    try:
        return template.format_map(_Missing(values))
    except (KeyError, IndexError, ValueError):
        return template


def _artifact_ref_values(refs: Any) -> list[str]:
    values: list[str] = []
    raw_items = refs if isinstance(refs, list) else ([refs] if refs else [])
    for raw in raw_items:
        if isinstance(raw, str):
            value = raw.strip()
        elif isinstance(raw, dict):
            value = str(raw.get("path") or raw.get("artifact_path") or raw.get("ref") or raw.get("artifact_ref") or "").strip()
        else:
            value = ""
        if value and value not in values:
            values.append(value)
    return values


def _artifact_payloads_for_refs(refs: list[str], *, max_refs: int, max_chars: int) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for ref in refs[:max_refs]:
        text, truncated = _read_artifact_text(ref, max_chars=max_chars)
        if not text:
            continue
        payloads.append(
            {
                "artifact_ref": ref,
                "content": text,
                "truncated": truncated,
                "max_chars": max_chars,
                "authority": f"{AUTHORITY}.artifact_text_projection",
            }
        )
    return payloads


def _read_artifact_text(ref: str, *, max_chars: int) -> tuple[str, bool]:
    raw = Path(str(ref or "")).expanduser()
    candidates = [raw] if raw.is_absolute() else [
        Path.cwd() / raw,
        Path.cwd().parent / raw,
        Path(__file__).resolve().parents[3] / raw,
    ]
    for path in candidates:
        try:
            resolved = path.resolve()
        except OSError:
            continue
        try:
            if not resolved.exists() or not resolved.is_file():
                continue
            text = resolved.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        return text[:max_chars], len(text) > max_chars
    return "", False


def _node_tail(node_id: str) -> str:
    return str(node_id or "").strip().rsplit("::", 1)[-1]


def _int_value(value: Any, default: int | None = 0) -> int | None:
    try:
        if value in (None, ""):
            return default
        return int(float(value))
    except Exception:
        return default


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {})}


def _safe_id(value: Any) -> str:
    text = re.sub(r"[^A-Za-z0-9_.:-]+", "_", str(value or "").strip())
    return text.strip("_")[:120] or "empty"
