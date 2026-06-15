from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from typing import Any

from runtime.tool_runtime.tool_result_envelope import tool_result_envelope_from_payload


@dataclass(frozen=True, slots=True)
class FileReadRange:
    start_line: int
    end_line: int
    observation_ref: str = ""
    content_sha256: str = ""
    mtime_ns: int | None = None
    read_intent: str = ""
    file_unchanged: bool = False
    content_omitted: bool = False
    previous_observation_ref: str = ""
    reusable_result_ref: str = ""
    exact_artifact_ref: str = ""
    artifact_ref_status: str = ""
    visible_exact: bool = False
    text_sha256: str = ""
    next_start_line: int | None = None
    has_more: bool | None = None
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
class FileStateObservationEvents:
    observation_ref: str = ""
    tool_call_id: str = ""
    events: tuple[dict[str, Any], ...] = ()
    authority: str = "runtime.memory.file_state_authority.observation_events"

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(
            {
                "observation_ref": self.observation_ref,
                "tool_call_id": self.tool_call_id,
                "events": [dict(item) for item in self.events],
                "event_count": len(self.events),
                "authority": self.authority,
            }
        )


@dataclass(frozen=True, slots=True)
class TaskFileState:
    path: str
    status: str = "unread"
    read_ranges: tuple[FileReadRange, ...] = ()
    search_hits: tuple[FileSearchHit, ...] = ()
    write_events: tuple[FileWriteEvent, ...] = ()
    total_lines: int | None = None
    content_sha256: str = ""
    mtime_ns: int | None = None
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
        payload["coverage"] = _coverage_payload(self.read_ranges, total_lines=self.total_lines)
        exact_coverage = _coverage_payload(tuple(_active_exact_read_ranges(self.read_ranges)), total_lines=self.total_lines)
        if exact_coverage:
            payload["exact_coverage"] = exact_coverage
        next_read = _next_suggested_read(self)
        if next_read:
            payload["next_suggested_read"] = next_read
        return _drop_empty(payload)


@dataclass(frozen=True, slots=True)
class FileStateAuthority:
    task_run_id: str = ""
    scope_kind: str = ""
    scope_id: str = ""
    session_id: str = ""
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

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "FileStateAuthority":
        item = dict(payload or {})
        files: list[TaskFileState] = []
        for raw in list(item.get("files") or []):
            if not isinstance(raw, dict):
                continue
            parsed = _task_file_state_from_dict(raw)
            if parsed is not None:
                files.append(parsed)
        return cls(
            task_run_id=str(item.get("task_run_id") or ""),
            scope_kind=str(item.get("scope_kind") or ""),
            scope_id=str(item.get("scope_id") or ""),
            session_id=str(item.get("session_id") or ""),
            files=tuple(files),
        )

    def apply_observation(self, observation: dict[str, Any]) -> "FileStateAuthority":
        extracted = file_state_events_from_observation(observation)
        state = self
        for event in extracted.events:
            state = state.apply_event(
                event,
                observation_ref=extracted.observation_ref,
                tool_call_id=extracted.tool_call_id,
            )
        return state

    def apply_event(self, event: dict[str, Any], *, observation_ref: str = "", tool_call_id: str = "") -> "FileStateAuthority":
        path = _normalize_path(event.get("path"))
        if not path:
            return self
        resolved_observation_ref = str(observation_ref or event.get("observation_ref") or "")
        resolved_tool_call_id = str(tool_call_id or event.get("tool_call_id") or "")
        files = list(self.files)
        index = next((idx for idx, item in enumerate(files) if item.path == path), -1)
        current = files[index] if index >= 0 else TaskFileState(path=path)
        updated = _apply_file_event(
            current,
            event,
            observation_ref=resolved_observation_ref,
            tool_call_id=resolved_tool_call_id,
        )
        if index >= 0:
            files.pop(index)
        files.append(updated)
        return replace(self, files=tuple(files))

    def projection(self, *, limit: int = 20) -> list[dict[str, Any]]:
        return [item.to_dict() for item in self.files[-max(1, int(limit or 20)):]]

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(
            {
                "task_run_id": self.task_run_id,
                "scope_kind": self.scope_kind,
                "scope_id": self.scope_id,
                "session_id": self.session_id,
                "files": [item.to_dict() for item in self.files],
                "authority": self.authority,
            }
        )


def file_state_events_from_observation(observation: dict[str, Any]) -> FileStateObservationEvents:
    source = _source_observation_payload(observation)
    observation_ref = str(source.get("observation_id") or observation.get("observation_id") or source.get("observation_ref") or "")
    payload = dict(source.get("payload") or source)
    envelope = tool_result_envelope_from_payload(payload)
    events: tuple[dict[str, Any], ...] = ()
    if envelope is None:
        tool_call_id = str(payload.get("tool_call_id") or "")
    else:
        events = tuple(dict(item) for item in envelope.file_state_events)
        tool_call_id = str(envelope.tool_call_id or payload.get("tool_call_id") or "")
    return FileStateObservationEvents(
        observation_ref=observation_ref,
        tool_call_id=tool_call_id,
        events=tuple(dict(item) for item in events),
    )


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
        total_lines = _int_or_none(event.get("total_lines"))
        ranges = list(current.read_ranges)
        if start is not None and end is not None and (end >= start or (total_lines == 0 and start == 1 and end == 0)):
            candidate = FileReadRange(
                start_line=start,
                end_line=end,
                observation_ref=observation_ref,
                content_sha256=str(event.get("content_sha256") or ""),
                mtime_ns=_int_or_none(event.get("mtime_ns")),
                read_intent=str(event.get("read_intent") or ""),
                file_unchanged=bool(event.get("file_unchanged") is True),
                content_omitted=bool(event.get("content_omitted") is True),
                previous_observation_ref=str(event.get("previous_observation_ref") or ""),
                reusable_result_ref=str(event.get("reusable_result_ref") or ""),
                exact_artifact_ref=str(event.get("exact_artifact_ref") or ""),
                artifact_ref_status=str(event.get("artifact_ref_status") or ""),
                visible_exact=bool(event.get("visible_exact") is True),
                text_sha256=str(event.get("text_sha256") or ""),
                next_start_line=_int_or_none(event.get("next_start_line")),
                has_more=event.get("has_more") if isinstance(event.get("has_more"), bool) else None,
                stale=False,
            )
            if not any(item.start_line == candidate.start_line and item.end_line == candidate.end_line and item.stale is False for item in ranges):
                ranges.append(candidate)
        if total_lines is None:
            total_lines = current.total_lines
        latest_has_more = event.get("has_more") if isinstance(event.get("has_more"), bool) else None
        ordered_ranges = tuple(sorted(ranges, key=lambda item: (item.start_line, item.end_line)))
        aggregate_complete = _has_complete_coverage(ordered_ranges, total_lines) or (
            total_lines == 0 and latest_has_more is False
        )
        if aggregate_complete:
            status = "complete"
            has_more = False
        else:
            status = "partial"
            has_more = True if total_lines is not None else latest_has_more
        return replace(
            current,
            status=status,
            read_ranges=ordered_ranges,
            total_lines=total_lines,
            content_sha256=str(event.get("content_sha256") or current.content_sha256 or ""),
            mtime_ns=_int_or_none(event.get("mtime_ns")) if _int_or_none(event.get("mtime_ns")) is not None else current.mtime_ns,
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
            mtime_ns=_int_or_none(event.get("mtime_ns")) if _int_or_none(event.get("mtime_ns")) is not None else current.mtime_ns,
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


def _task_file_state_from_dict(payload: dict[str, Any]) -> TaskFileState | None:
    path = _normalize_path(payload.get("path"))
    if not path:
        return None
    return TaskFileState(
        path=path,
        status=str(payload.get("status") or "unread"),
        read_ranges=tuple(
            item
            for item in (_file_read_range_from_dict(raw) for raw in list(payload.get("read_ranges") or []))
            if item is not None
        ),
        search_hits=tuple(
            item
            for item in (_file_search_hit_from_dict(raw) for raw in list(payload.get("search_hits") or []))
            if item is not None
        ),
        write_events=tuple(
            item
            for item in (_file_write_event_from_dict(raw) for raw in list(payload.get("write_events") or []))
            if item is not None
        ),
        total_lines=_int_or_none(payload.get("total_lines")),
        content_sha256=str(payload.get("content_sha256") or ""),
        mtime_ns=_int_or_none(payload.get("mtime_ns")),
        last_observation_ref=str(payload.get("last_observation_ref") or ""),
        last_tool_call_id=str(payload.get("last_tool_call_id") or ""),
        has_more=_bool_or_none(payload.get("has_more")),
        exists=_bool_or_none(payload.get("exists")),
    )


def _file_read_range_from_dict(payload: Any) -> FileReadRange | None:
    if not isinstance(payload, dict):
        return None
    start_line = _int_or_none(payload.get("start_line"))
    end_line = _int_or_none(payload.get("end_line"))
    if start_line is None or end_line is None:
        return None
    return FileReadRange(
        start_line=start_line,
        end_line=end_line,
        observation_ref=str(payload.get("observation_ref") or ""),
        content_sha256=str(payload.get("content_sha256") or ""),
        mtime_ns=_int_or_none(payload.get("mtime_ns")),
        read_intent=str(payload.get("read_intent") or ""),
        file_unchanged=bool(payload.get("file_unchanged") is True),
        content_omitted=bool(payload.get("content_omitted") is True),
        previous_observation_ref=str(payload.get("previous_observation_ref") or ""),
        reusable_result_ref=str(payload.get("reusable_result_ref") or ""),
        exact_artifact_ref=str(payload.get("exact_artifact_ref") or ""),
        artifact_ref_status=str(payload.get("artifact_ref_status") or ""),
        visible_exact=bool(payload.get("visible_exact") is True),
        text_sha256=str(payload.get("text_sha256") or ""),
        next_start_line=_int_or_none(payload.get("next_start_line")),
        has_more=_bool_or_none(payload.get("has_more")),
        stale=bool(payload.get("stale") is True),
    )


def _file_search_hit_from_dict(payload: Any) -> FileSearchHit | None:
    if not isinstance(payload, dict):
        return None
    return FileSearchHit(
        query=str(payload.get("query") or ""),
        line=_int_or_none(payload.get("line")),
        preview=str(payload.get("preview") or ""),
        observation_ref=str(payload.get("observation_ref") or ""),
    )


def _file_write_event_from_dict(payload: Any) -> FileWriteEvent | None:
    if not isinstance(payload, dict):
        return None
    operation = str(payload.get("operation") or "").strip()
    if not operation:
        return None
    return FileWriteEvent(
        operation=operation,
        observation_ref=str(payload.get("observation_ref") or ""),
        content_sha256_after=str(payload.get("content_sha256_after") or ""),
    )


def _coverage_payload(ranges: tuple[FileReadRange, ...], *, total_lines: int | None = None) -> dict[str, Any]:
    active = _active_read_ranges(ranges)
    if total_lines == 0 and not active:
        return {
            "range_count": 0,
            "covered_lines": 0,
            "total_lines": 0,
            "complete": True,
            "missing_ranges": [],
        }
    if not active:
        return {}
    merged = _merged_read_ranges(active)
    if not merged and total_lines == 0:
        return {
            "range_count": len(active),
            "covered_lines": 0,
            "total_lines": 0,
            "complete": True,
            "missing_ranges": [],
        }
    if not merged:
        return {}
    start = merged[0]["start_line"]
    end = merged[-1]["end_line"]
    covered_lines = sum(int(item["end_line"]) - int(item["start_line"]) + 1 for item in merged)
    complete = _merged_ranges_cover_total(merged, total_lines)
    return _drop_empty(
        {
            "start_line": start,
            "end_line": end,
            "range_count": len(active),
            "merged_ranges": merged,
            "covered_lines": covered_lines,
            "total_lines": total_lines,
            "complete": complete if total_lines is not None else None,
            "missing_ranges": _missing_ranges(merged, total_lines),
        }
    )


def _next_suggested_read(state: TaskFileState) -> dict[str, Any]:
    if state.status not in {"partial", "stale"}:
        return {}
    active = _active_read_ranges(state.read_ranges)
    if not active:
        return {"start_line": 1, "line_count": 240, "reason": "file state is stale or unread"}
    merged = _merged_read_ranges(active)
    missing = _missing_ranges(merged, state.total_lines)
    latest = _latest_active_read_range(state, active)
    if latest is not None and latest.has_more is True and latest.next_start_line is not None:
        return {
            "start_line": latest.next_start_line,
            "line_count": 240,
            "reason": "continue from latest read window",
        }
    if missing:
        first = missing[0]
        end_line = first.get("end_line")
        line_count = 240
        if isinstance(end_line, int):
            line_count = max(1, min(240, end_line - int(first["start_line"]) + 1))
        return {
            "start_line": first["start_line"],
            "line_count": line_count,
            "reason": "fill first unread gap",
        }
    end = max(int(item["end_line"]) for item in merged)
    if state.total_lines and end >= state.total_lines:
        return {}
    return {"start_line": end + 1, "line_count": 240, "reason": "continue from last read window"}


def _latest_active_read_range(state: TaskFileState, active: list[FileReadRange]) -> FileReadRange | None:
    last_ref = str(state.last_observation_ref or "")
    if last_ref:
        for item in reversed(active):
            if str(item.observation_ref or "") == last_ref:
                return item
    return active[-1] if active else None


def _has_complete_coverage(ranges: tuple[FileReadRange, ...], total_lines: int | None) -> bool:
    return _merged_ranges_cover_total(_merged_read_ranges(_active_read_ranges(ranges)), total_lines)


def _active_read_ranges(ranges: tuple[FileReadRange, ...]) -> list[FileReadRange]:
    return sorted(
        [item for item in ranges if item.stale is False and item.start_line >= 1 and item.end_line >= item.start_line],
        key=lambda item: (item.start_line, item.end_line),
    )


def _active_exact_read_ranges(ranges: tuple[FileReadRange, ...]) -> list[FileReadRange]:
    return sorted(
        [
            item
            for item in ranges
            if item.stale is False
            and (
                (item.start_line >= 1 and item.end_line >= item.start_line)
                or (item.start_line == 1 and item.end_line == 0)
            )
            and (item.visible_exact or (item.exact_artifact_ref and item.artifact_ref_status == "exact"))
            and not (item.content_omitted and not item.exact_artifact_ref)
        ],
        key=lambda item: (item.start_line, item.end_line),
    )


def _merged_read_ranges(ranges: list[FileReadRange]) -> list[dict[str, int]]:
    merged: list[dict[str, int]] = []
    for item in ranges:
        start = int(item.start_line)
        end = int(item.end_line)
        if end < start:
            continue
        if not merged or start > int(merged[-1]["end_line"]) + 1:
            merged.append({"start_line": start, "end_line": end})
            continue
        merged[-1]["end_line"] = max(int(merged[-1]["end_line"]), end)
    return merged


def _merged_ranges_cover_total(merged: list[dict[str, int]], total_lines: int | None) -> bool:
    if total_lines is None or total_lines < 1 or not merged:
        return False
    return (
        len(merged) == 1
        and int(merged[0]["start_line"]) <= 1
        and int(merged[0]["end_line"]) >= int(total_lines)
    )


def _missing_ranges(merged: list[dict[str, int]], total_lines: int | None) -> list[dict[str, int]]:
    if total_lines is None or total_lines < 1:
        return []
    missing: list[dict[str, int]] = []
    cursor = 1
    for item in merged:
        start = int(item["start_line"])
        end = int(item["end_line"])
        if start > cursor:
            missing.append({"start_line": cursor, "end_line": min(start - 1, total_lines)})
        cursor = max(cursor, end + 1)
        if cursor > total_lines:
            break
    if cursor <= total_lines:
        missing.append({"start_line": cursor, "end_line": total_lines})
    return missing


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


def _bool_or_none(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {}, ())}
