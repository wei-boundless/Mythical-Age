from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from prompting.strategy_prototypes import strategy_prototype_for_task_goal
from project_layout import ProjectLayout
from task_system.domains import bind_task_domain
from task_system.goal_profiles import bind_task_goal_profile, get_task_goal_profile


_PATH_RE = re.compile(
    r"(?P<path>(?:[A-Za-z]:)?(?:[./\\]?[\w\u4e00-\u9fff @()：:（），,\-]+[\\/])+[\w\u4e00-\u9fff @()：:（），,.\-]+"
    r"|[\w\u4e00-\u9fff @()\-./\\]+?\.(?:json|py|md|txt|log|csv|tsv|xlsx|pdf|yaml|yml|toml))",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class TaskRequirementContract:
    contract_id: str
    task_goal_type: str
    strategy_prototype_id: str
    user_goal: str
    domain: str
    execution_obligation: dict[str, Any] = field(default_factory=dict)
    materials: tuple[dict[str, Any], ...] = ()
    deliverables: tuple[str, ...] = ()
    required_reasoning_steps: tuple[str, ...] = ()
    required_actions: tuple[str, ...] = ()
    forbidden_actions: tuple[str, ...] = ()
    material_handling_policy: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    validation_schema: dict[str, Any] = field(default_factory=dict)
    professional_profile_id: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.task_requirement_contract"

    def __post_init__(self) -> None:
        if self.authority != "task_system.task_requirement_contract":
            raise ValueError("TaskRequirementContract authority must be task_system.task_requirement_contract")
        if not self.contract_id:
            raise ValueError("TaskRequirementContract requires contract_id")
        if not self.task_goal_type:
            raise ValueError("TaskRequirementContract requires task_goal_type")
        if not self.strategy_prototype_id:
            raise ValueError("TaskRequirementContract requires strategy_prototype_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["execution_obligation"] = dict(self.execution_obligation or {})
        payload["materials"] = [dict(item) for item in self.materials]
        payload["deliverables"] = list(self.deliverables)
        payload["required_reasoning_steps"] = list(self.required_reasoning_steps)
        payload["required_actions"] = list(self.required_actions)
        payload["forbidden_actions"] = list(self.forbidden_actions)
        return payload


def build_task_requirement_contract(
    *,
    session_id: str,
    task_id: str,
    user_goal: str,
    query_understanding: dict[str, Any] | None = None,
    current_turn_context: dict[str, Any] | None = None,
    explicit_inputs: dict[str, Any] | None = None,
    execution_obligation: dict[str, Any] | None = None,
) -> TaskRequirementContract:
    understanding = dict(query_understanding or {})
    current_turn = dict(current_turn_context or {})
    inputs = {
        **dict(explicit_inputs or {}),
        **dict(current_turn.get("explicit_inputs") or {}),
    }
    obligation = dict(execution_obligation or current_turn.get("execution_obligation") or {})
    task_goal_spec = dict(current_turn.get("task_goal_spec") or current_turn.get("goal_frame") or {})
    task_goal_type = _resolve_task_goal_type(
        user_goal=user_goal,
        materials=(),
        query_understanding=understanding,
        current_turn_context=current_turn,
        task_goal_spec=task_goal_spec,
    )
    materials = tuple(
        _filter_output_materials(
            _merge_materials(
                _collect_materials(
                    user_goal=user_goal,
                    explicit_inputs=inputs,
                    current_turn=current_turn,
                    task_goal_type=task_goal_type,
                ),
                [dict(item) for item in list(obligation.get("required_reads") or []) if isinstance(item, dict)],
            ),
            task_goal_spec=task_goal_spec,
            user_goal=user_goal,
        )
    )
    goal_profile = get_task_goal_profile(task_goal_type)
    goal_profile_binding = bind_task_goal_profile(
        session_id=session_id,
        task_id=task_id,
        task_goal_type=task_goal_type,
        task_goal_spec=task_goal_spec,
    )
    profile = str(getattr(goal_profile, "professional_profile_id", "") or _professional_profile_id(task_goal_type))
    prototype = strategy_prototype_for_task_goal(task_goal_type)
    deliverables = _contract_deliverables(
        task_goal_type=task_goal_type,
        obligation=obligation,
    )
    domain_value = str(getattr(goal_profile, "task_domain", "") or _domain_for_goal_type(task_goal_type, understanding))
    task_domain_binding = bind_task_domain(
        base_dir=_backend_base_dir(),
        task_id=task_id,
        requested_domain=str(task_goal_spec.get("task_domain") or domain_value),
        task_goal_domain=domain_value,
        goal_evidence=dict(task_goal_spec.get("evidence") or {}),
        forbidden_actions=tuple(task_goal_spec.get("forbidden_actions") or ()),
    )
    return TaskRequirementContract(
        contract_id=f"semantic-task:{session_id}:{task_id}",
        task_goal_type=task_goal_type,
        strategy_prototype_id=prototype.prototype_id,
        user_goal=str(user_goal or "").strip(),
        domain=domain_value,
        execution_obligation=obligation,
        materials=materials,
        deliverables=tuple(deliverables),
        required_reasoning_steps=tuple(_reasoning_steps_for_goal_type(task_goal_type)),
        required_actions=tuple(
            _dedupe(
                [
                    *_required_actions_for_goal_type(task_goal_type, materials=materials),
                    *_required_actions_for_obligation(obligation),
                ]
            )
        ),
        forbidden_actions=tuple(
            _dedupe(
                [
                    *_forbidden_actions_for_goal_type(
                        task_goal_type,
                        write_required=_obligation_has_writes(obligation),
                        write_forbidden=_obligation_forbids_write(obligation),
                    ),
                    *[
                        str(item).strip()
                        for item in list(obligation.get("forbidden_actions") or [])
                        if str(item).strip()
                    ],
                ]
            )
        ),
        material_handling_policy=_material_policy_for_goal_type(task_goal_type, materials=materials, execution_obligation=obligation),
        output_schema=_output_schema_for_goal_type(
            task_goal_type,
            deliverables=deliverables,
        ),
        validation_schema=_validation_schema_for_goal_type(task_goal_type, execution_obligation=obligation),
        professional_profile_id=profile,
        diagnostics={
            "task_goal_spec": task_goal_spec,
            "task_domain_binding": task_domain_binding.to_dict(),
            "goal_hypothesis_set": dict(dict(task_goal_spec.get("evidence") or {}).get("goal_hypothesis_set") or {}),
            "rejected_goal_candidates": [
                dict(item)
                for item in list(task_goal_spec.get("rejected_goal_candidates") or [])
                if isinstance(item, dict)
            ],
            "unacceptable_outcomes": [
                str(item).strip()
                for item in list(task_goal_spec.get("unacceptable_outcomes") or [])
                if str(item).strip()
            ],
            "ambiguity_points": [
                str(item).strip()
                for item in list(task_goal_spec.get("ambiguity_points") or [])
                if str(item).strip()
            ],
            "task_goal_profile_binding": goal_profile_binding.to_dict(),
            "material_count": len(materials),
            "material_kinds": sorted({str(item.get("kind") or "") for item in materials if item.get("kind")}),
            "explicit_mode": str(current_turn.get("interaction_mode") or current_turn.get("runtime_interaction_mode") or ""),
            "execution_obligation_summary": _obligation_summary(obligation),
            "strategy_prototype": prototype.to_dict(),
        },
    )


def task_requirement_contract_from_payload(payload: dict[str, Any] | None) -> TaskRequirementContract | None:
    item = dict(payload or {})
    if not item:
        return None
    try:
        return TaskRequirementContract(
            contract_id=str(item.get("contract_id") or ""),
            task_goal_type=str(item.get("task_goal_type") or ""),
            strategy_prototype_id=str(item.get("strategy_prototype_id") or item.get("task_goal_type") or ""),
            user_goal=str(item.get("user_goal") or ""),
            domain=str(item.get("domain") or ""),
            execution_obligation=dict(item.get("execution_obligation") or {}),
            materials=tuple(dict(value) for value in list(item.get("materials") or []) if isinstance(value, dict)),
            deliverables=tuple(str(value) for value in list(item.get("deliverables") or []) if str(value).strip()),
            required_reasoning_steps=tuple(
                str(value) for value in list(item.get("required_reasoning_steps") or []) if str(value).strip()
            ),
            required_actions=tuple(str(value) for value in list(item.get("required_actions") or []) if str(value).strip()),
            forbidden_actions=tuple(str(value) for value in list(item.get("forbidden_actions") or []) if str(value).strip()),
            material_handling_policy=dict(item.get("material_handling_policy") or {}),
            output_schema=dict(item.get("output_schema") or {}),
            validation_schema=dict(item.get("validation_schema") or {}),
            professional_profile_id=str(item.get("professional_profile_id") or ""),
            diagnostics=dict(item.get("diagnostics") or {}),
        )
    except ValueError:
        return None


def _backend_base_dir() -> Path:
    return ProjectLayout.from_backend_dir(Path(__file__).resolve().parents[2]).backend_dir


def _resolve_task_goal_type(
    *,
    user_goal: str,
    materials: tuple[dict[str, Any], ...],
    query_understanding: dict[str, Any],
    current_turn_context: dict[str, Any],
    task_goal_spec: dict[str, Any] | None = None,
) -> str:
    if _is_task_graph_node_runtime_context(current_turn_context):
        return "task_graph_node_execution"
    goal_frame = dict(task_goal_spec or {})
    framed_type = str(goal_frame.get("task_goal_type") or "").strip()
    if framed_type:
        return framed_type
    explicit = str(
        current_turn_context.get("semantic_task_type")
        or current_turn_context.get("task_goal_type")
        or dict(current_turn_context.get("task_requirement_contract") or {}).get("task_goal_type")
        or ""
    ).strip()
    if explicit:
        return explicit
    model_turn_decision = dict(current_turn_context.get("model_turn_decision") or {})
    if model_turn_decision:
        concrete_model_goal = str(model_turn_decision.get("task_goal_type") or "").strip()
        if concrete_model_goal:
            return concrete_model_goal
    raise RuntimeError("ModelTurnDecision.task_goal_type is required to resolve task goal type")


def _task_goal_spec_type_is_authoritative(task_goal_type: str, task_goal_spec: dict[str, Any]) -> bool:
    normalized = str(task_goal_type or "").strip()
    if normalized in {"game_vertical_slice_delivery", "frontend_app_delivery"}:
        return True
    evidence = dict(task_goal_spec.get("evidence") or {})
    signals = {
        str(item).strip()
        for item in list(evidence.get("goal_signals") or [])
        if str(item).strip()
    }
    if "legacy_fallback" in signals:
        return False
    return bool(normalized)


def _collect_materials(
    *,
    user_goal: str,
    explicit_inputs: dict[str, Any],
    current_turn: dict[str, Any],
    task_goal_type: str,
) -> list[dict[str, Any]]:
    materials: list[dict[str, Any]] = []
    seen: set[str] = set()
    allow_goal_scan = _task_goal_allows_user_goal_material_scan(task_goal_type)
    allow_broad_explicit_paths = _task_goal_allows_broad_explicit_material_paths(task_goal_type)

    def add(path: str, *, role: str = "material", required: bool = True) -> None:
        normalized = _normalize_path(path)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        materials.append(
            {
                "path": normalized,
                "kind": _kind_from_path(normalized),
                "role": role,
                "required": required,
            }
        )

    for key, role in (
        ("explicit_json_path", "failure_report"),
        ("explicit_dataset_path", "dataset"),
        ("explicit_pdf_path", "document"),
        ("path", "material"),
        ("file_path", "material"),
    ):
        value = explicit_inputs.get(key) or current_turn.get(key)
        if isinstance(value, str):
            add(value, role=role)
    for key in ("material_paths", "input_paths", "files"):
        for value in list(explicit_inputs.get(key) or current_turn.get(key) or []):
            if isinstance(value, str):
                add(value)
            elif isinstance(value, dict):
                add(str(value.get("path") or ""), role=str(value.get("role") or "material"), required=value.get("required") is not False)
    if allow_broad_explicit_paths:
        for key in ("paths",):
            for value in list(explicit_inputs.get(key) or current_turn.get(key) or []):
                if isinstance(value, str):
                    add(value)
                elif isinstance(value, dict):
                    add(str(value.get("path") or ""), role=str(value.get("role") or "material"), required=value.get("required") is not False)
    if allow_goal_scan:
        for match in _PATH_RE.finditer(str(user_goal or "")):
            path = _complete_partial_known_root_path(match.group("path"), text=str(user_goal or ""), start=match.start())
            if _path_looks_like_command_argument(text=str(user_goal or ""), start=match.start(), path=path):
                continue
            add(path, role="failure_report" if path.lower().endswith(".json") else "material")
    return materials


def _task_goal_allows_user_goal_material_scan(task_goal_type: str) -> bool:
    return str(task_goal_type or "").strip() in {
        "inspection",
        "test_report_triage",
        "material_synthesis",
        "pdf_question_answer",
        "structured_data_analysis",
        "runtime_trace_analysis",
        "code_fix_execution",
    }


def _task_goal_allows_broad_explicit_material_paths(task_goal_type: str) -> bool:
    return str(task_goal_type or "").strip() not in {
        "game_vertical_slice_delivery",
        "frontend_app_delivery",
        "artifact_delivery",
    }


def _merge_materials(primary: list[dict[str, Any]], obligation_reads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(item: dict[str, Any]) -> None:
        path = _normalize_path(str(item.get("path") or ""))
        if not path or path in seen:
            return
        seen.add(path)
        merged.append(
            {
                "path": path,
                "kind": str(item.get("kind") or _kind_from_path(path)),
                "role": str(item.get("role") or "material"),
                "required": item.get("required") is not False,
            }
        )

    for item in primary:
        add(dict(item))
    for item in obligation_reads:
        add(dict(item))
    return merged


def _filter_output_materials(
    materials: list[dict[str, Any]],
    *,
    task_goal_spec: dict[str, Any],
    user_goal: str,
) -> list[dict[str, Any]]:
    task_goal_type = str(task_goal_spec.get("task_goal_type") or "").strip()
    output_paths = _output_paths_from_goal_frame(task_goal_spec)
    if task_goal_type in {"game_vertical_slice_delivery", "frontend_app_delivery"}:
        output_paths.extend(_paths_in_output_context(user_goal))
    if not output_paths:
        return materials
    return [
        item
        for item in materials
        if not any(_same_path(str(item.get("path") or ""), output_path) for output_path in output_paths)
    ]


def _output_paths_from_goal_frame(task_goal_spec: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for key in ("core_deliverables", "supporting_deliverables"):
        for item in list(task_goal_spec.get(key) or []):
            if not isinstance(item, dict):
                continue
            metadata = dict(item.get("metadata") or {})
            for value in list(metadata.get("paths") or []):
                if str(value).strip():
                    paths.append(str(value).strip())
    constraints = [
        str(item).removeprefix("path:").strip()
        for item in list(task_goal_spec.get("explicit_constraints") or [])
        if str(item).startswith("path:")
    ]
    paths.extend(constraints)
    return _dedupe([_normalize_path(path) for path in paths if path])


def _paths_in_output_context(text: str) -> list[str]:
    output_paths: list[str] = []
    for match in _PATH_RE.finditer(str(text or "")):
        path = _normalize_path(match.group("path"))
        if not path:
            continue
        context = str(text or "")[max(0, match.start() - 36) : match.end() + 36]
        if any(marker in context for marker in ("写入", "输出", "最终报告", "阶段产物", "产物", "生成到", "保存到")):
            output_paths.append(path)
    return _dedupe(output_paths)


def _same_path(left: str, right: str) -> bool:
    left_norm = _normalize_path(left).replace("\\", "/").strip().lower()
    right_norm = _normalize_path(right).replace("\\", "/").strip().lower()
    return bool(left_norm and right_norm and (left_norm == right_norm or left_norm.endswith("/" + right_norm) or right_norm.endswith("/" + left_norm)))


def _normalize_path(path: str) -> str:
    value = _trim_path_to_known_suffix(str(path or "").strip().strip("'\"`，,。；;").replace("\\", "/"))
    if not value:
        return ""
    suffix_re = r"(?:json|py|md|txt|log|csv|tsv|xlsx|pdf|yaml|yml|toml)"
    known_root_match = re.search(
        rf"(?i)(?:(?<=^)|(?<=[\s:：]))((?:\.{{0,2}}/)?(?:backend|frontend|docs|storage|tests|scripts|output|src|app|packages|knowledge)/[^，。；;\n\r]*?\.{suffix_re})",
        value,
    )
    if known_root_match:
        return known_root_match.group(1).strip().strip("'\"`，,。；;")
    absolute_match = re.search(
        rf"(?i)([A-Za-z]:/[^，,。；;\n\r]*?\.{suffix_re})",
        value,
    )
    if absolute_match:
        return absolute_match.group(1).strip().strip("'\"`，,。；;")
    if re.search(rf"(?i)\.{suffix_re}", value):
        cut = re.search(rf"(?i)^(.+?\.{suffix_re})", value)
        if cut:
            candidate = _trim_path_to_known_suffix(cut.group(1).strip().strip("'\"`，,。；;"))
            parts = [part for part in re.split(r"\s+", candidate) if part]
            path_parts = [part for part in parts if "/" in part and re.search(rf"(?i)\.{suffix_re}$", part)]
            if path_parts:
                return path_parts[-1].strip().strip("'\"`，,。；;")
            return candidate
    return value


def _trim_path_to_known_suffix(value: str) -> str:
    text = str(value or "").strip()
    suffix_re = r"(?:json|py|md|txt|log|csv|tsv|xlsx|pdf|yaml|yml|toml)"
    match = re.search(rf"(?i)^(.+?\.{suffix_re})(?=$|[\s，,。；;:：、])", text)
    if match:
        return match.group(1).strip().strip("'\"`，,。；;")
    fallback = re.search(rf"(?i)^(.+?\.{suffix_re})", text)
    if fallback:
        return fallback.group(1).strip().strip("'\"`，,。；;")
    return text


def _complete_partial_known_root_path(path: str, *, text: str, start: int) -> str:
    value = str(path or "")
    if not value.startswith("/") or value.startswith("//"):
        return value
    prefix = str(text or "")[: max(0, start)].rstrip()
    match = re.search(r"(?i)(backend|frontend|docs|storage|tests|scripts|output|src|app|packages|knowledge)\s*$", prefix)
    if match:
        return f"{match.group(1)}{value}"
    return value


def _kind_from_path(path: str) -> str:
    suffix = str(path or "").rsplit(".", 1)[-1].lower() if "." in str(path or "") else ""
    if suffix in {"json", "yaml", "yml", "toml"}:
        return "json" if suffix == "json" else "structured_text"
    if suffix in {"csv", "tsv", "xlsx"}:
        return "dataset"
    if suffix == "pdf":
        return "pdf"
    if suffix in {"py", "ts", "tsx", "js", "jsx"}:
        return "code"
    if suffix in {"md", "txt", "log"}:
        return "text"
    return "unknown"


def _path_looks_like_command_argument(*, text: str, start: int, path: str) -> bool:
    prefix = str(text or "")[max(0, start - 40) : start].lower()
    suffix = str(path or "").rsplit(".", 1)[-1].lower() if "." in str(path or "") else ""
    if suffix not in {"py", "js", "ts", "tsx", "jsx"}:
        return False
    return any(marker in prefix for marker in ("pytest ", "python ", "node ", "npm ", "pnpm ", "yarn "))


def _domain_for_goal_type(task_goal_type: str, query_understanding: dict[str, Any]) -> str:
    profile = get_task_goal_profile(task_goal_type)
    if profile is not None:
        return profile.task_domain
    decision = dict(dict(query_understanding or {}).get("model_turn_decision") or {})
    action_intent = str(decision.get("action_intent") or "").strip()
    work_mode = str(decision.get("work_mode") or "").strip()
    if action_intent == "search_external":
        return "external_web"
    if action_intent in {"edit_workspace", "run_command", "start_service"} or work_mode in {"implementation", "verification"}:
        return "development"
    if action_intent == "read_context":
        return "workspace"
    return "general"


def _professional_profile_id(task_goal_type: str) -> str:
    profile = get_task_goal_profile(task_goal_type)
    if profile is not None and profile.professional_profile_id:
        return profile.professional_profile_id
    return ""


def _deliverables_for_goal_type(task_goal_type: str) -> list[str]:
    profile = get_task_goal_profile(task_goal_type)
    if profile is not None and profile.default_core_deliverables:
        return list(profile.default_core_deliverables)
    return ["final_answer"]


def _reasoning_steps_for_goal_type(task_goal_type: str) -> list[str]:
    profile = get_task_goal_profile(task_goal_type)
    if profile is not None and profile.default_reasoning_steps:
        return list(profile.default_reasoning_steps)
    return ["understand_request", "answer_with_boundaries"]


def _required_actions_for_goal_type(task_goal_type: str, *, materials: tuple[dict[str, Any], ...]) -> list[str]:
    actions: list[str] = []
    if materials:
        actions.append("read_material")
    profile = get_task_goal_profile(task_goal_type)
    if profile is not None and profile.required_actions:
        actions.extend(profile.required_actions)
        return _dedupe(actions)
    return _dedupe(actions)


def _forbidden_actions_for_goal_type(task_goal_type: str, *, write_required: bool = False, write_forbidden: bool = False) -> list[str]:
    common = ["invent_evidence", "visible_tool_markup", "surface_only_summary"]
    profile = get_task_goal_profile(task_goal_type)
    if profile is not None and profile.forbidden_actions:
        actions = list(profile.forbidden_actions)
        if not write_required and task_goal_type in {"test_report_triage", "inspection"}:
            actions.append("modify_code_without_request")
        if write_forbidden:
            actions.append("modify_code")
        return _dedupe(actions)
    if write_forbidden:
        return [*common, "modify_code"]
    return common


def _material_policy_for_goal_type(
    task_goal_type: str,
    *,
    materials: tuple[dict[str, Any], ...],
    execution_obligation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    obligation = dict(execution_obligation or {})
    profile = get_task_goal_profile(task_goal_type)
    profile_policy = dict(getattr(profile, "material_policy", None) or {}) if profile is not None else {}
    return {
        "requires_material_read": bool(materials),
        "structured_extraction": bool(profile_policy.get("structured_extraction")),
        "evidence_packet_required": bool(profile_policy.get("evidence_packet_required")),
        "stage_prompt_profiles_required": bool(profile_policy.get("stage_prompt_profiles_required")),
        "material_count": len(materials),
        "execution_obligation_required_reads": len(list(obligation.get("required_reads") or [])),
        "execution_obligation_required_writes": len(list(obligation.get("required_writes") or [])),
        "execution_obligation_required_verifications": len(list(obligation.get("required_verifications") or [])),
    }


def _output_schema_for_goal_type(task_goal_type: str, *, deliverables: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "structured_answer",
        "required_deliverables": list(deliverables or _deliverables_for_goal_type(task_goal_type)),
    }


def _validation_schema_for_goal_type(task_goal_type: str, *, execution_obligation: dict[str, Any] | None = None) -> dict[str, Any]:
    obligation = dict(execution_obligation or {})
    profile = get_task_goal_profile(task_goal_type)
    profile_policy = dict(getattr(profile, "material_policy", None) or {}) if profile is not None else {}
    validator_id = str(getattr(profile, "validator_profile_id", "") or f"deliverable.{task_goal_type}")
    return {
        "validator": validator_id,
        "reject_protocol_leak": True,
        "require_evidence_alignment": bool(profile_policy.get("evidence_packet_required")),
        "require_write_observation": _obligation_has_writes(obligation) and task_goal_type != "task_graph_node_execution",
        "require_verification_observation": _obligation_has_verification(obligation),
        "completion_judgment_statuses": ["verified", "partially_verified", "unverified", "blocked", "contradicted"],
    }


def _deliverables_from_obligation(obligation: dict[str, Any]) -> list[str]:
    return _dedupe(
        [
            str(item).strip()
            for item in list(dict(obligation or {}).get("required_deliverables") or [])
            if str(item).strip()
        ]
    )


def _contract_deliverables(*, task_goal_type: str, obligation: dict[str, Any]) -> list[str]:
    base = _deliverables_for_goal_type(task_goal_type)
    obligation_deliverables = _deliverables_from_obligation(obligation)
    if task_goal_type == "material_synthesis":
        allowed = {"material_findings", "cross_material_conclusions", "limitations", "evidence_limits"}
        return _dedupe([item for item in [*base, *obligation_deliverables] if item in allowed])
    if task_goal_type == "code_fix_execution":
        allowed = {"change_summary", "changed_files", "verification_result_or_limitation", "evidence_limits"}
        return _dedupe([item for item in [*base, *obligation_deliverables] if item in allowed])
    if task_goal_type == "game_vertical_slice_delivery":
        allowed = {
            "runnable_artifact_refs",
            "gameplay_acceptance",
            "visual_asset_refs",
            "verification_evidence",
            "final_report",
            "limitations",
        }
        return _dedupe([item for item in [*base, *obligation_deliverables] if item in allowed])
    if task_goal_type == "frontend_app_delivery":
        allowed = {"runnable_artifact_refs", "workflow_acceptance", "verification_evidence", "limitations"}
        return _dedupe([item for item in [*base, *obligation_deliverables] if item in allowed])
    return _dedupe([*base, *obligation_deliverables])


def _required_actions_for_obligation(obligation: dict[str, Any]) -> list[str]:
    item = dict(obligation or {})
    if str(item.get("task_graph_node_policy") or "").strip() == "orchestration_owned_side_effects":
        return []
    actions: list[str] = []
    if list(item.get("required_reads") or []):
        actions.append("read_material")
    if list(item.get("required_writes") or []):
        actions.append("apply_real_change")
    if list(item.get("required_commands") or []) or list(item.get("required_verifications") or []):
        actions.extend(["run_verification", "validate_deliverables"])
    if list(item.get("required_deliverables") or []):
        actions.append("validate_deliverables")
    return _dedupe(actions)


def _obligation_has_writes(obligation: dict[str, Any]) -> bool:
    return bool(list(dict(obligation or {}).get("required_writes") or []))


def _obligation_has_verification(obligation: dict[str, Any]) -> bool:
    item = dict(obligation or {})
    return bool(list(item.get("required_commands") or []) or list(item.get("required_verifications") or []))


def _obligation_forbids_write(obligation: dict[str, Any]) -> bool:
    forbidden = {
        str(item).strip()
        for item in list(dict(obligation or {}).get("forbidden_actions") or [])
        if str(item).strip()
    }
    return bool(forbidden.intersection({"modify_code", "write_file", "edit_file"}))


def _obligation_summary(obligation: dict[str, Any]) -> dict[str, Any]:
    item = dict(obligation or {})
    return {
        "required_reads": len(list(item.get("required_reads") or [])),
        "required_writes": len(list(item.get("required_writes") or [])),
        "required_commands": len(list(item.get("required_commands") or [])),
        "required_verifications": len(list(item.get("required_verifications") or [])),
        "required_deliverables": list(item.get("required_deliverables") or []),
        "forbidden_actions": list(item.get("forbidden_actions") or []),
    }


def _is_task_graph_node_runtime_context(current_turn_context: dict[str, Any]) -> bool:
    context = dict(current_turn_context or {})
    if context.get("task_graph_node_runtime") is True or context.get("suppress_bundle_projection") is True:
        return True
    if str(context.get("runtime_lane") or "").strip() == "coordination_task":
        return True
    if str(context.get("continuation_stage_id") or "").strip() and str(
        context.get("selected_task_id")
        or context.get("task_id")
        or context.get("specific_task_id")
        or ""
    ).startswith("task."):
        return True
    return False


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
