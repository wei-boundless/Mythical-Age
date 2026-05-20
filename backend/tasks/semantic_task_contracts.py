from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any


_PATH_RE = re.compile(
    r"(?P<path>(?:[A-Za-z]:)?(?:[./\\]?[\w\u4e00-\u9fff @()：:（），,\-]+[\\/])+[\w\u4e00-\u9fff @()：:（），,.\-]+"
    r"|[\w\u4e00-\u9fff @()\-./\\]+?\.(?:json|py|md|txt|log|csv|tsv|xlsx|pdf|yaml|yml|toml))",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class SemanticTaskContract:
    contract_id: str
    task_goal_type: str
    user_goal: str
    domain: str
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
    authority: str = "task_system.semantic_task_contract"

    def __post_init__(self) -> None:
        if self.authority != "task_system.semantic_task_contract":
            raise ValueError("SemanticTaskContract authority must be task_system.semantic_task_contract")
        if not self.contract_id:
            raise ValueError("SemanticTaskContract requires contract_id")
        if not self.task_goal_type:
            raise ValueError("SemanticTaskContract requires task_goal_type")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["materials"] = [dict(item) for item in self.materials]
        payload["deliverables"] = list(self.deliverables)
        payload["required_reasoning_steps"] = list(self.required_reasoning_steps)
        payload["required_actions"] = list(self.required_actions)
        payload["forbidden_actions"] = list(self.forbidden_actions)
        return payload


def build_semantic_task_contract(
    *,
    session_id: str,
    task_id: str,
    user_goal: str,
    query_understanding: dict[str, Any] | None = None,
    current_turn_context: dict[str, Any] | None = None,
    explicit_inputs: dict[str, Any] | None = None,
) -> SemanticTaskContract:
    understanding = dict(query_understanding or {})
    current_turn = dict(current_turn_context or {})
    inputs = {
        **dict(explicit_inputs or {}),
        **dict(current_turn.get("explicit_inputs") or {}),
    }
    materials = tuple(_collect_materials(user_goal=user_goal, explicit_inputs=inputs, current_turn=current_turn))
    task_goal_type = _resolve_task_goal_type(
        user_goal=user_goal,
        materials=materials,
        query_understanding=understanding,
        current_turn_context=current_turn,
    )
    profile = _professional_profile_id(task_goal_type)
    return SemanticTaskContract(
        contract_id=f"semantic-task:{session_id}:{task_id}",
        task_goal_type=task_goal_type,
        user_goal=str(user_goal or "").strip(),
        domain=_domain_for_goal_type(task_goal_type, understanding),
        materials=materials,
        deliverables=tuple(_deliverables_for_goal_type(task_goal_type)),
        required_reasoning_steps=tuple(_reasoning_steps_for_goal_type(task_goal_type)),
        required_actions=tuple(_required_actions_for_goal_type(task_goal_type, materials=materials)),
        forbidden_actions=tuple(_forbidden_actions_for_goal_type(task_goal_type)),
        material_handling_policy=_material_policy_for_goal_type(task_goal_type, materials=materials),
        output_schema=_output_schema_for_goal_type(task_goal_type),
        validation_schema=_validation_schema_for_goal_type(task_goal_type),
        professional_profile_id=profile,
        diagnostics={
            "material_count": len(materials),
            "material_kinds": sorted({str(item.get("kind") or "") for item in materials if item.get("kind")}),
            "explicit_mode": str(current_turn.get("interaction_mode") or current_turn.get("runtime_interaction_mode") or ""),
            "intent_execution_strategy": str(
                dict(current_turn.get("intent_decision") or {}).get("execution_strategy")
                or dict(current_turn.get("runtime_assembly_hint") or {}).get("execution_strategy")
                or ""
            ),
        },
    )


def semantic_contract_from_payload(payload: dict[str, Any] | None) -> SemanticTaskContract | None:
    item = dict(payload or {})
    if not item:
        return None
    try:
        return SemanticTaskContract(
            contract_id=str(item.get("contract_id") or ""),
            task_goal_type=str(item.get("task_goal_type") or ""),
            user_goal=str(item.get("user_goal") or ""),
            domain=str(item.get("domain") or ""),
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


def _resolve_task_goal_type(
    *,
    user_goal: str,
    materials: tuple[dict[str, Any], ...],
    query_understanding: dict[str, Any],
    current_turn_context: dict[str, Any],
) -> str:
    explicit = str(
        current_turn_context.get("semantic_task_type")
        or current_turn_context.get("task_goal_type")
        or dict(current_turn_context.get("semantic_task_contract") or {}).get("task_goal_type")
        or ""
    ).strip()
    if explicit:
        return explicit
    text = str(user_goal or "").lower()
    route = str(query_understanding.get("route") or query_understanding.get("route_hint") or "").strip().lower()
    posture = str(query_understanding.get("execution_posture") or "").strip().lower()
    material_paths = " ".join(str(item.get("path") or "").lower() for item in materials)
    has_failure_report = any(token in text for token in ("失败", "fail", "failing", "测试报告", "长跑", "long_runner", "triage"))
    has_root_cause_language = any(token in text for token in ("根因", "root cause", "结构性", "回归", "regression"))
    has_test_material = any(token in material_paths for token in ("test", "summary", "report", "fixture", ".json"))
    if has_failure_report and (has_root_cause_language or has_test_material):
        return "test_report_triage"
    if any(token in text for token in ("runtime trace", "运行追踪", "checkpoint", "事件链", "trace")):
        return "runtime_trace_analysis"
    if any(token in text for token in ("回归测试", "测试设计", "补测试", "regression test")):
        return "regression_test_design"
    if any(token in text for token in ("草案", "方案", "计划书", "实施方案")) and any(
        token in text for token in ("写入", "生成文件", "产出", "交付", "导出")
    ):
        return "artifact_delivery"
    advisory_repair = any(token in text for token in ("修复建议", "验证步骤", "排查", "troubleshoot", "建议"))
    explicit_real_change = any(
        token in text
        for token in (
            "在 sandbox overlay 中",
            "写入",
            "生成文件",
            "产出",
            "实现",
            "改代码",
            "修改代码",
            "修复它",
            "apply",
            "patch",
        )
    )
    if any(token in text for token in ("修复", "修改", "实现", "改代码", "fix", "patch", "bug")) and (
        explicit_real_change or not advisory_repair
    ):
        return "code_fix_execution"
    if any(token in text for token in ("生成文件", "写成", "产物", "交付", "导出")):
        return "artifact_delivery"
    if len(materials) > 1 or any(token in text for token in ("综合", "总结", "分析这些", "材料")):
        return "material_synthesis"
    if route in {"search", "realtime_network"}:
        return "light_qa"
    if route in {"workspace_read", "workspace_path_search", "workspace_text_search", "tool"} or posture == "builtin_tool_lane":
        return "bounded_tool_task"
    if any(token in text for token in ("聊天", "陪我", "角色", "灵魂", "记得")):
        return "role_conversation"
    return "light_qa"


def _collect_materials(
    *,
    user_goal: str,
    explicit_inputs: dict[str, Any],
    current_turn: dict[str, Any],
) -> list[dict[str, Any]]:
    materials: list[dict[str, Any]] = []
    seen: set[str] = set()

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
        ("target_path", "target"),
    ):
        value = explicit_inputs.get(key) or current_turn.get(key)
        if isinstance(value, str):
            add(value, role=role)
    for key in ("material_paths", "input_paths", "paths", "files"):
        for value in list(explicit_inputs.get(key) or current_turn.get(key) or []):
            if isinstance(value, str):
                add(value)
            elif isinstance(value, dict):
                add(str(value.get("path") or ""), role=str(value.get("role") or "material"), required=value.get("required") is not False)
    for match in _PATH_RE.finditer(str(user_goal or "")):
        add(match.group("path"), role="failure_report" if match.group("path").lower().endswith(".json") else "material")
    return materials


def _normalize_path(path: str) -> str:
    value = str(path or "").strip().strip("'\"`，,。；;").replace("\\", "/")
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
            candidate = cut.group(1).strip().strip("'\"`，,。；;")
            parts = [part for part in re.split(r"\s+", candidate) if part]
            path_parts = [part for part in parts if "/" in part and re.search(rf"(?i)\.{suffix_re}$", part)]
            if path_parts:
                return path_parts[-1].strip().strip("'\"`，,。；;")
            return candidate
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


def _domain_for_goal_type(task_goal_type: str, query_understanding: dict[str, Any]) -> str:
    if task_goal_type in {"test_report_triage", "runtime_trace_analysis"}:
        return "agent_runtime_quality"
    if task_goal_type in {"code_fix_execution", "regression_test_design"}:
        return "software_engineering"
    source_kind = str(query_understanding.get("source_kind") or "").strip()
    return source_kind or "general"


def _professional_profile_id(task_goal_type: str) -> str:
    return {
        "test_report_triage": "professional.test_report_triage",
        "runtime_trace_analysis": "professional.runtime_trace_analysis",
        "code_fix_execution": "professional.code_fix_execution",
        "regression_test_design": "professional.regression_test_design",
        "material_synthesis": "professional.material_synthesis",
    }.get(task_goal_type, "")


def _deliverables_for_goal_type(task_goal_type: str) -> list[str]:
    return {
        "test_report_triage": ["failure_classification", "structural_root_causes", "regression_test_plan", "evidence_limits"],
        "runtime_trace_analysis": ["event_chain", "turning_points", "structural_root_causes", "recovery_candidates"],
        "code_fix_execution": ["change_summary", "changed_files", "verification_result_or_limitation"],
        "regression_test_design": ["reproduction_inputs", "assertions", "coverage_risks", "target_files"],
        "artifact_delivery": ["artifact_refs", "completion_status", "limitations"],
        "material_synthesis": ["material_findings", "cross_material_conclusions", "limitations"],
        "bounded_tool_task": ["tool_grounded_answer", "limitations"],
        "light_qa": ["direct_answer", "source_or_memory_boundary"],
        "role_conversation": ["conversational_response"],
    }.get(task_goal_type, ["final_answer"])


def _reasoning_steps_for_goal_type(task_goal_type: str) -> list[str]:
    return {
        "test_report_triage": [
            "extract_failures",
            "classify_failures_by_system_layer",
            "infer_structural_root_causes",
            "map_regression_tests",
            "synthesize_final_answer",
        ],
        "runtime_trace_analysis": ["extract_events", "identify_turning_points", "map_state_owners", "synthesize_recovery_plan"],
        "code_fix_execution": ["inspect_relevant_code", "plan_structural_change", "edit_scoped_files", "run_or_explain_verification"],
        "regression_test_design": ["identify_regression_surface", "design_repro_inputs", "define_assertions", "map_test_files"],
        "material_synthesis": ["read_materials", "extract_facts", "compare_findings", "synthesize_answer"],
    }.get(task_goal_type, ["understand_request", "answer_with_boundaries"])


def _required_actions_for_goal_type(task_goal_type: str, *, materials: tuple[dict[str, Any], ...]) -> list[str]:
    actions: list[str] = []
    if materials:
        actions.append("read_material")
    if task_goal_type in {"test_report_triage", "runtime_trace_analysis", "material_synthesis"}:
        actions.append("build_evidence_packet")
    if task_goal_type in {"test_report_triage", "runtime_trace_analysis", "code_fix_execution", "regression_test_design"}:
        actions.append("validate_deliverables")
    if task_goal_type == "code_fix_execution":
        actions.extend(["inspect_code", "apply_real_change"])
    return _dedupe(actions)


def _forbidden_actions_for_goal_type(task_goal_type: str) -> list[str]:
    common = ["invent_evidence", "visible_tool_markup", "surface_only_summary"]
    if task_goal_type == "test_report_triage":
        return [*common, "invent_test_result", "modify_code_without_request"]
    if task_goal_type == "code_fix_execution":
        return [*common, "claim_unrun_tests_as_passed"]
    return common


def _material_policy_for_goal_type(task_goal_type: str, *, materials: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    return {
        "requires_material_read": bool(materials),
        "structured_extraction": task_goal_type in {"test_report_triage", "runtime_trace_analysis"},
        "evidence_packet_required": task_goal_type in {"test_report_triage", "runtime_trace_analysis", "material_synthesis"},
        "material_count": len(materials),
    }


def _output_schema_for_goal_type(task_goal_type: str) -> dict[str, Any]:
    return {
        "type": "structured_answer",
        "required_deliverables": _deliverables_for_goal_type(task_goal_type),
    }


def _validation_schema_for_goal_type(task_goal_type: str) -> dict[str, Any]:
    return {
        "validator": f"deliverable.{task_goal_type}",
        "reject_protocol_leak": True,
        "require_evidence_alignment": task_goal_type in {"test_report_triage", "runtime_trace_analysis", "material_synthesis"},
    }


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
