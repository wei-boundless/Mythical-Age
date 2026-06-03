from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ToolResourceLock:
    resource_key: str
    mode: str = "read"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ToolConcurrencyDescriptor:
    tool_name: str
    operation_id: str
    read_only: bool = False
    destructive: bool = False
    concurrency_safe: bool = False
    operation_type: str = ""
    resource_locks: tuple[ToolResourceLock, ...] = ()
    execution_class: str = "exclusive"
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["resource_locks"] = [item.to_dict() for item in self.resource_locks]
        return payload


@dataclass(frozen=True, slots=True)
class ToolBatchItem:
    item_index: int
    action_request: Any
    tool_call: dict[str, Any]
    admission: Any
    action_permit: dict[str, Any]
    concurrency_descriptor: ToolConcurrencyDescriptor
    execution_class: str

    def to_dict(self) -> dict[str, Any]:
        action_request = self.action_request
        admission = self.admission
        return {
            "item_index": self.item_index,
            "action_request_ref": str(getattr(action_request, "request_id", "") or ""),
            "tool_call": dict(self.tool_call or {}),
            "tool_name": str(self.tool_call.get("tool_name") or self.tool_call.get("name") or ""),
            "operation_id": self.concurrency_descriptor.operation_id,
            "admission": admission.to_dict() if hasattr(admission, "to_dict") else dict(admission or {}),
            "action_permit": dict(self.action_permit or {}),
            "concurrency_descriptor": self.concurrency_descriptor.to_dict(),
            "execution_class": self.execution_class,
        }


@dataclass(frozen=True, slots=True)
class ToolBatchGroup:
    group_index: int
    execution_class: str
    item_indexes: tuple[int, ...]
    parallel: bool = False
    resource_locks: tuple[ToolResourceLock, ...] = ()
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "group_index": self.group_index,
            "execution_class": self.execution_class,
            "item_indexes": list(self.item_indexes),
            "parallel": self.parallel,
            "resource_locks": [item.to_dict() for item in self.resource_locks],
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class ToolBatchPlan:
    batch_id: str
    items: tuple[ToolBatchItem, ...] = ()
    groups: tuple[ToolBatchGroup, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "harness.runtime.tool_batch_planner"

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "items": [item.to_dict() for item in self.items],
            "groups": [group.to_dict() for group in self.groups],
            "diagnostics": dict(self.diagnostics or {}),
            "authority": self.authority,
        }


def build_tool_batch_plan(
    *,
    turn_id: str,
    packet_ref: str,
    invocation_rows: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    tool_plan: Any,
    definitions_by_name: dict[str, Any] | None = None,
    workspace_root: str | Path | None = None,
) -> ToolBatchPlan:
    definitions = dict(definitions_by_name or {})
    rows = [dict(item) for item in list(invocation_rows or []) if isinstance(item, dict)]
    items: list[ToolBatchItem] = []
    for index, row in enumerate(rows):
        tool_call = dict(row.get("tool_call") or {})
        action_request = row.get("action_request")
        admission = row.get("admission")
        action_permit = dict(row.get("action_permit") or {})
        descriptor = build_tool_concurrency_descriptor(
            tool_call=tool_call,
            action_request=action_request,
            admission=admission,
            action_permit=action_permit,
            tool_plan=tool_plan,
            definitions_by_name=definitions,
            workspace_root=workspace_root,
        )
        items.append(
            ToolBatchItem(
                item_index=index,
                action_request=action_request,
                tool_call=tool_call,
                admission=admission,
                action_permit=action_permit,
                concurrency_descriptor=descriptor,
                execution_class=descriptor.execution_class,
            )
        )
    groups = group_tool_batch_items(items)
    seed = {
        "turn_id": str(turn_id or ""),
        "packet_ref": str(packet_ref or ""),
        "items": [
            {
                "index": item.item_index,
                "request_ref": str(getattr(item.action_request, "request_id", "") or ""),
                "tool_name": item.concurrency_descriptor.tool_name,
                "operation_id": item.concurrency_descriptor.operation_id,
                "execution_class": item.execution_class,
                "locks": [lock.to_dict() for lock in item.concurrency_descriptor.resource_locks],
            }
            for item in items
        ],
    }
    batch_hash = hashlib.sha256(json.dumps(seed, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return ToolBatchPlan(
        batch_id=f"toolbatch:{turn_id or 'turn'}:{batch_hash}",
        items=tuple(items),
        groups=tuple(groups),
        diagnostics={
            "turn_id": str(turn_id or ""),
            "packet_ref": str(packet_ref or ""),
            "item_count": len(items),
            "group_count": len(groups),
            "parallel_group_count": sum(1 for group in groups if group.parallel),
            "exclusive_group_count": sum(1 for group in groups if group.execution_class == "exclusive"),
            "approval_blocked_count": sum(1 for item in items if item.execution_class == "approval_blocked"),
            "non_executable_count": sum(1 for item in items if item.execution_class in {"approval_blocked", "denied_or_error"}),
        },
    )


def build_tool_concurrency_descriptor(
    *,
    tool_call: dict[str, Any],
    action_request: Any,
    admission: Any,
    action_permit: dict[str, Any],
    tool_plan: Any,
    definitions_by_name: dict[str, Any] | None = None,
    workspace_root: str | Path | None = None,
) -> ToolConcurrencyDescriptor:
    tool_name = str(tool_call.get("tool_name") or tool_call.get("name") or "").strip()
    operation_id = _operation_id_for_tool(
        tool_name,
        action_permit=action_permit,
        tool_plan=tool_plan,
        definitions_by_name=dict(definitions_by_name or {}),
    )
    operation_payload = _operation_payload(tool_plan=tool_plan, operation_id=operation_id, tool_name=tool_name)
    read_only = bool(operation_payload.get("read_only") is True)
    destructive = bool(operation_payload.get("destructive") is True)
    concurrency_safe = bool(operation_payload.get("concurrency_safe") is True)
    operation_type = str(operation_payload.get("operation_type") or "").strip()
    admission_decision = str(getattr(admission, "decision", "") or dict(getattr(admission, "to_dict", lambda: {})()).get("decision") or "").strip()
    if admission_decision == "ask_approval":
        execution_class = "approval_blocked"
        reason = "admission_requires_approval"
    elif admission_decision != "allow":
        execution_class = "denied_or_error"
        reason = f"admission_{admission_decision or 'not_allowed'}"
    elif concurrency_safe and read_only:
        execution_class = "parallel_read"
        reason = "read_only_concurrency_safe"
    elif concurrency_safe and not destructive and bool(operation_payload.get("parallel_safe") is True):
        execution_class = "parallel_safe"
        reason = "explicit_parallel_safe"
    else:
        execution_class = "exclusive"
        if not concurrency_safe:
            reason = "operation_not_concurrency_safe"
        elif not read_only:
            reason = "side_effect_operation_requires_exclusive_group"
        else:
            reason = "operation_requires_exclusive_group"
    locks = derive_resource_locks(
        tool_name=tool_name,
        operation_id=operation_id,
        operation_type=operation_type,
        tool_args=_tool_args(tool_call=tool_call, action_request=action_request),
        read_only=read_only,
        execution_class=execution_class,
        workspace_root=workspace_root,
    )
    return ToolConcurrencyDescriptor(
        tool_name=tool_name,
        operation_id=operation_id,
        read_only=read_only,
        destructive=destructive,
        concurrency_safe=concurrency_safe,
        operation_type=operation_type,
        resource_locks=tuple(locks),
        execution_class=execution_class,
        reason=reason,
    )


def derive_resource_locks(
    *,
    tool_name: str,
    operation_id: str,
    operation_type: str,
    tool_args: dict[str, Any],
    read_only: bool,
    execution_class: str,
    workspace_root: str | Path | None = None,
) -> tuple[ToolResourceLock, ...]:
    if execution_class in {"approval_blocked", "denied_or_error"}:
        return ()
    mode = "read" if read_only else "write"
    resource_key = _resource_key(
        tool_name=tool_name,
        operation_id=operation_id,
        operation_type=operation_type,
        tool_args=tool_args,
        workspace_root=workspace_root,
        mode=mode,
    )
    return (ToolResourceLock(resource_key=resource_key, mode=mode),)


def group_tool_batch_items(items: list[ToolBatchItem] | tuple[ToolBatchItem, ...]) -> tuple[ToolBatchGroup, ...]:
    groups: list[ToolBatchGroup] = []
    pending_parallel: list[ToolBatchItem] = []

    def flush_parallel() -> None:
        nonlocal pending_parallel
        if not pending_parallel:
            return
        group = _parallel_group(len(groups), pending_parallel)
        groups.append(group)
        pending_parallel = []

    for item in list(items or []):
        if item.execution_class in {"approval_blocked", "denied_or_error"}:
            continue
        if item.execution_class in {"parallel_read", "parallel_safe"}:
            if _conflicts_with_any(item.concurrency_descriptor.resource_locks, pending_parallel):
                flush_parallel()
            pending_parallel.append(item)
            continue
        flush_parallel()
        groups.append(_exclusive_group(len(groups), item))
    flush_parallel()
    return tuple(groups)


def _parallel_group(group_index: int, items: list[ToolBatchItem]) -> ToolBatchGroup:
    locks = _dedupe_locks(lock for item in items for lock in item.concurrency_descriptor.resource_locks)
    execution_class = "parallel_safe" if any(item.execution_class == "parallel_safe" for item in items) else "parallel_read"
    return ToolBatchGroup(
        group_index=group_index,
        execution_class=execution_class,
        item_indexes=tuple(item.item_index for item in items),
        parallel=len(items) > 1,
        resource_locks=locks,
        reason="compatible_parallel_group" if len(items) > 1 else "single_parallel_eligible_item",
    )


def _exclusive_group(group_index: int, item: ToolBatchItem) -> ToolBatchGroup:
    return ToolBatchGroup(
        group_index=group_index,
        execution_class="exclusive",
        item_indexes=(item.item_index,),
        parallel=False,
        resource_locks=tuple(item.concurrency_descriptor.resource_locks),
        reason=item.concurrency_descriptor.reason or "exclusive_operation",
    )


def _conflicts_with_any(locks: tuple[ToolResourceLock, ...], pending_items: list[ToolBatchItem]) -> bool:
    pending_locks = [lock for item in pending_items for lock in item.concurrency_descriptor.resource_locks]
    return any(_locks_conflict(lock, existing) for lock in locks for existing in pending_locks)


def _locks_conflict(left: ToolResourceLock, right: ToolResourceLock) -> bool:
    if left.resource_key != right.resource_key:
        return False
    return left.mode != "read" or right.mode != "read"


def _dedupe_locks(locks: Any) -> tuple[ToolResourceLock, ...]:
    result: list[ToolResourceLock] = []
    seen: set[tuple[str, str]] = set()
    for lock in locks:
        if not isinstance(lock, ToolResourceLock):
            continue
        key = (lock.resource_key, lock.mode)
        if key in seen:
            continue
        seen.add(key)
        result.append(lock)
    return tuple(result)


def _operation_id_for_tool(
    tool_name: str,
    *,
    action_permit: dict[str, Any],
    tool_plan: Any,
    definitions_by_name: dict[str, Any],
) -> str:
    operation_id = str(action_permit.get("operation_id") or "").strip()
    if operation_id:
        return operation_id
    definition = definitions_by_name.get(str(tool_name or "").strip())
    operation_id = str(getattr(definition, "operation_id", "") or "").strip()
    if operation_id:
        return operation_id
    for item in list(getattr(tool_plan, "model_visible_tools", ()) or ()):
        if not isinstance(item, dict):
            continue
        name = str(item.get("tool_name") or item.get("name") or "").strip()
        if name == tool_name:
            return str(item.get("operation_id") or tool_name).strip()
    return tool_name


def _operation_payload(*, tool_plan: Any, operation_id: str, tool_name: str) -> dict[str, Any]:
    table = getattr(tool_plan, "capability_table", None)
    capability = table.capability_for_operation(operation_id) if table is not None and hasattr(table, "capability_for_operation") else None
    metadata = dict(getattr(capability, "metadata", {}) or {}) if capability is not None else {}
    tool_view = dict(metadata.get("tool_view") or {})
    payload = {
        "operation_id": operation_id,
        "tool_name": tool_name,
        "read_only": bool(metadata.get("read_only") is True or tool_view.get("read_only") is True),
        "destructive": bool(metadata.get("destructive") is True or tool_view.get("destructive") is True),
        "concurrency_safe": bool(metadata.get("concurrency_safe") is True or tool_view.get("concurrency_safe") is True),
        "operation_type": str(metadata.get("operation_type") or tool_view.get("operation_type") or ""),
    }
    return payload


def _tool_args(*, tool_call: dict[str, Any], action_request: Any) -> dict[str, Any]:
    args = tool_call.get("args") or tool_call.get("tool_args") or {}
    if isinstance(args, dict):
        return dict(args)
    raw = getattr(action_request, "tool_call", {}) if action_request is not None else {}
    if isinstance(raw, dict):
        candidate = raw.get("args") or raw.get("tool_args") or {}
        if isinstance(candidate, dict):
            return dict(candidate)
    return {}


def _resource_key(
    *,
    tool_name: str,
    operation_id: str,
    operation_type: str,
    tool_args: dict[str, Any],
    workspace_root: str | Path | None,
    mode: str,
) -> str:
    op = str(operation_id or "").strip()
    kind = str(operation_type or "").strip()
    if op.startswith("op.git_") or kind == "vcs":
        return f"git:index:{_canonical_root(workspace_root)}"
    if op in {"op.shell", "op.python_repl"} or kind == "shell":
        cwd = str(tool_args.get("cwd") or tool_args.get("working_dir") or "")
        return f"shell:{_canonical_path(cwd, workspace_root=workspace_root) if cwd else _canonical_root(workspace_root)}"
    if op == "op.browser_control" or kind == "browser":
        session_id = str(tool_args.get("session_id") or tool_args.get("browser_session_id") or "default").strip() or "default"
        return f"browser:{session_id}"
    if op.startswith("op.subagent_") or kind in {"agent", "session"}:
        run_ref = str(tool_args.get("subagent_run_ref") or tool_args.get("target_agent_id") or tool_args.get("agent_id") or "session").strip()
        return f"agent:{run_ref or 'session'}"
    if kind == "memory" or op.startswith("op.memory_"):
        scope = str(tool_args.get("scope") or tool_args.get("memory_scope") or "default").strip() or "default"
        return f"memory:{scope}"
    if kind in {"filesystem", "code_intelligence"} or op in {
        "op.read_file",
        "op.write_file",
        "op.edit_file",
        "op.path_exists",
        "op.stat_path",
        "op.list_dir",
        "op.glob_paths",
        "op.search_files",
        "op.search_text",
    }:
        paths = _filesystem_arg_paths(tool_args)
        if paths:
            path = paths[0]
            scope = "file" if mode == "read" and op not in {"op.list_dir", "op.glob_paths", "op.search_files", "op.search_text"} else "tree"
            if op in {"op.write_file", "op.edit_file"}:
                scope = "file"
            return f"workspace:{scope}:{_canonical_path(path, workspace_root=workspace_root)}"
        return f"workspace:tree:{_canonical_root(workspace_root)}"
    if op == "op.image_generate":
        target = str(tool_args.get("target_id") or tool_args.get("asset_kind") or "default").strip() or "default"
        return f"asset:image:{target}"
    return f"unknown:{op or tool_name or 'tool'}"


def _filesystem_arg_paths(tool_args: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for key in ("path", "file_path", "target_path", "cwd", "root"):
        value = str(tool_args.get(key) or "").strip()
        if value:
            result.append(value)
    for key in ("paths", "roots"):
        value = tool_args.get(key)
        if isinstance(value, str) and value.strip():
            result.append(value.strip())
        elif isinstance(value, (list, tuple)):
            result.extend(str(item).strip() for item in value if str(item).strip())
    return result


def _canonical_path(path: str, *, workspace_root: str | Path | None) -> str:
    text = str(path or "").strip()
    root = Path(str(workspace_root or ".")).resolve()
    candidate = Path(text)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = candidate.resolve(strict=False)
    except Exception:
        resolved = candidate.absolute()
    return os.path.normcase(str(resolved))


def _canonical_root(workspace_root: str | Path | None) -> str:
    try:
        return os.path.normcase(str(Path(str(workspace_root or ".")).resolve()))
    except Exception:
        return os.path.normcase(str(workspace_root or "."))
