from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def prepare_runtime_sandbox_policy_for_turn(
    *,
    root_dir: Path,
    session_id: str,
    task_run_id: str,
    task_contract: dict[str, Any] | None,
    user_message: str,
    selected_recipe_payload: dict[str, Any],
    task_selection: dict[str, Any] | None,
    state_index: Any,
    event_log: Any,
) -> dict[str, Any]:
    inherited_workspace_key = _resolve_inherited_sandbox_workspace_key(
        session_id=session_id,
        current_task_run_id=task_run_id,
        task_contract=dict(task_contract or {}),
        user_message=user_message,
        task_selection=dict(task_selection or {}),
        state_index=state_index,
        event_log=event_log,
    )
    effective_selection = dict(task_selection or {})
    if inherited_workspace_key:
        effective_selection["sandbox_policy"] = {
            **dict(effective_selection.get("sandbox_policy") or {}),
            "workspace_key": inherited_workspace_key,
        }
    return prepare_runtime_sandbox_policy(
        root_dir=root_dir,
        session_id=session_id,
        task_run_id=task_run_id,
        task_contract=task_contract,
        user_message=user_message,
        selected_recipe_payload=selected_recipe_payload,
        task_selection=effective_selection,
    )


def prepare_runtime_sandbox_policy(
    *,
    root_dir: Path,
    session_id: str,
    task_run_id: str,
    task_contract: dict[str, Any] | None = None,
    user_message: str = "",
    selected_recipe_payload: dict[str, Any],
    task_selection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    recipe_metadata = dict(dict(selected_recipe_payload or {}).get("metadata") or {})
    base_policy = dict(recipe_metadata.get("sandbox_policy") or {})
    selection_policy = dict(dict(task_selection or {}).get("sandbox_policy") or {})
    policy = {**base_policy, **selection_policy}
    if not policy:
        return {}
    if policy.get("enabled") is False:
        return {"enabled": False, "mode": str(policy.get("mode") or "disabled")}
    policy["enabled"] = True
    policy.setdefault("mode", "workspace_overlay")
    policy.setdefault("side_effect_root", "output/sandbox_runs")
    policy.setdefault("workspace_dir_name", "workspace")
    policy.setdefault("real_workspace_access", "read_only")
    policy.setdefault("approval_policy", "sandboxed_side_effects")
    policy.setdefault("side_effect_tools", ["write_file", "edit_file", "terminal", "python_repl"])
    policy.setdefault("side_effect_operations", ["op.write_file", "op.edit_file", "op.shell", "op.python_repl"])
    policy.setdefault("overlay_copy_on_write", True)
    workspace_root = workspace_root_for_runtime(root_dir)
    side_effect_root = Path(str(policy.get("side_effect_root") or "output/sandbox_runs"))
    if not side_effect_root.is_absolute():
        side_effect_root = workspace_root / side_effect_root
    workspace_key = str(policy.get("workspace_key") or "").strip()
    if not workspace_key:
        workspace_key = sandbox_workspace_key(
            session_id=session_id,
            task_run_id=task_run_id,
            task_contract=dict(task_contract or {}),
            user_message=user_message,
        )
    sandbox_root = side_effect_root / safe_path_component(workspace_key) / str(policy.get("workspace_dir_name") or "workspace")
    sandbox_root.mkdir(parents=True, exist_ok=True)
    policy["sandbox_root"] = str(sandbox_root.resolve())
    policy["side_effect_root"] = str(side_effect_root.resolve())
    policy["workspace_root"] = str(workspace_root)
    policy["workspace_key"] = workspace_key
    return policy


def sandbox_workspace_key(
    *,
    session_id: str,
    task_run_id: str,
    task_contract: dict[str, Any],
    user_message: str,
) -> str:
    output_scope = sandbox_output_scope(task_contract=task_contract, user_message=user_message)
    if output_scope:
        return f"session:{session_id}:scope:{output_scope}"
    return task_run_id


def sandbox_output_scope(*, task_contract: dict[str, Any], user_message: str) -> str:
    candidates: list[str] = []
    semantic_contract = dict(task_contract.get("task_requirement_contract") or {})
    execution_obligation = dict(semantic_contract.get("execution_obligation") or {})
    for key in ("required_writes", "required_outputs", "required_output_paths"):
        for item in list(execution_obligation.get(key) or semantic_contract.get(key) or []):
            if isinstance(item, dict):
                value = str(item.get("path") or item.get("output_path") or "")
            else:
                value = str(item or "")
            if value.strip():
                candidates.append(value)
    candidates.extend(extract_workspace_path_scopes(user_message))
    for candidate in candidates:
        normalized = str(candidate or "").replace("\\", "/").strip()
        if not normalized:
            continue
        if normalized.endswith("/"):
            return normalized.strip("/")
        suffix = "/" + normalized.rsplit("/", 1)[-1]
        if "." in suffix:
            parent = normalized.rsplit("/", 1)[0] if "/" in normalized else ""
            if parent:
                return parent.strip("/")
        if normalized.startswith(("frontend/public/games/", "output/")):
            return normalized.strip("/")
    return ""


def workspace_root_for_runtime(root_dir: Path) -> Path:
    root = Path(root_dir).resolve()
    if root.name == "backend" and root.parent.exists():
        return root.parent.resolve()
    if root.name == "runtime_state" and root.parent.name == "storage":
        return root.parent.parent.resolve()
    if root.name == "storage":
        return root.parent.resolve()
    return root


def safe_path_component(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(value or "sandbox"))
    return safe.strip("._") or "sandbox"


def extract_workspace_path_scopes(text: str) -> list[str]:
    values: list[str] = []
    pattern = re.compile(r"((?:frontend|backend|output|docs|storage|scripts|tests)/[^\s，。；;：:]+)")
    for match in pattern.finditer(str(text or "").replace("\\", "/")):
        value = match.group(1).strip().strip("。,.，；;：:")
        if value:
            values.append(value)
    return values


def _resolve_inherited_sandbox_workspace_key(
    *,
    session_id: str,
    current_task_run_id: str,
    task_contract: dict[str, Any],
    user_message: str,
    task_selection: dict[str, Any],
    state_index: Any,
    event_log: Any,
) -> str:
    if str(dict(task_selection.get("sandbox_policy") or {}).get("workspace_key") or "").strip():
        return ""
    if str(task_selection.get("interaction_mode") or "").strip() != "professional_mode":
        return ""
    previous_policy = _latest_session_sandbox_policy(
        session_id=session_id,
        exclude_task_run_id=current_task_run_id,
        state_index=state_index,
        event_log=event_log,
    )
    previous_key = str(previous_policy.get("workspace_key") or "").strip()
    if not previous_key:
        return ""
    previous_scope = _sandbox_scope_from_workspace_key(previous_key)
    current_scope = sandbox_output_scope(task_contract=task_contract, user_message=user_message)
    if current_scope:
        return previous_key if _sandbox_scopes_overlap(current_scope, previous_scope) else ""
    return previous_key if _is_sandbox_continuation_message(user_message, previous_scope=previous_scope) else ""


def _latest_session_sandbox_policy(
    *,
    session_id: str,
    exclude_task_run_id: str,
    state_index: Any,
    event_log: Any,
) -> dict[str, Any]:
    task_runs = sorted(
        (
            task_run
            for task_run in state_index.list_session_task_runs(session_id)
            if str(task_run.task_run_id or "") != str(exclude_task_run_id or "")
        ),
        key=lambda item: float(item.updated_at or item.created_at or 0.0),
        reverse=True,
    )
    for task_run in task_runs:
        for event in reversed(event_log.list_events(task_run.task_run_id)):
            if event.event_type != "runtime_sandbox_prepared":
                continue
            policy = dict(dict(event.payload or {}).get("sandbox_policy") or {})
            if policy.get("enabled") is True and str(policy.get("workspace_key") or "").strip():
                return policy
    return {}


def _sandbox_scope_from_workspace_key(workspace_key: str) -> str:
    marker = ":scope:"
    value = str(workspace_key or "").strip()
    if marker not in value:
        return ""
    return value.rsplit(marker, 1)[-1].strip()


def _sandbox_scopes_overlap(left: str, right: str) -> bool:
    left_norm = str(left or "").replace("\\", "/").strip("/")
    right_norm = str(right or "").replace("\\", "/").strip("/")
    if not left_norm or not right_norm:
        return False
    return left_norm == right_norm or left_norm.startswith(right_norm + "/") or right_norm.startswith(left_norm + "/")


def _is_sandbox_continuation_message(message: str, *, previous_scope: str) -> bool:
    text = str(message or "").replace("\\", "/").strip().lower()
    if not text:
        return False
    continuation_markers = (
        "继续",
        "接着",
        "上一轮",
        "上次",
        "读回",
        "验收",
        "修正",
        "修改",
        "补上",
        "完善",
        "确认",
        "检查",
        "test",
        "verify",
        "continue",
        "read back",
        "fix",
        "update",
    )
    if any(marker in text for marker in continuation_markers):
        return True
    scope_tail = str(previous_scope or "").replace("\\", "/").strip("/").rsplit("/", 1)[-1].lower()
    if scope_tail and scope_tail in text:
        return True
    return any(token in text for token in ("game.js", "index.html", "readme", "assets", "产物", "项目", "工程"))
