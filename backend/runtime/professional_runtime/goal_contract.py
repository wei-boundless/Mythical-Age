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
    output_paths = _dedupe_strings(
        [
            *[
                str(item.get("path") or "").strip()
                for item in obligation_writes
                if str(item.get("path") or "").strip()
            ],
            *_extract_goal_output_paths(goal_text),
        ]
    )
    raw_material_paths = _dedupe_strings([*raw_material_paths, *_extract_goal_material_paths(goal_text)])
    material_types = _dedupe_strings(
        [
            *[str(item.get("kind") or "").strip() for item in materials if str(item.get("kind") or "").strip()],
            *[str(item.get("kind") or "").strip() for item in obligation_reads if str(item.get("kind") or "").strip()],
        ]
    )
    material_paths = [
        path
        for path in raw_material_paths
        if _goal_material_path_is_credible(path, output_paths=output_paths, goal_text=goal_text)
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
    task_goal_type = str(semantic_contract.get("task_goal_type") or "").strip()
    write_forbidden = bool(forbidden_actions.intersection({"modify_code", "write_file", "edit_file"}))
    requires_write = bool(obligation_writes) and not write_forbidden
    if not requires_write:
        requires_write = (
            not write_forbidden
            and ("apply_real_change" in required_actions or task_goal_type in {"code_fix_execution", "artifact_delivery"})
        )
    requires_verify = bool(obligation_commands or obligation_verifications)
    if not requires_verify:
        requires_verify = "validate_deliverables" in required_actions and task_goal_type in {
            "code_fix_execution",
            "regression_test_design",
        }
    response_terms = _dedupe_strings(
        [
            *_response_terms_from_semantic_contract(semantic_contract),
            *[
                _response_term_for_deliverable(item)
                for item in list(obligation.get("required_deliverables") or [])
                if str(item).strip()
            ],
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
                    if item != "read_material" or material_paths
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


def _semantic_control_plan(
    *,
    user_message: str,
    semantic_contract: dict[str, Any],
    mode_policy: dict[str, Any],
    goal_contract: ProfessionalTaskGoalContract,
) -> list[dict[str, Any]]:
    """Deprecated: kept only until the professional driver is fully decomposed.

    System code must not use this as an agent behavior plan source.
    """
    interaction_mode = str(mode_policy.get("interaction_mode") or "professional_mode").strip()
    task_goal_type = str(semantic_contract.get("task_goal_type") or "general").strip()
    reasoning_steps = [
        str(item).strip()
        for item in list(semantic_contract.get("required_reasoning_steps") or [])
        if str(item).strip()
    ]
    plan: list[dict[str, Any]] = [
        {
            "plan_item_id": "professional.mode_policy",
            "title": "绑定交互模式和任务边界",
            "step_kind": "plan_item",
            "executor_type": "model",
            "action_kind": "main_agent",
            "summary": f"{interaction_mode}: {str(user_message or '').strip()[:180]}",
            "required_operations": ["op.model_response"],
            "contract_required": True,
        },
        {
            "plan_item_id": "professional.semantic_contract",
            "title": "绑定语义任务契约",
            "step_kind": "plan_item",
            "executor_type": "model",
            "action_kind": "main_agent",
            "summary": f"任务类型 {task_goal_type}；交付物：{', '.join(list(semantic_contract.get('deliverables') or [])) or 'final_answer'}。",
            "required_operations": ["op.model_response"],
            "contract_required": True,
        },
    ]
    if goal_contract.requires_material_review:
        plan.append(
            {
                "plan_item_id": "professional.material_review",
                "title": "读取并抽取指定材料证据",
                "step_kind": "plan_item",
                "executor_type": "model",
                "action_kind": "main_agent",
                "summary": _material_review_summary(goal_contract),
                "required_operations": _required_operations_for_contract_materials(goal_contract),
                "material_paths": list(goal_contract.required_material_paths),
                "contract_required": True,
            }
        )
    if reasoning_steps:
        plan.append(
            {
                "plan_item_id": "professional.reasoning_steps",
                "title": "按专业步骤完成结构化分析",
                "step_kind": "plan_item",
                "executor_type": "model",
                "action_kind": "main_agent",
                "summary": " -> ".join(reasoning_steps),
                "required_operations": ["op.model_response"],
                "contract_required": True,
            }
        )
    if bool(dict(mode_policy.get("tool_policy") or {}).get("requires_evidence_packet")) or bool(
        dict(semantic_contract.get("material_handling_policy") or {}).get("evidence_packet_required")
    ):
        plan.append(
            {
                "plan_item_id": "professional.evidence_packet",
                "title": "构建证据包",
                "step_kind": "plan_item",
                "executor_type": "model",
                "action_kind": "main_agent",
                "summary": "将工具观察、材料事实、失败分类和限制先沉淀为 evidence packet。",
                "required_operations": ["op.model_response"],
                "contract_required": True,
            }
        )
    if goal_contract.requires_write_output:
        plan.append(
            {
                "plan_item_id": "professional.produce_output",
                "title": "执行真实代码或产物修改",
                "step_kind": "plan_item",
                "executor_type": "model",
                "action_kind": "main_agent",
                "summary": _produce_output_summary(goal_contract),
                "required_operations": ["op.write_file", "op.edit_file"],
                "contract_required": True,
            }
        )
    if goal_contract.requires_verification_command:
        plan.append(
            {
                "plan_item_id": "professional.verify_output",
                "title": "运行真实验证或说明限制",
                "step_kind": "plan_item",
                "executor_type": "model",
                "action_kind": "main_agent",
                "summary": "使用 terminal 运行验证命令，或明确说明无法验证的真实限制。",
                "required_operations": ["op.shell"],
                "contract_required": True,
            }
        )
    plan.extend(
        [
            {
                "plan_item_id": "professional.synthesis",
                "title": "综合证据形成专业结论",
                "step_kind": "plan_item",
                "executor_type": "model",
                "action_kind": "main_agent",
                "summary": _synthesis_summary(goal_contract),
                "required_operations": ["op.model_response"],
                "response_must_include": list(goal_contract.response_must_include),
                "contract_required": True,
            },
            {
                "plan_item_id": "professional.validate_deliverable",
                "title": "按交付物验证最终回答",
                "step_kind": "plan_item",
                "executor_type": "model",
                "action_kind": "main_agent",
                "summary": "检查语义交付物、证据对齐、协议泄漏和未支持声明。",
                "required_operations": ["op.model_response"],
                "contract_required": True,
            },
        ]
    )
    return plan


def _build_goal_contract(
    *,
    task_run_id: str,
    user_message: str,
    selected_recipe_payload: dict[str, Any],
) -> ProfessionalTaskGoalContract:
    _ = selected_recipe_payload
    goal = str(user_message or "").strip()
    output_paths = _extract_goal_output_paths(goal)
    material_paths = [
        path for path in _extract_goal_material_paths(goal) if not _same_path_member(path, output_paths)
    ]
    material_types = _dedupe_strings([_path_suffix(path) for path in material_paths if _path_suffix(path)])
    requires_write = _goal_text_requires_write_output(goal, material_paths=material_paths, output_paths=output_paths)
    requires_verify = _goal_text_requires_verification_command(goal)
    requires_delegation = _goal_text_requires_delegation(goal, material_types=material_types)
    requires_material_review = bool(material_paths)
    required_tool_kinds: list[str] = []
    if requires_material_review:
        required_tool_kinds.append("read_material")
    if requires_write:
        required_tool_kinds.append("write_output")
    if requires_verify:
        required_tool_kinds.append("verify_command")
    if requires_delegation:
        required_tool_kinds.append("delegate_review")
    required_output_kinds = ["final_answer"]
    if requires_write:
        required_output_kinds.append("sandbox_file")
    return ProfessionalTaskGoalContract(
        contract_id=f"professional-goal-contract:{task_run_id}",
        goal=goal,
        required_material_paths=material_paths,
        required_output_paths=output_paths,
        material_types=material_types,
        required_tool_kinds=required_tool_kinds,
        required_output_kinds=required_output_kinds,
        requires_material_review=requires_material_review,
        requires_write_output=requires_write,
        requires_verification_command=requires_verify,
        requires_delegation=requires_delegation,
        response_must_include=_response_terms_from_goal(goal),
        forbidden_visible_markers=_forbidden_visible_markers(),
    )


def _extract_goal_material_paths(text: str) -> list[str]:
    return _dedupe_strings(
        [
            *_expand_material_directory_file_lists(text),
            *_additional_readable_paths_in_material_sentences(text),
            *[
                path
                for path, prefix, suffix in _path_mentions_with_context(text)
                if (
                    _material_path_candidate_is_readable(path)
                    and _path_context_indicates_material(path=path, prefix=prefix, suffix=suffix)
                    and not _path_context_indicates_output(path=path, prefix=prefix, suffix=suffix)
                )
            ],
        ]
    )


def _extract_goal_output_paths(text: str) -> list[str]:
    direct_paths = [
            path
            for path, prefix, suffix in _path_mentions_with_context(text)
            if _path_context_indicates_output(path=path, prefix=prefix, suffix=suffix)
    ]
    expanded_paths = _expand_output_directory_file_lists(text)
    output_dirs = _extract_required_output_dirs(text, expanded_paths)
    return _prefer_qualified_output_paths(_dedupe_strings([*direct_paths, *expanded_paths, *output_dirs]))


def _expand_output_directory_file_lists(text: str) -> list[str]:
    normalized = str(text or "").replace("\\", "/")
    output_dirs: list[str] = _explicit_output_directories(normalized)
    dir_pattern = re.compile(
        r"(?P<dir>(?:[\w.\-\u4e00-\u9fff]+/)+[\w.\-\u4e00-\u9fff]+/)",
        re.IGNORECASE,
    )
    for match in dir_pattern.finditer(normalized):
        directory = _clean_path_mention(str(match.group("dir") or "")).replace("\\", "/").strip("/")
        if not directory:
            continue
        context = _local_path_context(normalized, start=match.start(), end=match.end(), radius=24)
        if _context_indicates_read_material_path(context):
            continue
        if _context_indicates_output_path(context):
            output_dirs.append(directory)
    if not output_dirs:
        return []
    suffixes = "html|css|js|jsx|ts|tsx|py|json|md|txt|csv|yaml|yml|toml"
    file_pattern = re.compile(
        rf"(?<![\w/\\.-])(?P<file>[\w.\-\u4e00-\u9fff]+\.({suffixes}))(?![\w/\\.-])",
        re.IGNORECASE,
    )
    files = [_clean_path_mention(str(match.group("file") or "")) for match in file_pattern.finditer(normalized)]
    result: list[str] = []
    for directory in output_dirs:
        for filename in files:
            if not filename or "/" in filename:
                continue
            result.append(f"{directory}/{filename}")
    return _dedupe_strings(result)


def _expand_material_directory_file_lists(text: str) -> list[str]:
    normalized = str(text or "").replace("\\", "/")
    material_dirs: list[str] = _explicit_material_directories(normalized)
    dir_pattern = re.compile(
        r"(?P<dir>(?:[\w.\-\u4e00-\u9fff]+/)+[\w.\-\u4e00-\u9fff]+/)",
        re.IGNORECASE,
    )
    for match in dir_pattern.finditer(normalized):
        directory = _clean_path_mention(str(match.group("dir") or "")).replace("\\", "/").strip("/")
        if not directory:
            continue
        context = _local_path_context(normalized, start=match.start(), end=match.end(), radius=32)
        if _context_indicates_read_material_path(context) and not _context_indicates_output_path(context):
            material_dirs.append(directory)
    if not material_dirs:
        return []
    suffixes = "html|css|js|jsx|ts|tsx|py|json|md|txt|csv|yaml|yml|toml"
    file_pattern = re.compile(
        rf"(?<![\w/\\.-])(?P<file>[\w.\-\u4e00-\u9fff]+\.({suffixes}))(?![\w/\\.-])",
        re.IGNORECASE,
    )
    files = [_clean_path_mention(str(match.group("file") or "")) for match in file_pattern.finditer(normalized)]
    result: list[str] = []
    for directory in material_dirs:
        for filename in files:
            if not filename or "/" in filename:
                continue
            result.append(f"{directory}/{filename}")
    explicit_paths = [path for path, _prefix, _suffix in _path_mentions_with_context(normalized)]
    return _dedupe_strings([*explicit_paths, *result])


def _extract_required_output_dirs(text: str, expanded_paths: list[str]) -> list[str]:
    normalized = str(text or "").replace("\\", "/")
    base_dirs = _dedupe_strings(
        [
            path.rsplit("/", 1)[0]
            for path in list(expanded_paths or [])
            if "/" in str(path or "")
        ]
    )
    if not base_dirs:
        return []
    result: list[str] = []
    explicit_dir_pattern = re.compile(
        r"(?P<dir>[\w.\-\u4e00-\u9fff]+/)\s*(?:目录|文件夹)",
        re.IGNORECASE,
    )
    for match in explicit_dir_pattern.finditer(normalized):
        directory = _clean_path_mention(str(match.group("dir") or "")).replace("\\", "/").strip("/")
        if not directory:
            continue
        context = _local_path_context(normalized, start=match.start(), end=match.end(), radius=18)
        if not any(marker in context for marker in ("创建", "新建", "必须", "写入", "生成")):
            continue
        for base_dir in base_dirs:
            result.append(f"{base_dir}/{directory}")
    return _dedupe_strings(result)


def _path_mentions_with_prefix(text: str) -> list[tuple[str, str]]:
    return [(path, prefix) for path, prefix, _suffix in _path_mentions_with_context(text)]


def _path_mentions_with_context(text: str) -> list[tuple[str, str, str]]:
    normalized = str(text or "")
    suffixes = "py|json|md|txt|csv|xlsx|xls|pdf|yaml|yml|toml|docx|pptx|html|css|js|jsx|ts|tsx"
    patterns = [
        re.compile(
            rf"(?P<path>(?:[\w.\-\u4e00-\u9fff]+[\\/])+[\w.\-\u4e00-\u9fff]+\.({suffixes}))",
            re.IGNORECASE,
        ),
        re.compile(
            rf"(?<![\w/\\.-])(?P<path>[\w.\-\u4e00-\u9fff]+\.({suffixes}))(?![\w/\\.-])",
            re.IGNORECASE,
        ),
    ]
    mentions: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for pattern in patterns:
        for match in pattern.finditer(normalized):
            path = _clean_path_mention(str(match.group("path") or ""))
            if not path or path in seen:
                continue
            seen.add(path)
            prefix = _local_path_context(normalized, start=match.start(), end=match.start(), radius=18)
            suffix = _local_path_context(normalized, start=match.end(), end=match.end(), radius=18)
            mentions.append((path, prefix, suffix))
    return mentions


def _additional_readable_paths_in_material_sentences(text: str) -> list[str]:
    normalized = str(text or "").replace("\\", "/")
    suffixes = "py|json|md|txt|csv|xlsx|xls|pdf|yaml|yml|toml|docx|pptx|html|css|js|jsx|ts|tsx"
    path_pattern = re.compile(
        rf"(?P<path>(?:[\w.\-\u4e00-\u9fff]+/)+[\w.\-\u4e00-\u9fff]+\.({suffixes}))",
        re.IGNORECASE,
    )
    results: list[str] = []
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
            path = _clean_path_mention(str(match.group("path") or ""))
            if path and _material_path_candidate_is_readable(path):
                results.append(path)
    return _dedupe_strings(results)


def _first_output_marker_index(text: str) -> int:
    indexes = [
        str(text or "").find(marker)
        for marker in ("目标输出", "输出目录", "输出到", "写入", "保存", "生成", "产出", "落到", "创建", "新建")
        if str(text or "").find(marker) >= 0
    ]
    return min(indexes) if indexes else -1


def _first_output_path_index(text: str) -> int:
    match = re.search(r"(?:^|[^\w/\\.-])(?:output|dist|build|coverage)/", str(text or ""), flags=re.IGNORECASE)
    return match.start() + (1 if match.group(0) and not match.group(0)[0].isalnum() else 0) if match else -1


def _explicit_output_directories(text: str) -> list[str]:
    result: list[str] = []
    pattern = re.compile(
        r"(?:目标输出目录|输出目录|目标目录|写入目录|保存目录|产物目录)[^/\\]{0,48}(?P<dir>(?:frontend|backend|output|docs|storage|scripts|tests|src|app|packages|knowledge)/(?:[\w.\-\u4e00-\u9fff]+/)*[\w.\-\u4e00-\u9fff]+/?)",
        re.IGNORECASE,
    )
    for match in pattern.finditer(str(text or "").replace("\\", "/")):
        directory = _clean_path_mention(str(match.group("dir") or "")).replace("\\", "/").strip("/")
        if directory:
            result.append(directory)
    return _dedupe_strings(result)


def _explicit_material_directories(text: str) -> list[str]:
    result: list[str] = []
    pattern = re.compile(
        r"(?:只读源项目|只读源工程|只读源目录|源项目|源工程|源目录|源路径)[^/\\]{0,48}(?P<dir>(?:frontend|backend|output|docs|storage|scripts|tests|src|app|packages|knowledge)/(?:[\w.\-\u4e00-\u9fff]+/)*[\w.\-\u4e00-\u9fff]+/?)",
        re.IGNORECASE,
    )
    for match in pattern.finditer(str(text or "").replace("\\", "/")):
        directory = _clean_path_mention(str(match.group("dir") or "")).replace("\\", "/").strip("/")
        if directory:
            result.append(directory)
    return _dedupe_strings(result)


def _local_path_context(text: str, *, start: int, end: int, radius: int) -> str:
    value = str(text or "")
    left = value.rfind("\n", 0, start)
    right = value.find("\n", end)
    line_start = 0 if left < 0 else left + 1
    line_end = len(value) if right < 0 else right
    return value[max(line_start, start - radius) : min(line_end, end + radius)]


def _clean_path_mention(path: str) -> str:
    cleaned = str(path or "").strip().strip("`'\"“”‘’（）()[]{}，。；;、")
    return cleaned.replace("\\", "/").strip("/")


def _material_path_candidate_is_readable(path: str) -> bool:
    normalized = _normalize_path_for_match(path)
    if not normalized:
        return False
    basename = normalized.rsplit("/", 1)[-1]
    if not basename or "." not in basename:
        return False
    if any(token in normalized for token in ("，", "。", "；", "、", "：", " ", "必须", "引用", "目录")):
        return False
    return True


def _prefix_indicates_output_path(prefix: str) -> bool:
    return _context_indicates_output_path(prefix)


def _path_context_indicates_output(*, path: str, prefix: str, suffix: str) -> bool:
    normalized_path = _normalize_path_for_match(path)
    if normalized_path.startswith("output/"):
        return True
    context = f"{prefix}{suffix}"
    if not _context_indicates_output_path(context):
        return False
    if _context_indicates_read_material_path(prefix) and not any(
        marker in prefix
        for marker in ("目标输出", "输出目录", "输出到", "写入", "保存", "生成", "产出", "落到", "创建", "新建")
    ):
        return False
    if _context_indicates_output_path(suffix) and not _context_indicates_output_path(prefix):
        return False
    return True


def _path_context_indicates_material(*, path: str, prefix: str, suffix: str) -> bool:
    normalized_path = _normalize_path_for_match(path)
    if normalized_path.startswith("output/"):
        return False
    context = f"{prefix}{suffix}"
    if _context_indicates_read_material_path(context):
        return True
    if any(marker in prefix for marker in ("根据", "基于", "参考", "结合", "读取", "审查", "分析", "检查", "查看")):
        return True
    if _looks_like_source_or_test_path(normalized_path) and not _context_indicates_output_path(prefix):
        return True
    return False


def _looks_like_source_or_test_path(path: str) -> bool:
    normalized = _normalize_path_for_match(path)
    return normalized.startswith(
        (
            "tests/",
            "backend/",
            "frontend/",
            "src/",
            "app/",
            "packages/",
            ".materials/",
        )
    )


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
            "检查",
            "查看",
            "审查",
            "分析",
            "追踪",
            "结合",
            "基于",
            "根据",
            "参考",
        )
    )


def _same_path_member(path: str, paths: list[str]) -> bool:
    normalized = _normalize_path_for_match(path)
    return any(normalized == _normalize_path_for_match(item) for item in paths)


def _same_basename_member(path: str, paths: list[str]) -> bool:
    basename = _normalize_path_for_match(path).rsplit("/", 1)[-1]
    if not basename:
        return False
    return any(basename == _normalize_path_for_match(item).rsplit("/", 1)[-1] for item in paths)


def _prefer_qualified_output_paths(paths: list[str]) -> list[str]:
    normalized_paths = [_normalize_path_for_match(path) for path in paths]
    qualified_basenames = {
        item.rsplit("/", 1)[-1]
        for item in normalized_paths
        if "/" in item and item.rsplit("/", 1)[-1]
    }
    result: list[str] = []
    for original, normalized in zip(paths, normalized_paths):
        if "/" not in normalized and normalized in qualified_basenames:
            continue
        result.append(original)
    return _dedupe_strings(result)


def _goal_material_path_is_credible(path: str, *, output_paths: list[str], goal_text: str) -> bool:
    normalized = _normalize_path_for_match(path)
    if not normalized:
        return False
    if _same_path_member(normalized, output_paths):
        return False
    if not _path_suffix(normalized) and not _is_material_directory_path(normalized):
        return False
    if any(marker in normalized for marker in ("sandbox overlay", "必须是", "目录必须", "难度", "结束")):
        return False
    if normalized.startswith("frontend/public/games/"):
        return False
    goal = str(goal_text or "")
    if normalized in _extract_goal_output_paths(goal):
        return False
    return True


def _path_suffix(path: str) -> str:
    text = str(path or "").strip()
    if "." not in text:
        return ""
    suffix = "." + text.rsplit(".", 1)[-1].lower()
    return suffix if len(suffix) > 1 else ""


def _is_material_directory_path(path: str) -> bool:
    normalized = str(path or "").replace("\\", "/").strip().strip("/").lower()
    if not normalized:
        return False
    return normalized.endswith("/assets") or normalized.endswith("/asset") or normalized.endswith("/static")


def _goal_text_requires_write_output(
    text: str,
    *,
    material_paths: list[str],
    output_paths: list[str],
) -> bool:
    normalized = str(text or "").lower()
    if any(marker in normalized for marker in ("读回", "验收", "确认上一轮", "确认上轮")) and not any(
        marker in normalized
        for marker in ("必须写入", "重新写入", "继续写入", "修改", "修复", "生成文件", "创建文件", "新建文件")
    ):
        return False
    if any(
        marker in normalized
        for marker in (
            "写入",
            "保存",
            "产出",
            "生成文件",
            "草案文件",
            "实施草案",
            "创建文件",
            "新建文件",
            "sandbox overlay 中完成",
            "sandbox overlay",
        )
    ):
        return True
    if output_paths:
        return True
    code_or_config_target = any(_path_suffix(path) in {".py", ".ts", ".tsx", ".js", ".jsx", ".json"} for path in material_paths)
    return code_or_config_target and any(marker in normalized for marker in ("修复", "改掉", "修改", "编辑"))


def _goal_text_requires_verification_command(text: str) -> bool:
    normalized = str(text or "").lower()
    return any(
        marker in normalized
        for marker in (
            "运行命令",
            "命令验证",
            "运行一个命令",
            "运行一个只读命令",
            "powershell",
            "terminal",
            "shell",
        )
    )


def _goal_text_requires_delegation(text: str, *, material_types: list[str]) -> bool:
    normalized = str(text or "").lower()
    if any(marker in normalized for marker in ("必须委派", "需要委派", "交给子 agent", "交给子agent")):
        return True
    specialist_types = {".pdf", ".xlsx", ".xls", ".docx", ".pptx"}
    return bool(specialist_types.intersection(set(material_types)))


def _response_terms_from_goal(text: str) -> list[str]:
    normalized = str(text or "")
    terms: list[str] = []
    for marker in (
        "结构",
        "根因",
        "回归",
        "治理",
        "库存",
        "行动",
        "后端",
        "前端",
        "测试",
        "超时",
        "原因",
        "验证",
    ):
        if marker.lower() in normalized.lower():
            terms.append(marker)
    for match in re.finditer(r"\b[A-Z][A-Za-z0-9-]*(?:\s+[A-Z][A-Za-z0-9-]*){1,4}\b", normalized):
        terms.append(match.group(0).strip())
    for match in re.finditer(r"\b[A-Z0-9][A-Z0-9-]{3,}\b", normalized):
        terms.append(match.group(0).strip())
    for match in re.finditer(r"必须包含([^。；;\n]+)", normalized):
        chunk = match.group(1)
        for part in re.split(r"[、,，和与]", chunk):
            value = part.strip(" ：:。；;，,")
            if value:
                terms.append(value)
    return _dedupe_strings(terms)[:10]


def _response_terms_from_semantic_contract(semantic_contract: dict[str, Any]) -> list[str]:
    task_goal_type = str(semantic_contract.get("task_goal_type") or "").strip()
    terms = _response_terms_from_goal(str(semantic_contract.get("user_goal") or ""))
    if task_goal_type == "material_synthesis":
        return terms
    if task_goal_type == "test_report_triage":
        return _dedupe_strings(["失败归类", "结构性根因", "回归测试", "证据边界", *terms])
    if task_goal_type == "runtime_trace_analysis":
        return _dedupe_strings(["事件链", "转折点", "结构性根因", "恢复", *terms])
    if task_goal_type == "code_fix_execution":
        return _dedupe_strings(["修改", "文件", "验证", *terms])
    if task_goal_type == "regression_test_design":
        return _dedupe_strings(["复现输入", "断言", "覆盖风险", "测试文件", *terms])
    return terms


def _response_term_for_deliverable(deliverable: Any) -> str:
    normalized = str(deliverable or "").strip()
    mapping = {
        "change_summary": "修改",
        "changed_files": "文件",
        "verification_result_or_limitation": "验证",
        "failure_classification": "失败归类",
        "structural_root_causes": "结构性根因",
        "regression_test_plan": "回归测试",
        "evidence_limits": "证据边界",
        "artifact_refs": "产物",
        "completion_status": "完成状态",
        "limitations": "限制",
        "tool_grounded_answer": "",
        "direct_answer": "",
        "source_or_memory_boundary": "",
        "conversational_response": "",
        "inspection_findings": "",
        "runnable_artifact_refs": "",
        "gameplay_acceptance": "",
        "workflow_acceptance": "",
        "visual_asset_refs": "",
        "verification_evidence": "",
        "final_report": "",
        "evidence_refs": "",
    }
    return mapping.get(normalized, "")


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


def _material_review_summary(contract: ProfessionalTaskGoalContract) -> str:
    if contract.required_material_paths:
        return "必须先取得这些材料的真实观察：" + "、".join(contract.required_material_paths[:6])
    return "复核当前可见上下文和能力边界。"


def _produce_output_summary(contract: ProfessionalTaskGoalContract) -> str:
    if contract.required_output_paths:
        return "必须通过 write_file/edit_file 产出：" + "、".join(contract.required_output_paths[:4])
    return "必须通过 write_file 或 edit_file 形成用户要求的真实产物；不能只在最终回答里声称已产出。"


def _synthesis_summary(contract: ProfessionalTaskGoalContract) -> str:
    terms = "、".join(contract.response_must_include)
    if terms:
        return f"最终回答必须覆盖验收词：{terms}；并说明真实完成项、限制和下一步。"
    return "最终回答必须基于真实观察说明完成项、结论、限制和下一步。"


def _required_operations_for_contract_materials(contract: ProfessionalTaskGoalContract) -> list[str]:
    operations = ["op.read_file", "op.search_files", "op.search_text"]
    if any(suffix in {".json", ".yaml", ".yml", ".toml"} for suffix in contract.material_types):
        operations.insert(0, "op.read_structured_file")
    if contract.requires_delegation:
        operations.append("op.delegate_to_agent")
    return _dedupe_strings(operations)


def _goal_contract_instruction(goal_contract: ProfessionalTaskGoalContract | None) -> str:
    if goal_contract is None:
        return ""
    lines: list[str] = ["目标契约："]
    if goal_contract.required_material_paths:
        lines.append("必须取得真实材料观察：" + "、".join(goal_contract.required_material_paths[:6]) + "。")
    if goal_contract.requires_write_output:
        lines.append("用户要求真实写入或修改产物；必须使用 write_file 或 edit_file，不能只口头声称完成。")
    if goal_contract.requires_verification_command:
        lines.append("用户要求命令验证；完成写入或修改后必须使用 terminal 返回真实验证结果。")
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
