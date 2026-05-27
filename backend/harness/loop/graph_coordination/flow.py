from __future__ import annotations

from typing import Any


_DEFAULT_STAGE_TITLES = {
    "idea_proposal": "创意提出",
    "idea_review": "创意审核",
    "approval_signal": "审核通过",
    "draft_submission": "正式编写",
    "content_issue": "内容纠察",
    "revision_request": "修正循环",
    "acceptance_result": "内容验收",
}


def build_coordination_flow_state(
    *,
    coordination_task_payload: dict[str, Any],
    topology_template: dict[str, Any],
    communication_protocol_payload: dict[str, Any],
) -> dict[str, Any]:
    metadata = dict(coordination_task_payload.get("metadata") or {})
    stage_sequence = metadata.get("stage_sequence")
    stages = _normalize_stage_sequence(
        stage_sequence=stage_sequence,
        topology_template=topology_template,
        communication_protocol_payload=communication_protocol_payload,
    )
    if not stages:
        return {}
    for index, stage in enumerate(stages):
        if stage["status"] != "pending":
            continue
        stages[index] = {
            **stage,
            "status": "running" if index == 0 else "pending",
        }
        break
    revision_stage_ids = [
        stage["stage_id"]
        for stage in stages
        if stage.get("loop_kind") == "revision_loop"
    ]
    return {
        "coordination_mode": str(coordination_task_payload.get("coordination_mode") or "review_merge"),
        "current_stage_id": next((stage["stage_id"] for stage in stages if stage["status"] == "running"), ""),
        "stages": stages,
        "revision_loop_enabled": bool(revision_stage_ids),
        "revision_stage_ids": revision_stage_ids,
        "max_revision_cycles": max(0, int(metadata.get("max_revision_cycles") or (1 if revision_stage_ids else 0))),
        "required_revision_cycles": max(0, int(metadata.get("required_revision_cycles") or (1 if revision_stage_ids else 0))),
        "completed_revision_cycles": 0,
        "acceptance_stage_id": next(
            (stage["stage_id"] for stage in stages if stage.get("message_type") == "acceptance_result"),
            "",
        ),
        "protocol_message_types": [
            str(item).strip()
            for item in list(communication_protocol_payload.get("message_types") or [])
            if str(item).strip()
        ],
        "topology_node_ids": [
            str(dict(node).get("node_id") or "").strip()
            for node in list(topology_template.get("nodes") or [])
            if str(dict(node).get("node_id") or "").strip()
        ],
    }


def finalize_coordination_flow_state(
    flow_state: dict[str, Any],
    *,
    accepted: bool,
    final_result_ref: str,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    if not flow_state:
        return {}, ()
    stages = []
    unresolved_issue_refs: list[str] = []
    required_revision_cycles = max(0, int(flow_state.get("required_revision_cycles") or 0))
    completed_revision_cycles = required_revision_cycles if accepted else 0
    for stage in list(flow_state.get("stages") or []):
        normalized = dict(stage)
        message_type = str(normalized.get("message_type") or "").strip()
        loop_kind = str(normalized.get("loop_kind") or "").strip()
        if accepted:
            if loop_kind == "revision_loop" and required_revision_cycles <= 0:
                normalized["status"] = "skipped"
            else:
                normalized["status"] = "completed"
        else:
            if message_type == "acceptance_result":
                normalized["status"] = "failed"
                unresolved_issue_refs.append(f"stage:{normalized.get('stage_id')}")
            elif loop_kind == "revision_loop":
                normalized["status"] = "revision_requested"
                unresolved_issue_refs.append(f"stage:{normalized.get('stage_id')}")
            elif normalized.get("status") == "pending":
                unresolved_issue_refs.append(f"stage:{normalized.get('stage_id')}")
        normalized["final_result_ref"] = final_result_ref
        stages.append(normalized)
    finalized = {
        **dict(flow_state),
        "current_stage_id": "",
        "next_stage_id": "",
        "next_stage_title": "",
        "next_task_ref": "",
        "stages": stages,
        "completed_revision_cycles": completed_revision_cycles,
        "accepted": bool(accepted),
        "final_result_ref": str(final_result_ref or ""),
    }
    return finalized, tuple(dict.fromkeys(unresolved_issue_refs))


def advance_coordination_flow_state(
    flow_state: dict[str, Any],
    *,
    final_result_ref: str,
    next_task_ref: str = "",
) -> dict[str, Any]:
    if not flow_state:
        return {}
    stages = [dict(item) for item in list(flow_state.get("stages") or []) if isinstance(item, dict)]
    if not stages:
        return {}
    current_index = next(
        (index for index, stage in enumerate(stages) if str(stage.get("status") or "").strip() == "running"),
        -1,
    )
    if current_index < 0:
        current_index = next(
            (index for index, stage in enumerate(stages) if str(stage.get("status") or "").strip() == "pending"),
            -1,
        )
    next_stage_id = ""
    next_stage_title = ""
    advanced_stages: list[dict[str, Any]] = []
    for index, stage in enumerate(stages):
        normalized = dict(stage)
        if index == current_index:
            normalized["status"] = "completed"
            normalized["final_result_ref"] = str(final_result_ref or "")
        elif current_index >= 0 and index == current_index + 1:
            normalized["status"] = "running"
            next_stage_id = str(normalized.get("stage_id") or "").strip()
            next_stage_title = str(normalized.get("title") or next_stage_id).strip()
        elif current_index >= 0 and index > current_index + 1 and str(normalized.get("status") or "").strip() == "running":
            normalized["status"] = "pending"
        advanced_stages.append(normalized)
    completed_stage_ids = [
        str(stage.get("stage_id") or "").strip()
        for stage in advanced_stages
        if str(stage.get("status") or "").strip() == "completed"
    ]
    return {
        **dict(flow_state),
        "current_stage_id": next_stage_id,
        "current_task_completed": current_index >= 0,
        "completed_stage_ids": [item for item in completed_stage_ids if item],
        "next_stage_id": next_stage_id,
        "next_stage_title": next_stage_title,
        "next_task_ref": str(next_task_ref or ""),
        "accepted": False,
        "final_result_ref": str(final_result_ref or ""),
        "stages": advanced_stages,
    }


def summarize_coordination_flow(flow_state: dict[str, Any]) -> dict[str, Any]:
    stages = [dict(item) for item in list(flow_state.get("stages") or []) if isinstance(item, dict)]
    return {
        "stage_count": len(stages),
        "current_stage_id": str(flow_state.get("current_stage_id") or ""),
        "revision_loop_enabled": bool(flow_state.get("revision_loop_enabled") is True),
        "required_revision_cycles": int(flow_state.get("required_revision_cycles") or 0),
        "completed_revision_cycles": int(flow_state.get("completed_revision_cycles") or 0),
        "accepted": bool(flow_state.get("accepted") is True),
        "stage_statuses": [
            {
                "stage_id": str(stage.get("stage_id") or ""),
                "status": str(stage.get("status") or ""),
                "message_type": str(stage.get("message_type") or ""),
            }
            for stage in stages
        ],
    }


def build_coordination_node_status_map(flow_state: dict[str, Any]) -> dict[str, dict[str, str]]:
    stages = [dict(item) for item in list(flow_state.get("stages") or []) if isinstance(item, dict)]
    node_status_map: dict[str, dict[str, str]] = {}
    for stage in stages:
        node_id = str(stage.get("node_id") or "").strip()
        if not node_id:
            continue
        stage_status = str(stage.get("status") or "").strip()
        node_status_map[node_id] = {
            "stage_id": str(stage.get("stage_id") or "").strip(),
            "message_type": str(stage.get("message_type") or "").strip(),
            "stage_status": stage_status,
            "node_run_status": _node_run_status_from_stage_status(stage_status),
        }
    return node_status_map


def _normalize_stage_sequence(
    *,
    stage_sequence: Any,
    topology_template: dict[str, Any],
    communication_protocol_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    stages: list[dict[str, Any]] = []
    if isinstance(stage_sequence, list):
        for index, item in enumerate(stage_sequence, start=1):
            if not isinstance(item, dict):
                continue
            stage_id = str(item.get("stage_id") or f"stage_{index}").strip()
            if not stage_id:
                continue
            message_type = str(item.get("message_type") or "").strip()
            node_id = str(item.get("node_id") or "").strip()
            role = str(item.get("role") or "").strip()
            stages.append(
                {
                    **{
                        key: value
                        for key, value in item.items()
                        if key
                        not in {
                            "stage_id",
                            "title",
                            "node_id",
                            "role",
                            "task_ref",
                            "message_type",
                            "status",
                            "loop_kind",
                        }
                    },
                    "stage_id": stage_id,
                    "title": str(item.get("title") or _DEFAULT_STAGE_TITLES.get(message_type, stage_id)).strip(),
                    "node_id": node_id,
                    "role": role,
                    "task_ref": str(item.get("task_ref") or "").strip(),
                    "message_type": message_type,
                    "status": "pending",
                    "loop_kind": str(item.get("loop_kind") or ("revision_loop" if message_type == "revision_request" else "")).strip(),
                }
            )
    if stages:
        return stages
    nodes = [dict(item) for item in list(topology_template.get("nodes") or []) if isinstance(item, dict)]
    if nodes:
        for index, node in enumerate(nodes, start=1):
            stage_id = str(node.get("stage_id") or node.get("node_id") or f"stage_{index}").strip()
            if not stage_id:
                continue
            node_type = str(node.get("node_type") or "").strip()
            message_type = str(node.get("message_type") or "message/send").strip()
            loop_kind = str(node.get("loop_kind") or "").strip()
            if not loop_kind and node_type == "revision":
                loop_kind = "revision_loop"
            stages.append(
                {
                    "stage_id": stage_id,
                    "title": str(node.get("title") or stage_id).strip(),
                    "node_id": str(node.get("node_id") or stage_id).strip(),
                    "role": str(node.get("role") or "").strip(),
                    "task_ref": str(node.get("task_id") or node.get("task_ref") or "").strip(),
                    "message_type": message_type,
                    "status": "pending",
                    "loop_kind": loop_kind,
                }
            )
    if stages:
        return stages
    message_types = [
        str(item).strip()
        for item in list(communication_protocol_payload.get("message_types") or [])
        if str(item).strip()
    ]
    for index, message_type in enumerate(message_types, start=1):
        node = nodes[min(index - 1, len(nodes) - 1)] if nodes else {}
        stage_id = f"stage_{index}"
        stages.append(
            {
                "stage_id": stage_id,
                "title": _DEFAULT_STAGE_TITLES.get(message_type, message_type or stage_id),
                "node_id": str(node.get("node_id") or "").strip(),
                "role": str(node.get("role") or "").strip(),
                "task_ref": str(node.get("task_id") or node.get("task_ref") or "").strip(),
                "message_type": message_type,
                "status": "pending",
                "loop_kind": "revision_loop" if message_type == "revision_request" else "",
            }
        )
    return stages


def _node_run_status_from_stage_status(stage_status: str) -> str:
    normalized = str(stage_status or "").strip()
    if normalized == "running":
        return "running"
    if normalized in {"completed", "skipped"}:
        return "completed"
    if normalized in {"failed", "revision_requested"}:
        return "failed"
    return "pending"

