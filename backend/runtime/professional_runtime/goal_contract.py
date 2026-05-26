from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class ProfessionalTaskGoalContract:
    contract_id: str
    goal: str
    required_material_paths: list[str] = field(default_factory=list)
    required_output_paths: list[str] = field(default_factory=list)
    material_types: list[str] = field(default_factory=list)
    required_tool_kinds: list[str] = field(default_factory=list)
    required_output_kinds: list[str] = field(default_factory=list)
    requires_material_review: bool = False
    requires_write_output: bool = False
    requires_verification_command: bool = False
    requires_delegation: bool = False
    response_must_include: list[str] = field(default_factory=list)
    forbidden_visible_markers: list[str] = field(default_factory=list)
    authority: str = "orchestration.professional_task_goal_contract"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _goal_contract_from_semantic_contract(
    *,
    task_run_id: str,
    user_message: str,
    semantic_contract: dict[str, Any],
) -> ProfessionalTaskGoalContract:
    materials = [dict(item) for item in list(semantic_contract.get("materials") or []) if isinstance(item, dict)]
    obligation = dict(semantic_contract.get("execution_obligation") or {})
    obligation_reads = [
        dict(item)
        for item in list(obligation.get("required_reads") or [])
        if isinstance(item, dict)
    ]
    obligation_writes = [
        dict(item)
        for item in list(obligation.get("required_writes") or [])
        if isinstance(item, dict)
    ]
    obligation_commands = [
        dict(item)
        for item in list(obligation.get("required_commands") or [])
        if isinstance(item, dict)
    ]
    obligation_verifications = [
        dict(item)
        for item in list(obligation.get("required_verifications") or [])
        if isinstance(item, dict)
    ]
    forbidden_actions = {
        str(item).strip()
        for item in list(obligation.get("forbidden_actions") or [])
        if str(item).strip()
    }
    raw_material_paths = _dedupe_strings(
        [
            *[str(item.get("path") or "").strip() for item in materials if str(item.get("path") or "").strip()],
            *[str(item.get("path") or "").strip() for item in obligation_reads if str(item.get("path") or "").strip()],
        ]
    )
    goal_text = str(semantic_contract.get("user_goal") or user_message or "").strip()
    output_paths = _structured_output_paths(
        semantic_contract=semantic_contract,
        obligation_writes=obligation_writes,
    )
    material_types = _dedupe_strings(
        [
            *[str(item.get("kind") or "").strip() for item in materials if str(item.get("kind") or "").strip()],
            *[str(item.get("kind") or "").strip() for item in obligation_reads if str(item.get("kind") or "").strip()],
            *[_path_suffix(path).lstrip(".") for path in raw_material_paths if _path_suffix(path)],
        ]
    )
    material_paths = [
        path
        for path in raw_material_paths
        if path and not _same_path_member(path, output_paths)
    ]
    required_actions = {
        str(item).strip()
        for item in list(semantic_contract.get("required_actions") or [])
        if str(item).strip()
    }
    deliverables = [
        str(item).strip()
        for item in list(semantic_contract.get("deliverables") or [])
        if str(item).strip()
    ]
    write_forbidden = bool(forbidden_actions.intersection({"modify_code", "write_file", "edit_file"}))
    requires_write = bool(obligation_writes) and not write_forbidden
    requires_verify = bool(obligation_commands or obligation_verifications)
    response_terms = _dedupe_strings(
        [
            *[str(item).strip() for item in list(semantic_contract.get("response_must_include") or []) if str(item).strip()],
        ]
    )
    return ProfessionalTaskGoalContract(
        contract_id=f"professional-goal-contract:{task_run_id}",
        goal=goal_text,
        required_material_paths=material_paths,
        required_output_paths=output_paths,
        material_types=material_types,
        required_tool_kinds=_dedupe_strings(
            [
                *[
                    item
                    for item in list(required_actions)
                    if _semantic_action_is_active(
                        item,
                        material_paths=material_paths,
                        requires_write=requires_write,
                        requires_verify=requires_verify,
                    )
                ],
                *(["write_output"] if requires_write else []),
                *(["verify_command"] if requires_verify else []),
            ]
        ),
        required_output_kinds=["final_answer", *deliverables],
        requires_material_review=bool(material_paths),
        requires_write_output=requires_write,
        requires_verification_command=requires_verify,
        requires_delegation=False,
        response_must_include=response_terms,
        forbidden_visible_markers=_forbidden_visible_markers(),
    )


def _structured_output_paths(
    *,
    semantic_contract: dict[str, Any],
    obligation_writes: list[dict[str, Any]],
) -> list[str]:
    output_schema = dict(semantic_contract.get("output_schema") or {})
    structured_values = [
        *[str(item.get("path") or "").strip() for item in obligation_writes if str(item.get("path") or "").strip()],
        *[str(item or "").strip() for item in list(semantic_contract.get("required_output_paths") or []) if str(item or "").strip()],
        *[str(item or "").strip() for item in list(semantic_contract.get("output_paths") or []) if str(item or "").strip()],
        *[str(item or "").strip() for item in list(output_schema.get("required_output_paths") or []) if str(item or "").strip()],
        *[str(item or "").strip() for item in list(output_schema.get("output_paths") or []) if str(item or "").strip()],
    ]
    return _dedupe_strings(structured_values)


def _semantic_action_is_active(
    action: Any,
    *,
    material_paths: list[str],
    requires_write: bool,
    requires_verify: bool,
) -> bool:
    item = str(action or "").strip()
    if not item:
        return False
    if item == "read_material":
        return bool(material_paths)
    if item in {"apply_real_change", "integrate_asset"}:
        return bool(requires_write)
    if item in {"run_verification", "run_browser_verification"}:
        return bool(requires_verify)
    return True


def _same_path_member(path: str, paths: list[str]) -> bool:
    normalized = _normalize_path_for_match(path)
    return any(normalized == _normalize_path_for_match(item) for item in paths)


def _path_suffix(path: str) -> str:
    text = str(path or "").strip()
    if "." not in text:
        return ""
    suffix = "." + text.rsplit(".", 1)[-1].lower()
    return suffix if len(suffix) > 1 else ""


def _forbidden_visible_markers() -> list[str]:
    return [
        "<｜｜DSML",
        "｜｜parameter",
        "tool_calls",
        "invoke name=",
        "<tool_call",
        'name="read_file"',
        'name="search_text"',
        'name="search_files"',
        'name="delegate_to_agent"',
    ]


def _goal_contract_instruction(goal_contract: ProfessionalTaskGoalContract | None) -> str:
    if goal_contract is None:
        return ""
    lines: list[str] = ["目标契约："]
    if goal_contract.required_material_paths:
        lines.append("必须取得真实材料观察：" + "、".join(goal_contract.required_material_paths[:6]) + "。")
    if goal_contract.requires_write_output:
        lines.append("目标契约要求真实写入或修改产物；必须使用 write_file 或 edit_file，不能只口头声称完成。")
    if goal_contract.requires_verification_command:
        lines.append("目标契约要求命令验证；完成写入或修改后必须使用 terminal 返回真实验证结果。")
    if goal_contract.requires_delegation:
        lines.append("如主 Agent 不能稳定读取专业材料，只能通过 delegate_to_agent 发起受控材料核对，并综合回传证据。")
    if goal_contract.response_must_include:
        lines.append("最终回答必须覆盖：" + "、".join(goal_contract.response_must_include) + "。")
    lines.append("最终回答不得包含 DSML、tool_calls、invoke、工具参数或伪工具调用。")
    return "\n".join(lines) + "\n"


def _normalize_path_for_match(path: str) -> str:
    value = str(path or "").strip().strip("`'\"“”‘’").replace("\\", "/")
    match = re.search(r"(?i)^(.+?\.(?:json|py|md|txt|log|csv|tsv|xlsx|xls|pdf|yaml|yml|toml|docx|pptx))(?=$|[\s，,。；;:：、])", value)
    if match:
        value = match.group(1)
    return value.lower()


def _dedupe_strings(values: list[Any] | tuple[Any, ...]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
