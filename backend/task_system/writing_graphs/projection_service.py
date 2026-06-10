from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from task_system.graph_instances.file_service import GraphTaskInstanceFileService
from task_system.graph_instances.models import GraphTaskInstance


ASSET_CATEGORIES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("chapters", "正文", ("chapters/", "chapter/")),
    ("outline", "大纲", ("outline/", "outlines/")),
    ("world", "世界观", ("world/", "worldbuilding/")),
    ("characters", "角色", ("characters/", "character/")),
    ("settings", "设定", ("settings/", "setting/")),
    ("review", "审稿记录", ("review/", "reviews/")),
    ("input", "参考材料", ("input/", "references/", "reference/")),
)

DECISION_ACTIONS: dict[str, dict[str, str]] = {
    "pass": {
        "action": "approve",
        "label": "通过本章",
        "description": "沿当前下游边传播当前章节。",
    },
    "revise": {
        "action": "request_revision",
        "label": "退稿给写手",
        "description": "沿返修或反馈边回传修改意见。",
    },
    "replace": {
        "action": "replace_with_user_text",
        "label": "采用我的改写稿",
        "description": "把用户正文写入正式库，并作为人工产物继续传播。",
    },
}


class WritingGraphDeskProjectionService:
    authority = "task_system.writing_graphs.desk_projection"

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.files = GraphTaskInstanceFileService(self.base_dir)

    def build(
        self,
        *,
        instance: GraphTaskInstance,
        file_tree: dict[str, Any],
        artifacts: dict[str, Any],
        node_sessions: list[dict[str, Any]],
        human_controls: dict[str, Any],
        graph_monitor: dict[str, Any] | None,
        flat_files: list[dict[str, Any]] | None = None,
        include_file_tree: bool = True,
    ) -> dict[str, Any]:
        projected_files = flat_files if flat_files is not None else _flatten_file_tree(dict(file_tree.get("tree") or {}))
        chapter_index = self._chapter_index(instance.graph_task_instance_id, projected_files)
        selected_chapter = self._select_current_chapter(
            chapter_index=chapter_index,
            human_controls=human_controls,
        )
        reader = self._reader(instance.graph_task_instance_id, selected_chapter)
        writing_assets = self._writing_assets(instance.graph_task_instance_id, projected_files)
        chapter_actions = _chapter_actions(human_controls)
        summary = _summary(
            chapter_index=chapter_index,
            chapter_actions=chapter_actions,
            artifacts=artifacts,
            node_sessions=node_sessions,
            graph_monitor=graph_monitor,
        )
        payload = {
            "authority": self.authority,
            "graph_task_instance_id": instance.graph_task_instance_id,
            "instance": instance.to_dict(),
            "chapter_index": chapter_index,
            "current_chapter": selected_chapter or {},
            "reader": reader,
            "writing_assets": writing_assets,
            "chapter_actions": chapter_actions,
            "node_sessions": node_sessions,
            "artifacts": artifacts,
            "human_controls": human_controls,
            "graph_debug_ref": {
                "active_graph_run_id": instance.active_graph_run_id,
                "graph_monitor_available": graph_monitor is not None,
            },
            "summary": summary,
        }
        if include_file_tree:
            payload["file_tree"] = file_tree
        return payload

    def _chapter_index(self, instance_id: str, flat_files: list[dict[str, Any]]) -> list[dict[str, Any]]:
        chapters = []
        for item in flat_files:
            path = _normalize_path(item.get("path"))
            if not path or not _is_chapter_path(path, str(item.get("name") or "")):
                continue
            stat = self._file_stat(instance_id, path)
            chapter_number = _chapter_number(path, str(item.get("name") or ""))
            chapters.append(
                {
                    "authority": "task_system.writing_graphs.chapter_index_item",
                    "chapter_id": f"chapter-{chapter_number:03d}" if chapter_number is not None else _safe_id(path),
                    "title": _chapter_title(path, chapter_number),
                    "path": path,
                    "status": "draft_available",
                    "source": "project_file",
                    "chapter_number": chapter_number,
                    "updated_at": stat.get("updated_at", 0.0),
                    "size": stat.get("size", 0),
                }
            )
        return sorted(chapters, key=_chapter_sort_key)

    def _select_current_chapter(
        self,
        *,
        chapter_index: list[dict[str, Any]],
        human_controls: dict[str, Any],
    ) -> dict[str, Any] | None:
        if not chapter_index:
            return None
        control_paths = _control_chapter_paths(human_controls)
        for path in control_paths:
            match = next((item for item in chapter_index if item.get("path") == path), None)
            if match:
                return {**match, "selection_reason": "human_control"}
        updated = [item for item in chapter_index if float(item.get("updated_at") or 0.0) > 0]
        if updated:
            latest = max(updated, key=lambda item: float(item.get("updated_at") or 0.0))
            return {**latest, "selection_reason": "latest_updated_chapter"}
        return {**chapter_index[-1], "selection_reason": "latest_chapter_number"}

    def _reader(self, instance_id: str, current_chapter: dict[str, Any] | None) -> dict[str, Any]:
        path = str(dict(current_chapter or {}).get("path") or "").strip()
        if not path:
            return {
                "authority": "task_system.writing_graphs.reader_projection",
                "path": "",
                "content": "",
                "content_kind": "empty",
                "empty": True,
            }
        try:
            payload = self.files.read_file(instance_id, path)
            content = str(payload.get("content") or "")
        except (FileNotFoundError, ValueError):
            content = ""
        return {
            "authority": "task_system.writing_graphs.reader_projection",
            "path": path,
            "content": content,
            "content_kind": "chapter",
            "empty": not bool(content.strip()),
        }

    def _writing_assets(self, instance_id: str, flat_files: list[dict[str, Any]]) -> dict[str, Any]:
        groups = {
            category_id: {
                "category_id": category_id,
                "title": title,
                "items": [],
                "summary": {"file_count": 0},
                "authority": "task_system.writing_graphs.asset_category",
            }
            for category_id, title, _prefixes in ASSET_CATEGORIES
        }
        groups["other"] = {
            "category_id": "other",
            "title": "其他文件",
            "items": [],
            "summary": {"file_count": 0},
            "authority": "task_system.writing_graphs.asset_category",
        }
        for item in flat_files:
            path = _normalize_path(item.get("path"))
            if not path:
                continue
            category_id = _asset_category(path)
            stat = self._file_stat(instance_id, path)
            asset = {
                "path": path,
                "name": str(item.get("name") or Path(path).name),
                "kind": str(item.get("kind") or "file"),
                "updated_at": stat.get("updated_at", 0.0),
                "size": stat.get("size", 0),
                "authority": "task_system.writing_graphs.asset_item",
            }
            groups[category_id]["items"].append(asset)
        for group in groups.values():
            group["items"] = sorted(group["items"], key=lambda asset: str(asset.get("path") or ""))
            group["summary"] = {"file_count": len(group["items"])}
        return {
            "authority": "task_system.writing_graphs.asset_projection",
            "categories": list(groups.values()),
            "summary": {"file_count": sum(len(group["items"]) for group in groups.values())},
        }

    def _file_stat(self, instance_id: str, path: str) -> dict[str, Any]:
        target = (self.files.root(instance_id) / path).resolve()
        try:
            stat = target.stat()
        except OSError:
            return {"updated_at": 0.0, "size": 0}
        return {"updated_at": stat.st_mtime, "size": stat.st_size}


def _flatten_file_tree(node: dict[str, Any]) -> list[dict[str, Any]]:
    if not node:
        return []
    children = list(node.get("children") or [])
    current = [node] if str(node.get("kind") or "") == "file" else []
    for child in children:
        if isinstance(child, dict):
            current.extend(_flatten_file_tree(child))
    return current


def _normalize_path(value: Any) -> str:
    return str(value or "").replace("\\", "/").strip().strip("/")


def _is_chapter_path(path: str, name: str) -> bool:
    lower = path.lower()
    return (
        lower.startswith("chapters/")
        or "/chapters/" in lower
        or re.search(r"(?:^|/|[_\-. ])chapter[_\-. ]?\d+", lower) is not None
        or re.search(r"第.+章", name) is not None
    )


def _chapter_number(path: str, name: str) -> int | None:
    for value in (path, name):
        match = re.search(r"chapter[_\-. ]?(\d+)", value, re.IGNORECASE)
        if match:
            return int(match.group(1))
        zh_match = re.search(r"第\s*(\d+)\s*章", value)
        if zh_match:
            return int(zh_match.group(1))
    return None


def _chapter_title(path: str, chapter_number: int | None) -> str:
    if chapter_number is not None:
        return f"第 {chapter_number} 章"
    return Path(path).name or path


def _chapter_sort_key(item: dict[str, Any]) -> tuple[int, str]:
    number = item.get("chapter_number")
    if isinstance(number, int):
        return (number, str(item.get("path") or ""))
    return (10_000_000, str(item.get("path") or ""))


def _asset_category(path: str) -> str:
    lower = path.lower()
    for category_id, _title, prefixes in ASSET_CATEGORIES:
        if any(lower.startswith(prefix) for prefix in prefixes):
            return category_id
    return "other"


def _chapter_actions(human_controls: dict[str, Any]) -> list[dict[str, Any]]:
    controls = [
        *(list(human_controls.get("pending") or []) if isinstance(human_controls.get("pending"), list) else []),
        *(list(human_controls.get("available") or []) if isinstance(human_controls.get("available"), list) else []),
    ]
    actions: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for control in controls:
        if not isinstance(control, dict):
            continue
        control_id = str(control.get("control_id") or "").strip()
        for decision in list(control.get("allowed_decisions") or []):
            decision_kind = str(decision or "").strip()
            spec = DECISION_ACTIONS.get(decision_kind)
            if not spec or not control_id:
                continue
            key = (control_id, decision_kind)
            if key in seen:
                continue
            seen.add(key)
            actions.append(
                {
                    "authority": "task_system.writing_graphs.chapter_action",
                    "action": spec["action"],
                    "decision": decision_kind,
                    "label": spec["label"],
                    "description": spec["description"],
                    "enabled": True,
                    "control_id": control_id,
                    "edge_id": str(control.get("edge_id") or ""),
                    "source_node_id": str(control.get("source_node_id") or ""),
                    "target_node_id": str(control.get("target_node_id") or ""),
                    "reason": str(control.get("reason") or ""),
                }
            )
    return actions


def _control_chapter_paths(human_controls: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    controls = [
        *(list(human_controls.get("pending") or []) if isinstance(human_controls.get("pending"), list) else []),
        *(list(human_controls.get("available") or []) if isinstance(human_controls.get("available"), list) else []),
    ]
    for control in controls:
        if not isinstance(control, dict):
            continue
        for ref in list(control.get("artifact_refs") or []):
            if not isinstance(ref, dict):
                continue
            path = _normalize_path(ref.get("path"))
            if path and _is_chapter_path(path, Path(path).name):
                paths.append(path)
    return paths


def _summary(
    *,
    chapter_index: list[dict[str, Any]],
    chapter_actions: list[dict[str, Any]],
    artifacts: dict[str, Any],
    node_sessions: list[dict[str, Any]],
    graph_monitor: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "authority": "task_system.writing_graphs.desk_summary",
        "chapter_count": len(chapter_index),
        "action_count": len(chapter_actions),
        "artifact_count": int(dict(artifacts.get("summary") or {}).get("artifact_count") or 0),
        "node_session_count": len(node_sessions),
        "graph_monitor_available": graph_monitor is not None,
    }


def _safe_id(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in str(value or "").strip())
    return safe.strip("._-") or "chapter"
