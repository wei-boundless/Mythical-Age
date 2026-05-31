from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class TaskGraphSemanticRelationPreset:
    relation_id: str
    title_zh: str
    category: str
    description: str
    edge_type: str
    contract_family_id: str = ""
    payload_contract_id: str = ""
    default_parameters: dict[str, Any] = field(default_factory=dict)
    configurable_fields: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["configurable_fields"] = list(self.configurable_fields)
        payload["default_parameters"] = dict(self.default_parameters)
        return payload


SEMANTIC_RELATION_PRESETS: tuple[TaskGraphSemanticRelationPreset, ...] = (
    TaskGraphSemanticRelationPreset(
        relation_id="writing.draft_to_review",
        title_zh="草稿进入审核",
        category="writing_review",
        description="写手交付草稿产物，审核节点按质量门裁决是否通过。",
        edge_type="handoff",
        contract_family_id="writing.draft_artifact",
        payload_contract_id="contract.writing.draft_artifact.draft",
        default_parameters={"artifact_type": "draft", "handoff_mode": "structured_packet"},
        configurable_fields=("artifact_type", "quality_bar"),
    ),
    TaskGraphSemanticRelationPreset(
        relation_id="writing.review_pass_to_commit",
        title_zh="审核通过后提交",
        category="writing_review",
        description="审核节点放行产物，进入提交或下一阶段。",
        edge_type="handoff",
        contract_family_id="writing.commit_receipt",
        payload_contract_id="contract.writing.commit_receipt.approved_artifact",
        default_parameters={"verdict_key": "verdict", "required_verdict": "pass"},
        configurable_fields=("verdict_key", "required_verdict", "commit_target"),
    ),
    TaskGraphSemanticRelationPreset(
        relation_id="writing.review_revise_to_writer",
        title_zh="审核未通过返修",
        category="writing_revision",
        description="审核节点把问题清单和返修要求发回写手或返修节点。",
        edge_type="review_feedback",
        contract_family_id="writing.revision_request",
        payload_contract_id="contract.writing.revision_request.revise",
        default_parameters={"verdict_key": "verdict", "required_verdict": "revise", "max_revision_attempts": 3},
        configurable_fields=("verdict_key", "required_verdict", "max_revision_attempts", "carry_fields"),
    ),
    TaskGraphSemanticRelationPreset(
        relation_id="writing.revision_to_review",
        title_zh="返修后复审",
        category="writing_revision",
        description="返修节点把修订产物重新交给审核节点。",
        edge_type="handoff",
        contract_family_id="writing.draft_artifact",
        payload_contract_id="contract.writing.draft_artifact.revision",
        default_parameters={"artifact_type": "revision", "handoff_mode": "structured_packet"},
        configurable_fields=("artifact_type", "quality_bar"),
    ),
    TaskGraphSemanticRelationPreset(
        relation_id="writing.review_reject_to_human",
        title_zh="审核驳回转人工",
        category="writing_review",
        description="审核节点遇到无法自动修复的质量失败时，转给人工确认。",
        edge_type="conditional_feedback",
        contract_family_id="writing.review_verdict",
        payload_contract_id="contract.writing.review_verdict.reject",
        default_parameters={"verdict_key": "verdict", "required_verdict": "reject"},
        configurable_fields=("verdict_key", "required_verdict", "human_gate_role"),
    ),
    TaskGraphSemanticRelationPreset(
        relation_id="memory.read_required",
        title_zh="读取正式记忆",
        category="memory",
        description="节点运行前读取已提交记忆，缺失时按策略阻断或提醒。",
        edge_type="memory_read",
        payload_contract_id="contract.memory.read",
        default_parameters={"on_missing": "block", "version_selector": "latest_committed_before_stage_start", "limit": 50},
        configurable_fields=("repository_id", "collection_id", "record_kind", "model_visible_label", "usage_instruction", "on_missing", "limit"),
    ),
    TaskGraphSemanticRelationPreset(
        relation_id="memory.write_candidate",
        title_zh="写入候选记忆",
        category="memory",
        description="节点产出候选记忆；候选不会直接对后续节点可见。",
        edge_type="memory_write_candidate",
        contract_family_id="writing.memory_update",
        payload_contract_id="contract.memory.write_candidate",
        default_parameters={"source_output_key": "memory_candidate", "on_missing": "warn"},
        configurable_fields=("repository_id", "collection_id", "record_kind", "source_output_key"),
    ),
    TaskGraphSemanticRelationPreset(
        relation_id="memory.commit_after_review",
        title_zh="审核后提交记忆",
        category="memory",
        description="审核通过后把候选记忆提交为正式可读资料。",
        edge_type="memory_commit",
        contract_family_id="writing.memory_update",
        payload_contract_id="contract.memory.commit",
        default_parameters={"verdict_key": "verdict", "required_verdict": "pass", "visible_after": "next_clock"},
        configurable_fields=("repository_id", "collection_id", "record_kind", "approval_source_node_id", "verdict_key", "required_verdict"),
    ),
)


def list_semantic_relation_presets() -> tuple[TaskGraphSemanticRelationPreset, ...]:
    return SEMANTIC_RELATION_PRESETS


def get_semantic_relation_preset(relation_id: str) -> TaskGraphSemanticRelationPreset | None:
    target = str(relation_id or "").strip()
    if not target:
        return None
    return next((item for item in SEMANTIC_RELATION_PRESETS if item.relation_id == target), None)


def semantic_relation_catalog() -> dict[str, Any]:
    presets = [item.to_dict() for item in SEMANTIC_RELATION_PRESETS]
    categories = sorted({str(item["category"]) for item in presets})
    return {
        "authority": "task_system.task_graph_semantic_relations",
        "relations": presets,
        "categories": categories,
        "summary": {
            "semantic_relation_count": len(presets),
            "writing_relation_count": sum(1 for item in presets if str(item["category"]).startswith("writing")),
            "memory_relation_count": sum(1 for item in presets if item["category"] == "memory"),
        },
    }


def resolve_semantic_relation(relation_id: str, parameters: dict[str, Any] | None = None) -> dict[str, Any]:
    preset = get_semantic_relation_preset(relation_id)
    if preset is None:
        raise ValueError(f"Unknown task graph semantic relation: {relation_id}")
    parameters = _compact({**dict(preset.default_parameters), **dict(parameters or {})})
    payload_contract_id = _text(parameters.get("payload_contract_id"), preset.payload_contract_id)
    metadata = _base_metadata(preset, parameters)
    if preset.category == "memory":
        metadata.update(_memory_metadata(preset, parameters))
    elif preset.relation_id in {"writing.review_revise_to_writer", "writing.review_reject_to_human"}:
        metadata.update(_revision_metadata(parameters))
    elif preset.relation_id == "writing.review_pass_to_commit":
        metadata.update(_review_pass_metadata(parameters))
    else:
        metadata.update(_handoff_metadata(parameters))
    return {
        "authority": "task_system.task_graph_semantic_relation_resolver",
        "relation_id": preset.relation_id,
        "title_zh": preset.title_zh,
        "category": preset.category,
        "edge_type": preset.edge_type,
        "payload_contract_id": payload_contract_id,
        "metadata": metadata,
        "contract_bindings": _contract_bindings(preset, parameters, payload_contract_id),
    }


def _base_metadata(preset: TaskGraphSemanticRelationPreset, parameters: dict[str, Any]) -> dict[str, Any]:
    return {
        "semantic_relation_id": preset.relation_id,
        "semantic_category": preset.category,
        "semantic_title_zh": preset.title_zh,
        "semantic_parameters": parameters,
        "contract_family_id": preset.contract_family_id,
        "authority": "task_system.task_graph_semantic_relation",
    }


def _handoff_metadata(parameters: dict[str, Any]) -> dict[str, Any]:
    return {
        "handoff_mode": _text(parameters.get("handoff_mode"), "structured_packet"),
        "result_delivery_policy": _text(parameters.get("result_delivery_policy"), "contract_payload_and_refs"),
    }


def _review_pass_metadata(parameters: dict[str, Any]) -> dict[str, Any]:
    verdict_key = _text(parameters.get("verdict_key"), "verdict")
    required_verdict = _text(parameters.get("required_verdict"), "pass")
    return {
        "trigger": {verdict_key: required_verdict},
        "verdict_key": verdict_key,
        "required_verdict": required_verdict,
        "commit_target": _text(parameters.get("commit_target"), "next_stage"),
    }


def _revision_metadata(parameters: dict[str, Any]) -> dict[str, Any]:
    verdict_key = _text(parameters.get("verdict_key"), "verdict")
    required_verdict = _text(parameters.get("required_verdict"), "revise")
    carry_fields = _list(parameters.get("carry_fields")) or ["artifact_ref", "issues", "revision_request"]
    return {
        "trigger": {verdict_key: required_verdict},
        "verdict": required_verdict,
        "verdict_key": verdict_key,
        "required_verdict": required_verdict,
        "carry": carry_fields,
        "max_revision_attempts": _int(parameters.get("max_revision_attempts"), 3),
    }


def _memory_metadata(preset: TaskGraphSemanticRelationPreset, parameters: dict[str, Any]) -> dict[str, Any]:
    repository_id = _text(parameters.get("repository_id") or parameters.get("repository"))
    collection_id = _text(parameters.get("collection_id") or parameters.get("collection"), "default")
    record_kind = _text(parameters.get("record_kind"), f"{collection_id}_record")
    selector = {
        "collection": collection_id,
        "record_kind": record_kind,
    }
    operation = preset.edge_type.replace("memory_", "")
    if operation == "read":
        selector["status_filter"] = ["committed"]
        selector["limit"] = _int(parameters.get("limit"), 50)
    metadata = {
        "repository": repository_id,
        "repository_id": repository_id,
        "collection": collection_id,
        "selector": selector,
        "record_kind": record_kind,
        "version_selector": _text(parameters.get("version_selector"), "latest_committed_before_stage_start"),
        "on_missing": _text(parameters.get("on_missing"), "block" if operation == "read" else "warn"),
        "model_visible_label": _text(parameters.get("model_visible_label"), collection_id if operation == "read" else ""),
        "usage_instruction": _text(parameters.get("usage_instruction"), _memory_instruction(operation, collection_id)),
    }
    if operation == "write_candidate":
        metadata.update(
            {
                "source_output_key": _text(parameters.get("source_output_key"), "memory_candidate"),
                "record_key": _text(parameters.get("record_key"), f"{repository_id}.{collection_id}.current" if repository_id else f"{collection_id}.current"),
                "materialization_policy": dict(parameters.get("materialization_policy") or {}),
            }
        )
    if operation == "commit":
        visible_after = _text(parameters.get("visible_after"), "next_clock")
        metadata.update(
            {
                "candidate_ref_key": _text(parameters.get("candidate_ref_key"), "memory_candidate_ref"),
                "verdict_key": _text(parameters.get("verdict_key"), "verdict"),
                "required_verdict": _text(parameters.get("required_verdict"), "pass"),
                "approval_source_node_id": _text(parameters.get("approval_source_node_id")),
                "approval_policy": "approved_upstream_review_gate",
                "commit_visibility_policy": {"required_status": "committed", "visible_after": visible_after},
            }
        )
    return metadata


def _contract_bindings(
    preset: TaskGraphSemanticRelationPreset,
    parameters: dict[str, Any],
    payload_contract_id: str,
) -> dict[str, Any]:
    bindings: dict[str, Any] = {
        "schema": {"payload_contract_id": payload_contract_id},
        "semantic": {
            "relation_id": preset.relation_id,
            "category": preset.category,
            "title_zh": preset.title_zh,
            "contract_family_id": preset.contract_family_id,
            "parameters": parameters,
        },
    }
    if preset.category == "memory":
        bindings["memory"] = {
            "operation": preset.edge_type.replace("memory_", ""),
            "repository_id": _text(parameters.get("repository_id") or parameters.get("repository")),
            "collection_id": _text(parameters.get("collection_id") or parameters.get("collection"), "default"),
        }
    return _compact_nested(bindings)


def _memory_instruction(operation: str, collection_id: str) -> str:
    if operation == "read":
        return f"你只能把已提交的 {collection_id} 记忆作为事实来源；缺失内容必须报告，不得自行补写成事实。"
    if operation == "write_candidate":
        return f"你只负责提出 {collection_id} 候选记忆，不能把候选内容当作已提交事实。"
    if operation == "commit":
        return f"只有审核通过的 {collection_id} 候选记忆可以提交为正式资料。"
    return ""


def _compact(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if value not in ("", None, [], {})
    }


def _compact_nested(payload: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, dict):
            compacted = _compact_nested(value)
            if compacted:
                result[key] = compacted
        elif value not in ("", None, [], {}):
            result[key] = value
    return result


def _text(value: Any, fallback: str = "") -> str:
    result = str(value or "").strip()
    return result or fallback


def _int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _list(value: Any) -> list[str]:
    if isinstance(value, str):
        raw = value.replace("，", ",").replace("\n", ",").split(",")
    elif isinstance(value, (list, tuple, set)):
        raw = list(value)
    else:
        raw = []
    return [str(item).strip() for item in raw if str(item).strip()]
