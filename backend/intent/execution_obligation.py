from __future__ import annotations

import re
from typing import Any

from task_system.goal_profiles import get_task_goal_profile

from .obligation_models import ExecutionObligation


_PATH_RE = re.compile(
    r"(?P<path>(?:[A-Za-z]:)?(?:[./\\]?[\w\u4e00-\u9fff @()：:（），,\-]+[\\/])+[\w\u4e00-\u9fff @()：:（），,.\-]+"
    r"|[\w\u4e00-\u9fff @()\-./\\]+?\.(?:json|py|md|txt|log|csv|tsv|xlsx|pdf|yaml|yml|toml|ts|tsx|js|jsx))",
    flags=re.IGNORECASE,
)

_GLOBAL_FORBID_WRITE_MARKERS = (
    "不要写任何文件",
    "不要写入任何文件",
    "不要生成任何文件",
    "不要创建任何文件",
    "不要新建任何文件",
    "不要保存任何文件",
    "不要产出任何文件",
    "不要写文件",
    "不要写入文件",
    "不要生成文件",
    "不要创建文件",
    "不要新建文件",
    "不要保存文件",
    "只分析，不要写",
    "只分析不要写",
    "只读分析，不要写",
    "do not write",
    "don't write",
    "do not create files",
    "don't create files",
    "no file writes",
    "analysis only",
)
_BROAD_NO_MODIFY_MARKERS = (
    "先分析不要改",
    "先分析，不要改",
    "先不要改",
    "不要改代码",
    "不要修改代码",
    "不要动代码",
    "不用改代码",
    "别改代码",
    "不要改文件",
    "不要修改文件",
    "不用改文件",
    "别改文件",
    "do not modify",
    "don't modify",
    "read only",
    "readonly",
)
_SCOPED_SOURCE_WRITE_FORBID_MARKERS = (
    "不要修改源项目",
    "不要改源项目",
    "不要动源项目",
    "不要修改源工程",
    "不要改源工程",
    "不要动源工程",
    "不要修改源目录",
    "不要改源目录",
    "不要动源目录",
    "不要修改原项目",
    "不要改原项目",
    "不要修改原目录",
    "不要改原目录",
    "不要修改原始目录",
    "不要改原始目录",
    "源项目只读",
    "源工程只读",
    "源目录只读",
    "只读源项目",
    "只读源工程",
    "只读源目录",
    "source project read only",
    "source directory read only",
    "do not modify source project",
    "don't modify source project",
)
def build_execution_obligation(
    *,
    session_id: str,
    task_id: str,
    user_goal: str,
    explicit_inputs: dict[str, Any] | None = None,
    current_turn_context: dict[str, Any] | None = None,
) -> ExecutionObligation:
    text = str(user_goal or "").strip()
    lowered = text.lower()
    current_turn = dict(current_turn_context or {})
    model_decision = dict(current_turn.get("model_turn_decision") or {})
    inputs = {
        **dict(explicit_inputs or {}),
        **dict(current_turn.get("explicit_inputs") or {}),
    }
    resource_contract = _resource_contract_from_current_turn(current_turn)
    contract_reads = _collect_required_reads_from_resource_contract(resource_contract)
    reads = contract_reads
    if not reads:
        reads = _collect_required_reads(text=text, explicit_inputs=inputs, current_turn=current_turn)
    goal_frame = dict(current_turn.get("task_goal_spec") or current_turn.get("goal_frame") or {})
    profile_obligation = _profile_obligation_requirements(
        task_goal_spec=goal_frame,
        current_turn=current_turn,
    )
    contract_writes = _collect_required_writes_from_resource_contract(resource_contract)
    model_writes = _model_decision_write_requirements(
        model_decision=model_decision,
        explicit_inputs=inputs,
        resource_contract=resource_contract,
    )
    scoped_write_constraints = _scoped_write_constraints(
        text=text,
        current_turn=current_turn,
        resource_contract=resource_contract,
    )
    natural_language_write_forbid_signal = _natural_language_write_forbid_signal(
        lowered=lowered,
        required_contract_writes=contract_writes,
        required_profile_writes=list(profile_obligation["required_writes"]),
        explicit_inputs=inputs,
    )
    forbid_write = _structured_write_forbidden(current_turn)
    write_required = (
        bool(contract_writes)
        or bool(model_writes)
        or bool(profile_obligation["required_writes"])
    ) and not forbid_write
    model_verification = _model_decision_verification_requirements(model_decision, goal_frame)
    verify_required = bool(profile_obligation["required_verifications"]) or bool(model_verification["verifications"])
    required_writes = tuple(
        _dedupe_dicts(
            [
                *(contract_writes if not forbid_write else []),
                *([] if forbid_write else list(model_writes)),
                *([] if forbid_write else list(profile_obligation["required_writes"])),
            ],
            key_fields=("kind", "path", "source"),
        )
    )
    required_commands = tuple(
        _dedupe_dicts(
            [
                *list(profile_obligation["required_commands"]),
                *list(model_verification["commands"]),
            ],
            key_fields=("kind", "command_hint", "source"),
        )
    )
    required_verifications = tuple(
        _dedupe_dicts(
            [
                *list(profile_obligation["required_verifications"]),
                *list(model_verification["verifications"]),
            ],
            key_fields=("kind", "verification_kind", "criterion_id"),
        )
    )
    required_deliverables = tuple(
        _dedupe(
            [
                *_model_decision_deliverables(model_decision),
                *list(profile_obligation["required_deliverables"]),
                *(["verification_result_or_limitation"] if verify_required else []),
            ]
        )
    )
    forbidden_actions = ("modify_code", "write_file", "edit_file") if forbid_write else ()
    if scoped_write_constraints:
        for item in required_writes:
            item.setdefault("write_scope_policy", "sandbox_or_target_only")
            item.setdefault("forbidden_source_writes", scoped_write_constraints)
    signals = {
        "read_paths": [item["path"] for item in reads if item.get("path")],
        "write_required": write_required,
        "verify_required": verify_required,
        "forbid_write": forbid_write,
        "natural_language_write_forbid_signal": natural_language_write_forbid_signal,
        "forbid_write_authority": "model_turn_decision_or_boundary_policy",
        "hard_write_authority": "operation_gate_and_sandbox_policy",
        "structured_write_forbidden": forbid_write,
        "scoped_write_constraints": scoped_write_constraints,
        "profile_obligation": profile_obligation["evidence"],
        "resource_contract_used": bool(resource_contract),
        "model_decision_used": bool(model_decision),
        "natural_language_action_inference_removed": True,
        "read_paths_compiled_from": (
            "model_resource_contract"
            if contract_reads
            else "request_facts_or_explicit_inputs"
            if reads
            else ""
        ),
        "execution_actions_compiled_from": [
            *(("model_resource_contract",) if contract_writes else ()),
            *(("model_turn_decision",) if model_writes else ()),
            *(
                ("task_goal_profile",)
                if (
                    profile_obligation["required_writes"]
                    or profile_obligation["required_commands"]
                    or profile_obligation["required_verifications"]
                )
                else ()
            ),
            *(("model_completion_criteria",) if model_verification["verifications"] else ()),
        ],
    }
    confidence = 0.35
    if reads:
        confidence += 0.15
    if write_required:
        confidence += 0.2
    if verify_required:
        confidence += 0.15
    if forbid_write:
        confidence += 0.15
    return ExecutionObligation(
        obligation_id=f"execution-obligation:{session_id}:{task_id}",
        user_goal=text,
        required_reads=tuple(reads),
        required_writes=required_writes,
        required_commands=required_commands,
        required_deliverables=required_deliverables,
        required_verifications=required_verifications,
        forbidden_actions=forbidden_actions,
        confidence=min(confidence, 0.98),
        extraction_evidence=signals,
    )


def _resource_contract_from_current_turn(current_turn: dict[str, Any]) -> dict[str, Any]:
    decision = dict(current_turn.get("model_turn_decision") or {})
    resource_contract = decision.get("resource_contract")
    if isinstance(resource_contract, dict) and resource_contract:
        return dict(resource_contract)
    direct = current_turn.get("resource_contract")
    return dict(direct) if isinstance(direct, dict) and direct else {}


def _collect_required_reads_from_resource_contract(resource_contract: dict[str, Any]) -> list[dict[str, Any]]:
    contract = dict(resource_contract or {})
    source_projects = _project_paths(contract.get("source_projects"))
    read_files = _relative_paths(contract.get("required_read_files"))
    read_dirs = _relative_paths(contract.get("required_read_dirs"))
    reads: list[dict[str, Any]] = []
    if not source_projects:
        for path in read_files:
            reads.append(
                {
                    "path": path,
                    "kind": _kind_from_path(path),
                    "role": "source_file" if _is_material_mount_path(path) else "material",
                    "required": True,
                    "source": "model_resource_contract",
                }
            )
        for path in read_dirs:
            reads.append(
                {
                    "path": path,
                    "kind": "asset_dir" if _is_asset_dir(path) else "directory",
                    "role": "source_asset_dir" if _is_asset_dir(path) else "source_dir",
                    "required": True,
                    "source": "model_resource_contract",
                }
            )
        return _dedupe_dicts(reads, key_fields=("path", "role", "source"))
    for source_root in source_projects:
        for path in read_files:
            reads.append(
                {
                    "path": _source_contract_path(source_root, path),
                    "kind": _kind_from_path(path),
                    "role": "source_file",
                    "required": True,
                    "source": "model_resource_contract",
                }
            )
        for path in read_dirs:
            reads.append(
                {
                    "path": _source_contract_path(source_root, path),
                    "kind": "asset_dir" if _is_asset_dir(path) else "directory",
                    "role": "source_asset_dir" if _is_asset_dir(path) else "source_dir",
                    "required": True,
                    "source": "model_resource_contract",
                }
            )
    return _dedupe_dicts(reads, key_fields=("path", "role", "source"))


def _collect_required_writes_from_resource_contract(resource_contract: dict[str, Any]) -> list[dict[str, Any]]:
    contract = dict(resource_contract or {})
    target_projects = _project_paths(contract.get("target_projects"))
    write_files = _relative_paths(contract.get("required_write_files"))
    write_dirs = _relative_paths(contract.get("required_write_dirs"))
    writes: list[dict[str, Any]] = []
    if not target_projects:
        for path in write_files:
            writes.append(
                {
                    "kind": "file_write",
                    "path": path,
                    "required": True,
                    "source": "model_resource_contract",
                }
            )
        for path in write_dirs:
            writes.append(
                {
                    "kind": "asset_dir_write" if _is_asset_dir(path) else "directory_write",
                    "path": path,
                    "required": True,
                    "source": "model_resource_contract",
                }
            )
        return _dedupe_dicts(writes, key_fields=("kind", "path", "source"))
    for target_root in target_projects:
        for path in write_files:
            writes.append(
                {
                    "kind": "file_write",
                    "path": _join_path(target_root, path),
                    "required": True,
                    "source": "model_resource_contract",
                }
            )
        for path in write_dirs:
            writes.append(
                {
                    "kind": "asset_dir_write" if _is_asset_dir(path) else "directory_write",
                    "path": _join_path(target_root, path),
                    "required": True,
                    "source": "model_resource_contract",
                }
            )
    return _dedupe_dicts(writes, key_fields=("kind", "path", "source"))


def _project_paths(value: Any) -> list[str]:
    paths: list[str] = []
    for item in list(value or []):
        if isinstance(item, dict):
            path = str(item.get("path") or "").strip()
        else:
            path = str(item or "").strip()
        path = path.replace("\\", "/").strip().strip("`'\"“”‘’ ，,。；;")
        if path:
            paths.append(path.rstrip("/"))
    return _dedupe(paths)


def _relative_paths(value: Any) -> list[str]:
    return [
        item.strip("/")
        for item in _dedupe([str(raw or "").replace("\\", "/").strip() for raw in list(value or [])])
        if item and not item.startswith(("/", "../")) and ":/" not in item
    ]


def _join_path(root: str, relative: str) -> str:
    left = str(root or "").replace("\\", "/").strip().rstrip("/")
    right = str(relative or "").replace("\\", "/").strip().strip("/")
    if left and right and (right == left or right.startswith(left + "/")):
        return right
    return f"{left}/{right}" if left and right else left or right


def _source_contract_path(source_root: str, path: str) -> str:
    normalized_path = str(path or "").replace("\\", "/").strip().strip("/")
    if _is_material_mount_path(normalized_path):
        return normalized_path
    normalized_root = str(source_root or "").replace("\\", "/").strip().rstrip("/")
    if normalized_root and normalized_path.startswith(normalized_root.strip("/") + "/"):
        return normalized_path
    return _join_path(normalized_root, normalized_path)


def _is_material_mount_path(path: str) -> bool:
    return str(path or "").replace("\\", "/").strip("/").startswith(".materials/source_projects/")


def _is_asset_dir(path: str) -> bool:
    return str(path or "").replace("\\", "/").strip("/").lower().endswith("assets")


def _natural_language_write_forbid_signal(
    *,
    lowered: str,
    required_contract_writes: list[dict[str, Any]],
    required_profile_writes: list[dict[str, Any]],
    explicit_inputs: dict[str, Any],
) -> bool:
    text = str(lowered or "").lower()
    if _has_any(text, _GLOBAL_FORBID_WRITE_MARKERS):
        return True
    if required_contract_writes or required_profile_writes or _explicit_output_path_present(explicit_inputs):
        return False
    if _has_any(text, _SCOPED_SOURCE_WRITE_FORBID_MARKERS):
        return False
    if _has_any(text, _BROAD_NO_MODIFY_MARKERS):
        return True
    if _analysis_only_without_output(text):
        return True
    return False


def _structured_write_forbidden(current_turn: dict[str, Any]) -> bool:
    forbidden = {
        str(item).strip()
        for item in [
            *list(dict(current_turn.get("model_turn_decision") or {}).get("forbidden_actions") or []),
            *list(dict(current_turn.get("task_goal_spec") or current_turn.get("goal_frame") or {}).get("forbidden_actions") or []),
            *list(current_turn.get("forbidden_actions") or []),
        ]
        if str(item).strip()
    }
    return bool(forbidden.intersection({"modify_code", "write_file", "edit_file", "edit_workspace"}))


def _scoped_write_constraints(
    *,
    text: str,
    current_turn: dict[str, Any],
    resource_contract: dict[str, Any],
) -> list[dict[str, Any]]:
    normalized = str(text or "").lower()
    raw_constraints = [
        str(item or "").strip()
        for item in [
            *list(dict(current_turn.get("model_turn_decision") or {}).get("constraints") or []),
            *list(dict(current_turn.get("model_turn_decision") or {}).get("forbidden_actions") or []),
            *list(dict(current_turn.get("task_goal_spec") or current_turn.get("goal_frame") or {}).get("explicit_constraints") or []),
            *list(dict(current_turn.get("task_goal_spec") or current_turn.get("goal_frame") or {}).get("forbidden_actions") or []),
        ]
        if str(item or "").strip()
    ]
    joined_constraints = "\n".join(raw_constraints).lower()
    if not (_has_any(normalized, _SCOPED_SOURCE_WRITE_FORBID_MARKERS) or _has_any(joined_constraints, _SCOPED_SOURCE_WRITE_FORBID_MARKERS)):
        return []
    source_paths = _project_paths(dict(resource_contract or {}).get("source_projects"))
    if not source_paths:
        source_paths = [".materials/source_projects"]
    return [
        {
            "target": "source_project",
            "access": "read_only",
            "paths": source_paths,
            "source": "user_or_model_constraint",
        }
    ]


def _explicit_output_path_present(explicit_inputs: dict[str, Any]) -> bool:
    for key in ("output_path", "artifact_path", "target_output_path"):
        if str(dict(explicit_inputs or {}).get(key) or "").strip():
            return True
    return False


def _analysis_only_without_output(text: str) -> bool:
    normalized = str(text or "").lower()
    if not any(marker in normalized for marker in ("只分析", "仅分析", "analysis only", "read only", "readonly")):
        return False
    return not any(marker in normalized for marker in ("写", "写入", "保存", "生成", "产出", "output/", "输出到", "报告"))


def _profile_obligation_requirements(
    *,
    task_goal_spec: dict[str, Any],
    current_turn: dict[str, Any],
) -> dict[str, Any]:
    explicit_task_goal_type = str(
        current_turn.get("semantic_task_type")
        or current_turn.get("task_goal_type")
        or dict(current_turn.get("task_requirement_contract") or {}).get("task_goal_type")
        or ""
    ).strip()
    task_goal_type = str(explicit_task_goal_type or task_goal_spec.get("task_goal_type") or "").strip()
    profile = get_task_goal_profile(task_goal_type)
    if profile is None:
        return {
            "required_writes": (),
            "required_commands": (),
            "required_verifications": (),
            "required_deliverables": (),
            "evidence": {"matched": False, "task_goal_type": task_goal_type},
        }
    actions = {str(item).strip() for item in tuple(profile.required_actions or ()) if str(item).strip()}
    writes: list[dict[str, Any]] = []
    commands: list[dict[str, Any]] = []
    verifications: list[dict[str, Any]] = []
    if "apply_real_change" in actions:
        writes.append({"kind": "workspace_change", "required": True, "source": "task_goal_profile", "task_goal_type": task_goal_type})
    if "integrate_asset" in actions:
        writes.append({"kind": "asset_integration", "required": True, "source": "task_goal_profile", "task_goal_type": task_goal_type})
    if "run_browser_verification" in actions:
        commands.append({"kind": "browser_or_runtime_check", "command_hint": "start_or_open_app", "required": True, "source": "task_goal_profile"})
        verifications.append({"kind": "browser_verification", "required": True, "source": "task_goal_profile"})
    if "run_verification" in actions:
        commands.append({"kind": "verification_command", "required": True, "source": "task_goal_profile"})
        default_verifications = [
            str(item).strip()
            for item in tuple(getattr(profile, "default_verifications", ()) or ())
            if str(item).strip()
        ]
        verifications.append(
            {
                "kind": "evidence",
                "verification_kind": "evidence",
                "criterion_id": default_verifications[0] if default_verifications else "",
                "title": default_verifications[0] if default_verifications else "",
                "required": True,
                "source": "task_goal_profile",
            }
        )
    required_verifications = (
        []
        if explicit_task_goal_type
        else [
            dict(item)
            for item in list(task_goal_spec.get("required_verifications") or [])
            if isinstance(item, dict)
        ]
    )
    for item in required_verifications:
        verifications.append(
            {
                "kind": str(item.get("verification_kind") or item.get("kind") or "evidence"),
                "criterion_id": str(item.get("criterion_id") or ""),
                "title": str(item.get("title") or ""),
                "required": item.get("required") is not False,
                "source": "task_goal_spec",
            }
        )
    return {
        "required_writes": tuple(writes),
        "required_commands": tuple(commands),
        "required_verifications": tuple(verifications),
        "required_deliverables": tuple(profile.default_core_deliverables),
        "evidence": {
            "matched": True,
            "task_goal_type": task_goal_type,
            "profile_id": profile.task_goal_type,
            "required_actions": sorted(actions),
            "explicit_task_goal_type": explicit_task_goal_type,
            "task_goal_spec_type": str(task_goal_spec.get("task_goal_type") or ""),
        },
    }


def _model_decision_verification_requirements(
    model_decision: dict[str, Any],
    task_goal_spec: dict[str, Any],
) -> dict[str, tuple[dict[str, Any], ...]]:
    decision = dict(model_decision or {})
    criteria = [
        str(item or "").strip()
        for item in [
            *list(decision.get("completion_criteria") or []),
            *[
                str(dict(item).get("title") or dict(item).get("criterion_id") or "")
                for item in list(dict(task_goal_spec or {}).get("required_verifications") or [])
                if isinstance(item, dict)
            ],
        ]
        if str(item or "").strip()
    ]
    action_intent = str(decision.get("action_intent") or "").strip()
    work_mode = str(decision.get("work_mode") or "").strip()
    requires_verification = bool(criteria) or action_intent in {"run_command", "use_browser", "start_service"} or work_mode == "verification"
    if not requires_verification:
        return {"commands": (), "verifications": ()}
    command_kind = "browser_or_runtime_check" if action_intent in {"use_browser", "start_service"} else "verification_command"
    verification_kind = "browser_verification" if action_intent in {"use_browser", "start_service"} else "evidence"
    command = {
        "kind": command_kind,
        "required": True,
        "source": "model_turn_decision",
    }
    verification = {
        "kind": verification_kind,
        "verification_kind": verification_kind,
        "required": True,
        "source": "model_turn_decision",
    }
    if criteria:
        verification["criteria"] = criteria
    return {"commands": (command,), "verifications": (verification,)}


def _model_decision_write_requirements(
    *,
    model_decision: dict[str, Any],
    explicit_inputs: dict[str, Any],
    resource_contract: dict[str, Any],
) -> tuple[dict[str, Any], ...]:
    decision = dict(model_decision or {})
    action_intent = str(decision.get("action_intent") or "").strip()
    work_mode = str(decision.get("work_mode") or "").strip()
    if action_intent not in {"edit_workspace"} and work_mode != "implementation":
        return ()
    if _collect_required_writes_from_resource_contract(resource_contract):
        return ()
    explicit_output = str(
        explicit_inputs.get("output_path")
        or explicit_inputs.get("artifact_path")
        or explicit_inputs.get("target_output_path")
        or ""
    ).strip()
    if explicit_output:
        return (
            {
                "kind": "file_write",
                "path": explicit_output,
                "required": True,
                "source": "model_turn_decision",
            },
        )
    return (
        {
            "kind": "workspace_change",
            "required": True,
            "source": "model_turn_decision",
        },
    )


def _model_decision_deliverables(model_decision: dict[str, Any]) -> list[str]:
    return _dedupe(
        [
            _slug_label(str(item or ""))
            for item in list(dict(model_decision or {}).get("deliverables") or [])
            if str(item or "").strip()
        ]
    )


def _slug_label(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    slug = re.sub(r"[^A-Za-z0-9_\-\u4e00-\u9fff]+", "_", text).strip("_").lower()
    return slug or text[:40]


def _collect_required_reads(
    *,
    text: str,
    explicit_inputs: dict[str, Any],
    current_turn: dict[str, Any],
) -> list[dict[str, Any]]:
    reads: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(path: str, *, role: str = "material", required: bool = True) -> None:
        value = _normalize_path(path)
        if not value or value in seen:
            return
        seen.add(value)
        reads.append({"path": value, "kind": _kind_from_path(value), "role": role, "required": required})

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
    for match in _PATH_RE.finditer(text):
        raw_path = str(match.group("path") or "")
        path = _complete_partial_known_root_path(
            _normalize_path(raw_path),
            text=text,
            start=match.start(),
        )
        normalized_fragment = _normalize_path(raw_path)
        normalized_index = raw_path.replace("\\", "/").lower().find(normalized_fragment.lower()) if normalized_fragment else -1
        path_start = match.start() + max(0, normalized_index)
        path_end = path_start + len(normalized_fragment or raw_path)
        if _path_looks_like_command_argument(text=text, start=match.start(), path=path):
            continue
        if _path_looks_like_required_output(text=text, start=path_start, end=path_end):
            continue
        if not _path_looks_like_required_input(text=text, start=path_start, end=path_end, path=path):
            continue
        role = "failure_report" if path.lower().endswith(".json") and _has_any(text.lower(), ("失败", "fail", "测试报告")) else "material"
        add(path, role=role)
    for path in _additional_readable_paths_in_material_sentences(text):
        role = "failure_report" if path.lower().endswith(".json") and _has_any(text.lower(), ("失败", "fail", "测试报告")) else "material"
        add(path, role=role)
    return reads


def _normalize_path(path: str) -> str:
    value = _trim_path_to_known_suffix(str(path or "").strip().strip("'\"`，,。；;").replace("\\", "/"))
    if not value:
        return ""
    suffix_re = r"(?:json|py|md|txt|log|csv|tsv|xlsx|pdf|yaml|yml|toml|ts|tsx|js|jsx)"
    known_root_match = re.search(
        rf"(?i)(?:(?<=^)|(?<=[\s:：]))((?:\.{{0,2}}/)?(?:backend|frontend|docs|storage|tests|scripts|output|src|app|packages|knowledge)/[^，。；;\n\r]*?\.{suffix_re})",
        value,
    )
    if known_root_match:
        return known_root_match.group(1).strip().strip("'\"`，,。；;")
    absolute_match = re.search(rf"(?i)([A-Za-z]:/[^，,。；;\n\r]*?\.{suffix_re})", value)
    if absolute_match:
        return absolute_match.group(1).strip().strip("'\"`，,。；;")
    return value


def _trim_path_to_known_suffix(value: str) -> str:
    text = str(value or "").strip()
    suffix_re = r"(?:json|py|md|txt|log|csv|tsv|xlsx|pdf|yaml|yml|toml|ts|tsx|js|jsx)"
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


def _path_looks_like_command_argument(*, text: str, start: int, path: str) -> bool:
    prefix = str(text or "")[max(0, start - 40) : start].lower()
    suffix = str(path or "").rsplit(".", 1)[-1].lower() if "." in str(path or "") else ""
    if suffix not in {"py", "js", "ts", "tsx", "jsx"}:
        return False
    return any(marker in prefix for marker in ("pytest ", "python ", "node ", "npm ", "pnpm ", "yarn "))


def _path_looks_like_required_input(*, text: str, start: int, path: str, end: int | None = None) -> bool:
    normalized_path = str(path or "").replace("\\", "/").strip()
    if not normalized_path:
        return False
    resolved_end = int(end if end is not None else start + len(str(path or "")))
    prefix = str(text or "").replace("\\", "/")[max(0, start - 24) : start]
    if _context_indicates_read_material_path(prefix) and not _context_indicates_output_path(prefix):
        return True
    context = _local_path_context(str(text or "").replace("\\", "/"), start=start, end=resolved_end, radius=36)
    if _context_indicates_output_path(context):
        return False
    if _context_indicates_read_material_path(context):
        return True
    if normalized_path.startswith(("backend/", "docs/", "tests/", "knowledge/", "storage/")):
        return True
    return False


def _path_looks_like_required_output(*, text: str, start: int, end: int) -> bool:
    normalized = str(text or "").replace("\\", "/")
    context = _local_path_context(normalized, start=start, end=end, radius=48)
    if not _context_indicates_output_path(context):
        return False
    read_index = _last_read_marker_index(context)
    output_index = _last_output_marker_index(context)
    return output_index >= 0 and output_index >= read_index


def _local_path_context(text: str, *, start: int, end: int, radius: int) -> str:
    value = str(text or "")
    left = value.rfind("\n", 0, start)
    right = value.find("\n", end)
    line_start = 0 if left < 0 else left + 1
    line_end = len(value) if right < 0 else right
    return value[max(line_start, start - radius) : min(line_end, end + radius)]


def _context_indicates_output_path(context: str) -> bool:
    text = str(context or "")
    if _context_indicates_read_material_path(text) and not any(marker in text for marker in ("目标输出", "输出目录", "输出到", "写入", "保存", "生成", "产出")):
        return False
    return any(
        marker in text
        for marker in (
            "目标输出",
            "输出目录",
            "输出到",
            "写入",
            "保存",
            "生成",
            "产出",
            "落到",
            "创建",
            "新建",
            "目录必须是",
            "sandbox overlay 中完成",
            "sandbox overlay",
        )
    )


def _context_indicates_read_material_path(context: str) -> bool:
    return any(
        marker in str(context or "")
        for marker in (
            "只读",
            "源项目",
            "源工程",
            "源路径",
            "源目录",
            "读回",
            "读取",
            "打开",
            "查看",
            "分析",
            "追踪",
            "结合",
            "基于",
            "根据",
            "参考",
            "从",
            "载入",
            "检查",
        )
    )


def _additional_readable_paths_in_material_sentences(text: str) -> list[str]:
    normalized = str(text or "").replace("\\", "/")
    suffixes = "json|py|md|txt|log|csv|tsv|xlsx|pdf|yaml|yml|toml|ts|tsx|js|jsx"
    path_pattern = re.compile(
        rf"(?P<path>(?:[\w.\-\u4e00-\u9fff]+/)+[\w.\-\u4e00-\u9fff]+\.({suffixes}))",
        re.IGNORECASE,
    )
    result: list[str] = []
    for sentence in re.split(r"[\n。；;]", normalized):
        if not _context_indicates_read_material_path(sentence):
            continue
        first_output_marker = _first_output_marker_index(sentence)
        first_output_path = _first_output_path_index(sentence)
        for match in path_pattern.finditer(sentence):
            if first_output_marker >= 0 and match.start() > first_output_marker:
                continue
            if first_output_path >= 0 and match.start() >= first_output_path:
                continue
            path = _normalize_path(str(match.group("path") or ""))
            if path:
                result.append(path)
    return _dedupe(result)


def _first_output_marker_index(text: str) -> int:
    indexes = [
        str(text or "").find(marker)
        for marker in ("目标输出", "输出目录", "输出到", "写入", "保存", "生成", "产出", "落到", "创建", "新建")
        if str(text or "").find(marker) >= 0
    ]
    return min(indexes) if indexes else -1


def _last_output_marker_index(text: str) -> int:
    indexes = [
        str(text or "").rfind(marker)
        for marker in ("目标输出", "输出目录", "输出到", "写入", "保存", "生成", "产出", "落到", "创建", "新建")
        if str(text or "").rfind(marker) >= 0
    ]
    return max(indexes) if indexes else -1


def _last_read_marker_index(text: str) -> int:
    indexes = [
        str(text or "").rfind(marker)
        for marker in ("只读", "源项目", "源工程", "源路径", "源目录", "读回", "读取", "打开", "查看", "分析", "追踪", "结合", "基于", "根据", "参考", "从", "载入", "检查")
        if str(text or "").rfind(marker) >= 0
    ]
    return max(indexes) if indexes else -1


def _first_output_path_index(text: str) -> int:
    match = re.search(r"(?:^|[^\w/\\.-])(?:output|dist|build|coverage)/", str(text or ""), flags=re.IGNORECASE)
    return match.start() + (1 if match.group(0) and not match.group(0)[0].isalnum() else 0) if match else -1


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


def _has_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker.lower() in str(text or "").lower() for marker in markers)


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


def _dedupe_dicts(values: list[dict[str, Any]], *, key_fields: tuple[str, ...]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for value in values:
        item = dict(value or {})
        key = tuple(str(item.get(field) or "").strip() for field in key_fields)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result
