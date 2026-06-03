from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from typing import Any

from runtime.tool_runtime.tool_result_envelope import tool_result_envelope_from_payload

from .tool_observation_ledger import build_tool_observation_record


@dataclass(frozen=True, slots=True)
class FileReadRange:
    start_line: int
    end_line: int
    observation_ref: str = ""
    content_sha256: str = ""
    stale: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(asdict(self))


@dataclass(frozen=True, slots=True)
class FileSearchHit:
    query: str
    line: int | None = None
    preview: str = ""
    observation_ref: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(asdict(self))


@dataclass(frozen=True, slots=True)
class FileWriteEvent:
    operation: str
    observation_ref: str = ""
    content_sha256_after: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(asdict(self))


@dataclass(frozen=True, slots=True)
class TaskFileState:
    path: str
    status: str = "unread"
    read_ranges: tuple[FileReadRange, ...] = ()
    search_hits: tuple[FileSearchHit, ...] = ()
    write_events: tuple[FileWriteEvent, ...] = ()
    total_lines: int | None = None
    content_sha256: str = ""
    last_observation_ref: str = ""
    last_tool_call_id: str = ""
    has_more: bool | None = None
    exists: bool | None = None
    authority: str = "runtime.memory.file_state_authority.task_file_state"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["read_ranges"] = [item.to_dict() for item in self.read_ranges]
        payload["search_hits"] = [item.to_dict() for item in self.search_hits]
        payload["write_events"] = [item.to_dict() for item in self.write_events]
        payload["coverage"] = _coverage_payload(self.read_ranges)
        next_read = _next_suggested_read(self)
        if next_read:
            payload["next_suggested_read"] = next_read
        return _drop_empty(payload)


@dataclass(frozen=True, slots=True)
class FileStateAuthority:
    task_run_id: str = ""
    files: tuple[TaskFileState, ...] = ()
    authority: str = "runtime.memory.file_state_authority"

    @classmethod
    def from_observations(
        cls,
        observations: list[dict[str, Any]] | tuple[dict[str, Any], ...],
        *,
        task_run_id: str = "",
    ) -> "FileStateAuthority":
        authority = cls(task_run_id=str(task_run_id or ""))
        for observation in list(observations or []):
            if isinstance(observation, dict):
                authority = authority.apply_observation(observation)
        return authority

    def apply_observation(self, observation: dict[str, Any]) -> "FileStateAuthority":
        source = _source_observation_payload(observation)
        observation_ref = str(source.get("observation_id") or observation.get("observation_id") or source.get("observation_ref") or "")
        payload = dict(source.get("payload") or source)
        envelope = tool_result_envelope_from_payload(payload)
        if envelope is None:
            record = build_tool_observation_record(
                observation_ref=observation_ref,
                tool_name=str(payload.get("tool_name") or source.get("tool_name") or ""),
                tool_args=dict(payload.get("tool_args") or {}),
                result=payload,
            )
            events = _events_from_record(record.to_dict(), observation_ref=observation_ref)
            tool_call_id = str(payload.get("tool_call_id") or "")
        else:
            events = tuple(dict(item) for item in envelope.file_state_events)
            if not events:
                record = build_tool_observation_record(
                    observation_ref=observation_ref,
                    tool_name=envelope.tool_name,
                    tool_args=dict(envelope.tool_args),
                    result={"result_envelope": envelope.to_dict()},
                )
                events = _events_from_record(record.to_dict(), observation_ref=observation_ref)
            tool_call_id = str(envelope.tool_call_id or payload.get("tool_call_id") or "")
        state = self
        for event in events:
            state = state.apply_event(event, observation_ref=observation_ref, tool_call_id=tool_call_id)
        return state

    def apply_event(self, event: dict[str, Any], *, observation_ref: str = "", tool_call_id: str = "") -> "FileStateAuthority":
        path = _normalize_path(event.get("path"))
        if not path:
            return self
        files = list(self.files)
        index = next((idx for idx, item in enumerate(files) if item.path == path), -1)
        current = files[index] if index >= 0 else TaskFileState(path=path)
        updated = _apply_file_event(current, event, observation_ref=observation_ref, tool_call_id=tool_call_id)
        if index >= 0:
            files[index] = updated
        else:
            files.append(updated)
        files = sorted(files, key=lambda item: item.path)
        return replace(self, files=tuple(files))

    def projection(self, *, limit: int = 20) -> list[dict[str, Any]]:
        return [item.to_dict() for item in self.files[-max(1, int(limit or 20)):]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_run_id": self.task_run_id,
            "files": [item.to_dict() for item in self.files],
            "authority": self.authority,
        }


def build_file_state_projection_from_observations(
    observations: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    task_run_id: str = "",
    limit: int = 20,
) -> list[dict[str, Any]]:
    return FileStateAuthority.from_observations(observations, task_run_id=task_run_id).projection(limit=limit)


def _apply_file_event(
    current: TaskFileState,
    event: dict[str, Any],
    *,
    observation_ref: str,
    tool_call_id: str,
) -> TaskFileState:
    event_type = str(event.get("event_type") or event.get("type") or "").strip()
    if event_type == "read":
        start = _int_or_none(event.get("start_line"))
        end = _int_or_none(event.get("end_line"))
        ranges = list(current.read_ranges)
        if start is not None and end is not None:
            candidate = FileReadRange(
                start_line=start,
                end_line=end,
                observation_ref=observation_ref,
                content_sha256=str(event.get("content_sha256") or ""),
                stale=False,
            )
            if not any(item.start_line == candidate.start_line and item.end_line == candidate.end_line and item.stale is False for item in ranges):
                ranges.append(candidate)
        total_lines = _int_or_none(event.get("total_lines"))
        status = "complete"
        has_more = event.get("has_more") if isinstance(event.get("has_more"), bool) else None
        if has_more is True or _has_partial_coverage(tuple(ranges), total_lines):
            status = "partial"
        return replace(
            current,
            status=status,
            read_ranges=tuple(sorted(ranges, key=lambda item: (item.start_line, item.end_line)))[-24:],
            total_lines=total_lines if total_lines is not None else current.total_lines,
            content_sha256=str(event.get("content_sha256") or current.content_sha256 or ""),
            has_more=has_more,
            last_observation_ref=observation_ref,
            last_tool_call_id=tool_call_id,
            exists=True,
        )
    if event_type in {"write", "edit"}:
        stale_ranges = tuple(replace(item, stale=True) for item in current.read_ranges)
        write = FileWriteEvent(
            operation=event_type,
            observation_ref=observation_ref,
            content_sha256_after=str(event.get("content_sha256") or ""),
        )
        return replace(
            current,
            status="stale" if stale_ranges else "changed",
            read_ranges=stale_ranges,
            write_events=(*current.write_events, write)[-12:],
            content_sha256=str(event.get("content_sha256") or current.content_sha256 or ""),
            last_observation_ref=observation_ref,
            last_tool_call_id=tool_call_id,
            exists=True,
        )
    if event_type == "search":
        hits = list(current.search_hits)
        for match in [dict(item) for item in list(event.get("matches") or []) if isinstance(item, dict)]:
            hits.append(
                FileSearchHit(
                    query=str(event.get("query") or ""),
                    line=_int_or_none(match.get("line")),
                    preview=str(match.get("text") or match.get("preview") or "")[:240],
                    observation_ref=observation_ref,
                )
            )
        if not hits:
            hits.append(FileSearchHit(query=str(event.get("query") or ""), observation_ref=observation_ref))
        return replace(
            current,
            status=current.status if current.status not in {"unread", ""} else "matched",
            search_hits=tuple(hits[-24:]),
            last_observation_ref=observation_ref,
            last_tool_call_id=tool_call_id,
        )
    if event_type in {"stat", "exists"}:
        exists = event.get("exists") if isinstance(event.get("exists"), bool) else current.exists
        status = "missing" if exists is False else current.status
        return replace(
            current,
            status=status,
            exists=exists,
            last_observation_ref=observation_ref,
            last_tool_call_id=tool_call_id,
        )
    return current


def _events_from_record(record: dict[str, Any], *, observation_ref: str) -> tuple[dict[str, Any], ...]:
    tool_name = str(record.get("tool_name") or "")
    args = dict(record.get("tool_args") or {})
    events: list[dict[str, Any]] = []
    if tool_name == "read_file":
        content_range = dict(dict(record.get("result_metadata") or {}).get("content_range") or {})
        path = _normalize_path(content_range.get("path") or args.get("path"))
        if path:
            events.append(
                {
                    "event_type": "read",
                    "path": path,
                    "start_line": content_range.get("start_line"),
                    "end_line": content_range.get("end_line"),
                    "returned_lines": content_range.get("returned_lines"),
                    "total_lines": content_range.get("total_lines"),
                    "line_count": content_range.get("line_count"),
                    "next_start_line": content_range.get("next_start_line"),
                    "has_more": content_range.get("has_more"),
                    "content_sha256": content_range.get("content_sha256"),
                }
            )
    elif tool_name in {"write_file", "edit_file"}:
        for path in _paths_from_record(record):
            events.append({"event_type": "write" if tool_name == "write_file" else "edit", "path": path})
    elif tool_name == "search_text":
        for path in _paths_from_record(record, key="matched_paths"):
            events.append({"event_type": "search", "path": path, "query": str(args.get("query") or ""), "matches": []})
    elif tool_name in {"stat_path", "path_exists"}:
        for path in _paths_from_record(record):
            events.append({"event_type": "stat" if tool_name == "stat_path" else "exists", "path": path})
    return tuple(_drop_empty({**event, "observation_ref": observation_ref}) for event in events)


def _paths_from_record(record: dict[str, Any], *, key: str = "observed_paths") -> list[str]:
    paths = [_normalize_path(item) for item in list(record.get(key) or []) if _normalize_path(item)]
    for ref in [dict(item) for item in list(record.get("artifact_refs") or []) if isinstance(item, dict)]:
        path = _normalize_path(ref.get("path") or ref.get("artifact_ref"))
        if path:
            paths.append(path)
    return sorted(set(paths))


def _coverage_payload(ranges: tuple[FileReadRange, ...]) -> dict[str, Any]:
    active = [item for item in ranges if item.stale is False]
    if not active:
        return {}
    start = min(item.start_line for item in active)
    end = max(item.end_line for item in active)
    return {"start_line": start, "end_line": end, "range_count": len(active)}


def _next_suggested_read(state: TaskFileState) -> dict[str, Any]:
    if state.status not in {"partial", "stale"}:
        return {}
    active = [item for item in state.read_ranges if item.stale is False]
    if not active:
        return {"start_line": 1, "line_count": 240, "reason": "file state is stale or unread"}
    end = max(item.end_line for item in active)
    if state.total_lines and end >= state.total_lines:
        return {}
    return {"start_line": end + 1, "line_count": 240, "reason": "continue from last read window"}


def _has_partial_coverage(ranges: tuple[FileReadRange, ...], total_lines: int | None) -> bool:
    if total_lines is None:
        return True
    active = [item for item in ranges if item.stale is False]
    if not active:
        return True
    return min(item.start_line for item in active) > 1 or max(item.end_line for item in active) < total_lines


def _source_observation_payload(observation: dict[str, Any]) -> dict[str, Any]:
    item = dict(observation or {})
    wrapped = dict(item.get("observation") or {})
    return wrapped if wrapped else item


def _normalize_path(path: Any) -> str:
    return str(path or "").replace("\\", "/").strip().strip("/")


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {}, ())}
