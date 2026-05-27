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


def build_graph_flow_state(
    *,
    coordination_task_payload: dict[str, Any],
    topology_template: dict[str, Any],
    communication_protocol_payload: dict[str, Any],
) -> dict[str, Any]:
    metadata = dict(coordination_task_payload.get("metadata") or {})
    stages = _normalize_stage_sequence(
        stage_sequence=metadata.get("stage_sequence"),
        topology_template=topology_template,
        communication_protocol_payload=communication_protocol_payload,
    )
    if not stages:
        return {}
    for index, stage in enumerate(stages):
        if stage["status"] != "pending":
            continue
        stages[index] = {**stage, "status": "running" if index == 0 else "pending"}
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
                    "node_id": str(item.get("node_id") or "").strip(),
                    "role": str(item.get("role") or "").strip(),
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
