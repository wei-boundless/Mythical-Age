from __future__ import annotations

from pathlib import Path
from typing import Any


def validate_required_artifact_file(
    *,
    root_dir: Path,
    selected_recipe_payload: dict[str, Any],
    artifact_policy: dict[str, Any] | None = None,
    final_content: str,
    result_refs: tuple[str, ...],
    event_log_events: list[dict[str, Any]],
) -> dict[str, Any]:
    artifact_policy_payload = dict(artifact_policy or {})
    rules = [
        dict(item)
        for item in list(selected_recipe_payload.get("validation_rules") or [])
        if str(dict(item).get("validation_kind") or "") == "artifact_file_required"
        and str(dict(item).get("severity") or "") == "error"
    ]
    if not rules:
        if _artifact_policy_requires_materialized_content(artifact_policy_payload):
            target_paths = _artifact_policy_target_paths(artifact_policy_payload)
            has_content = bool(str(final_content or "").strip())
            return {
                "passed": has_content,
                "required": True,
                "reason": (
                    "required artifact policy has final content for materialization"
                    if has_content
                    else "artifact_policy requires a final_content artifact but the model returned empty content"
                ),
                "source": "task_graph_artifact_policy",
                "artifact_targets": target_paths,
                "final_content_chars": len(str(final_content or "")),
                "result_ref_count": len(result_refs),
            }
        return {
            "passed": True,
            "required": False,
            "reason": "no artifact_file_required validation rule",
        }
    successful_writes = successful_write_file_paths(root_dir=root_dir, event_log_events=event_log_events)
    existing_writes = [item for item in successful_writes if Path(item["absolute_path"]).exists()]
    passed = bool(existing_writes)
    return {
        "passed": passed,
        "required": True,
        "reason": "required artifact file exists" if passed else "write_file was required but no successful existing artifact file was found",
        "rule_ids": [str(item.get("rule_id") or "") for item in rules],
        "successful_write_count": len(successful_writes),
        "existing_write_count": len(existing_writes),
        "artifacts": existing_writes,
        "final_content_chars": len(str(final_content or "")),
        "result_ref_count": len(result_refs),
    }


def successful_write_file_paths(
    *,
    root_dir: Path,
    event_log_events: list[dict[str, Any]],
) -> list[dict[str, str]]:
    workspace_root = workspace_root_from_runtime_root(root_dir)
    artifacts: list[dict[str, str]] = []
    for raw_event in event_log_events:
        event = _unwrap_runtime_event(raw_event)
        if str(event.get("event_type") or "") not in {"tool_result_received", "executor_observation_received"}:
            continue
        observation = dict(dict(event.get("payload") or {}).get("observation") or {})
        if observation.get("observation_type") != "tool_result":
            continue
        payload = dict(observation.get("payload") or {})
        if str(payload.get("tool_name") or "") != "write_file":
            continue
        structured_paths = _structured_write_paths(payload)
        if not structured_paths:
            continue
        for raw_path in structured_paths:
            candidate = Path(raw_path)
            if not candidate.is_absolute():
                candidate = workspace_root / str(raw_path).replace("\\", "/").strip().strip("/")
            candidate = candidate.resolve()
            try:
                relative_path = candidate.relative_to(workspace_root).as_posix()
            except ValueError:
                relative_path = candidate.as_posix()
            artifacts.append(
                {
                    "path": relative_path,
                    "absolute_path": candidate.as_posix(),
                    "observation_ref": str(event.get("refs", {}).get("observation_ref") or ""),
                }
            )
    unique: dict[str, dict[str, str]] = {}
    for item in artifacts:
        unique[item["absolute_path"]] = item
    return list(unique.values())


def workspace_root_from_runtime_root(root_dir: Path) -> Path:
    root = Path(root_dir).resolve()
    if root.name == "backend" and root.parent.exists():
        return root.parent.resolve()
    if root.name == "runtime_state" and root.parent.name == "storage" and root.parent.parent.exists():
        return root.parent.parent.resolve()
    if root.name == "storage" and root.parent.exists():
        return root.parent.resolve()
    return root


def artifact_repository_root_for_loop(root_dir: Path) -> Path:
    runtime_root = Path(root_dir).resolve()
    if runtime_root.name == "runtime_state":
        return runtime_root.parent / "artifact_repository"
    return runtime_root / "artifact_repository"


def _artifact_policy_requires_materialized_content(policy: dict[str, Any]) -> bool:
    artifact_policy = dict(policy or {})
    if not artifact_policy:
        return False
    if artifact_policy.get("enabled") is False:
        return False
    specs = [dict(item) for item in list(artifact_policy.get("artifacts") or []) if isinstance(item, dict)]
    if specs:
        return any(dict(item).get("required", True) is not False for item in specs)
    if artifact_policy.get("required") is False:
        return False
    return bool(str(artifact_policy.get("artifact_target") or artifact_policy.get("output_path") or "").strip())


def _artifact_policy_target_paths(policy: dict[str, Any]) -> list[str]:
    artifact_policy = dict(policy or {})
    targets: list[str] = []
    for item in list(artifact_policy.get("artifacts") or []):
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        if path and path not in targets:
            targets.append(path)
    for key in ("artifact_target", "output_path"):
        path = str(artifact_policy.get(key) or "").strip()
        if path and path not in targets:
            targets.append(path)
    return targets


def _unwrap_runtime_event(event: dict[str, Any]) -> dict[str, Any]:
    payload = dict(event or {})
    wrapped_event = payload.get("event")
    if isinstance(wrapped_event, dict) and wrapped_event.get("event_type"):
        return dict(wrapped_event)
    return payload


def _structured_write_paths(payload: dict[str, Any]) -> list[str]:
    envelope = dict(payload.get("result_envelope") or {})
    if str(envelope.get("status") or "ok") != "ok":
        return []
    structured = dict(envelope.get("structured_payload") or payload.get("structured_payload") or {})
    paths: list[str] = []
    paths.extend(str(path or "").strip() for path in list(envelope.get("observed_paths") or []) if str(path or "").strip())
    paths.extend(str(path or "").strip() for path in list(structured.get("observed_paths") or []) if str(path or "").strip())
    for ref in [*list(envelope.get("artifact_refs") or []), *list(structured.get("artifact_refs") or [])]:
        if not isinstance(ref, dict):
            continue
        path = str(ref.get("path") or "").strip()
        if path:
            paths.append(path)
    result: list[str] = []
    seen: set[str] = set()
    for path in paths:
        normalized = path.replace("\\", "/").strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


