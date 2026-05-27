from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


_GLOBAL_WRITE_FORBID_MARKERS = (
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
    "只分析，不要写",
    "只分析不要写",
    "do not write",
    "don't write",
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
    "源项目只读",
    "源工程只读",
    "源目录只读",
    "只读源项目",
    "只读源工程",
    "只读源目录",
    "do not modify source project",
    "don't modify source project",
)


@dataclass(frozen=True, slots=True)
class BoundaryPolicy:
    policy_id: str
    forbidden_actions: tuple[str, ...] = ()
    required_process: tuple[str, ...] = ()
    write_allowed: bool = True
    network_allowed: bool = True
    shell_allowed: bool = True
    browser_allowed: bool = True
    approval_policy: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "agent_runtime.boundary_policy"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["forbidden_actions"] = list(self.forbidden_actions)
        payload["required_process"] = list(self.required_process)
        payload["diagnostics"] = dict(self.diagnostics or {})
        return payload


def build_boundary_policy(
    *,
    user_message: str,
    request_facts: dict[str, Any] | None = None,
    current_turn_context: dict[str, Any] | None = None,
) -> BoundaryPolicy:
    text = str(user_message or "").lower()
    context = dict(current_turn_context or {})
    forbidden: list[str] = []
    required: list[str] = []
    write_required_by_context = _write_required_by_context(text=text, context=context)
    scoped_source_readonly = any(marker in text for marker in _SCOPED_SOURCE_WRITE_FORBID_MARKERS)
    global_write_forbidden = any(marker in text for marker in _GLOBAL_WRITE_FORBID_MARKERS)
    broad_no_modify = any(marker in text for marker in _BROAD_NO_MODIFY_MARKERS)
    if global_write_forbidden:
        forbidden.extend(["edit_workspace", "write_file", "modify_code"])
    elif broad_no_modify and not write_required_by_context:
        forbidden.extend(["edit_workspace", "write_file", "modify_code"])
    if any(marker in text for marker in ("不要联网", "不要搜索", "不要查网页", "no web", "do not search")):
        forbidden.extend(["search_external", "fetch_url"])
    if any(marker in text for marker in ("先写计划", "先给计划", "必须先写计划", "计划书")):
        required.append("plan_before_execute")
    if any(marker in text for marker in ("必须测试", "必须验证", "跑测试", "run tests")):
        required.append("verify_before_final")
    for item in list(context.get("forbidden_actions") or []):
        if str(item).strip():
            forbidden.append(str(item).strip())
    for item in _structured_forbidden_actions(context):
        forbidden.append(item)
    approval_policy = str(context.get("approval_policy") or context.get("permission_mode") or "").strip()
    forbidden_actions = tuple(_dedupe(forbidden))
    return BoundaryPolicy(
        policy_id=f"boundary:{str(dict(request_facts or {}).get('facts_id') or 'runtime')}",
        forbidden_actions=forbidden_actions,
        required_process=tuple(_dedupe(required)),
        write_allowed=not bool(set(forbidden_actions) & {"edit_workspace", "write_file", "modify_code"}),
        network_allowed=not bool(set(forbidden) & {"search_external", "fetch_url"}),
        shell_allowed="run_command" not in forbidden,
        browser_allowed="use_browser" not in forbidden,
        approval_policy=approval_policy,
        diagnostics={
            "source": "latest_user_message_and_context",
            "hard_boundary": False,
            "authority_boundary": "operation_gate_and_sandbox_policy",
            "natural_language_markers_are_intent_signals": True,
            "global_write_forbidden": global_write_forbidden,
            "global_write_forbid_signal": global_write_forbidden,
            "broad_no_modify_signal": broad_no_modify,
            "scoped_source_readonly": scoped_source_readonly,
            "write_required_by_context": write_required_by_context,
            "structured_forbidden_actions_used": [
                item
                for item in forbidden_actions
                if item in {"edit_workspace", "write_file", "modify_code"}
            ],
        },
    )


def _write_required_by_context(*, text: str, context: dict[str, Any]) -> bool:
    if any(marker in str(text or "") for marker in ("写入", "输出到", "保存", "生成", "产出", "创建", "新建")):
        return True
    if "output/" in str(text or "").replace("\\", "/").lower():
        return True
    resource_contract = dict(
        context.get("resource_contract")
        or dict(context.get("model_turn_decision") or {}).get("resource_contract")
        or {}
    )
    if list(resource_contract.get("required_write_files") or []) or list(resource_contract.get("required_write_dirs") or []):
        return True
    if list(dict(context.get("artifact_policy") or {}).get("required_output_paths") or []):
        return True
    explicit_inputs = dict(context.get("explicit_inputs") or {})
    return any(str(explicit_inputs.get(key) or "").strip() for key in ("output_path", "artifact_path", "target_output_path"))


def _structured_forbidden_actions(context: dict[str, Any]) -> list[str]:
    actions: list[str] = []
    for source in (
        dict(context.get("model_turn_decision") or {}),
        dict(context.get("task_goal_spec") or context.get("goal_frame") or {}),
    ):
        for item in list(source.get("forbidden_actions") or []):
            value = str(item or "").strip()
            if value:
                actions.append(value)
    return _dedupe(actions)


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


