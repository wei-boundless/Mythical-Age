from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from json_file_store import JsonFilePayloadCorrupt, JsonFileStoreError, json_file_lock, read_json_dict, write_json_dict


READ_OBSERVATION_AUTHORITY = "runtime_objects.read_observation_artifact.v1"
READ_OBSERVATIONS_SUBDIR = "read_observations"


class ReadObservationArtifactStore:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = Path(root_dir)
        self.base_dir = self.root_dir / READ_OBSERVATIONS_SUBDIR
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def write_read_observation(
        self,
        *,
        task_run_id: str = "",
        scope: dict[str, Any] | None = None,
        path: str,
        text: str,
        start_line: int,
        end_line: int,
        returned_lines: int,
        line_count: int,
        total_lines: int,
        has_more: bool,
        next_start_line: int | None = None,
        content_sha256: str = "",
        mtime_ns: int | None = None,
        size_bytes: int | None = None,
        tool_call_id: str = "",
        tool_result_ref: str = "",
        observation_ref: str = "",
        source_tool_name: str = "read_file",
        repository_id: str = "",
    ) -> dict[str, Any]:
        scope_payload = dict(scope or {})
        normalized_path = _normalize_path(path)
        normalized_text = str(text or "")
        text_sha256 = _sha256_text(normalized_text)
        content_hash = str(content_sha256 or "").strip()
        digest = _artifact_digest(
            task_run_id=task_run_id,
            scope=scope_payload,
            path=normalized_path,
            start_line=start_line,
            end_line=end_line,
            text_sha256=text_sha256,
            content_sha256=content_hash,
            mtime_ns=mtime_ns,
        )
        artifact_ref = f"read_observation:{digest}"
        directory = self._artifact_dir(artifact_ref)
        directory.mkdir(parents=True, exist_ok=True)
        text_path = directory / "content.txt"
        meta_path = directory / "metadata.json"
        text_path.write_text(normalized_text, encoding="utf-8")
        metadata = _drop_empty(
            {
                "artifact_ref": artifact_ref,
                "task_run_id": str(task_run_id or ""),
                "scope_kind": str(scope_payload.get("kind") or ""),
                "scope_id": str(scope_payload.get("scope_id") or ""),
                "session_id": str(scope_payload.get("session_id") or ""),
                "path": normalized_path,
                "repository_id": str(repository_id or ""),
                "start_line": int(start_line or 0),
                "end_line": int(end_line or 0),
                "returned_lines": int(returned_lines or 0),
                "line_count": int(line_count or 0),
                "total_lines": int(total_lines or 0),
                "has_more": bool(has_more),
                "next_start_line": int(next_start_line) if next_start_line is not None else None,
                "content_sha256": content_hash,
                "text_sha256": text_sha256,
                "mtime_ns": int(mtime_ns) if mtime_ns is not None else None,
                "size_bytes": int(size_bytes) if size_bytes is not None else len(normalized_text.encode("utf-8", errors="replace")),
                "tool_call_id": str(tool_call_id or ""),
                "tool_result_ref": str(tool_result_ref or ""),
                "observation_ref": str(observation_ref or ""),
                "source_tool_name": str(source_tool_name or "read_file"),
                "content_omitted": False,
                "created_at": time.time(),
                "text_path": str(text_path),
                "authority": READ_OBSERVATION_AUTHORITY,
            }
        )
        _write_json(meta_path, metadata)
        self._bind_alias(artifact_ref, artifact_ref)
        for alias in (tool_result_ref, observation_ref, tool_call_id):
            if str(alias or "").strip():
                self._bind_alias(str(alias or "").strip(), artifact_ref)
        return metadata

    def bind_observation_ref(self, *, artifact_ref: str, observation_ref: str = "", tool_result_ref: str = "") -> None:
        target = str(artifact_ref or "").strip()
        if not target:
            return
        if not self.artifact_exists(target):
            return
        for alias in (observation_ref, tool_result_ref):
            text = str(alias or "").strip()
            if text:
                self._bind_alias(text, target)
                metadata = self.read_metadata(target)
                if metadata:
                    if observation_ref:
                        metadata["observation_ref"] = str(observation_ref or "")
                    if tool_result_ref:
                        metadata["tool_result_ref"] = str(tool_result_ref or "")
                    _write_json(self._artifact_dir(target) / "metadata.json", metadata)

    def artifact_exists(self, artifact_ref: str) -> bool:
        ref = self.resolve_ref(artifact_ref)
        if not ref:
            return False
        directory = self._artifact_dir(ref)
        return (directory / "metadata.json").is_file() and (directory / "content.txt").is_file()

    def resolve_ref(self, ref: str) -> str:
        text = str(ref or "").strip()
        if not text:
            return ""
        if text.startswith("read_observation:"):
            return text
        aliases = self._read_aliases()
        return str(aliases.get(text) or "").strip()

    def read_metadata(self, ref: str) -> dict[str, Any]:
        artifact_ref = self.resolve_ref(ref)
        if not artifact_ref:
            return {}
        try:
            metadata = read_json_dict(
                self._artifact_dir(artifact_ref) / "metadata.json",
                label=f"read observation artifact {artifact_ref}",
                missing_factory=dict,
            )
        except (JsonFileStoreError, JsonFilePayloadCorrupt):
            return {}
        if str(metadata.get("artifact_ref") or "") != artifact_ref:
            return {}
        return dict(metadata)

    def read_text(self, ref: str) -> str:
        artifact_ref = self.resolve_ref(ref)
        if not artifact_ref:
            raise FileNotFoundError(str(ref or ""))
        path = self._artifact_dir(artifact_ref) / "content.txt"
        resolved = path.resolve()
        base = self.base_dir.resolve()
        if base not in [resolved, *resolved.parents]:
            raise ValueError("read observation artifact path is outside store")
        return resolved.read_text(encoding="utf-8")

    def read_payload(self, ref: str) -> dict[str, Any]:
        artifact_ref = self.resolve_ref(ref)
        if not artifact_ref:
            raise FileNotFoundError(str(ref or ""))
        metadata = self.read_metadata(artifact_ref)
        if not metadata:
            raise FileNotFoundError(str(ref or ""))
        text = self.read_text(artifact_ref)
        expected_sha = str(metadata.get("text_sha256") or "").strip()
        actual_sha = _sha256_text(text)
        if expected_sha and expected_sha != actual_sha:
            raise ValueError("read observation artifact text hash mismatch")
        return {
            "metadata": dict(metadata),
            "text": text,
            "artifact_ref": str(metadata.get("artifact_ref") or artifact_ref),
        }

    def _artifact_dir(self, artifact_ref: str) -> Path:
        digest = str(artifact_ref or "").split(":", 1)[-1]
        return self.base_dir / _safe_part(digest)

    def _aliases_path(self) -> Path:
        return self.base_dir / "aliases.json"

    def _bind_alias(self, alias: str, artifact_ref: str) -> None:
        key = str(alias or "").strip()
        value = str(artifact_ref or "").strip()
        if not key or not value:
            return
        path = self._aliases_path()
        with json_file_lock(path):
            aliases = self._read_aliases_unlocked()
            aliases[key] = value
            _write_json(path, aliases)

    def _read_aliases(self) -> dict[str, str]:
        path = self._aliases_path()
        with json_file_lock(path):
            return self._read_aliases_unlocked()

    def _read_aliases_unlocked(self) -> dict[str, str]:
        try:
            payload = read_json_dict(self._aliases_path(), label="read observation aliases", missing_factory=dict)
        except (JsonFileStoreError, JsonFilePayloadCorrupt):
            return {}
        return {str(key): str(value) for key, value in payload.items() if str(key).strip() and str(value).strip()}


def _artifact_digest(
    *,
    task_run_id: str,
    scope: dict[str, Any],
    path: str,
    start_line: int,
    end_line: int,
    text_sha256: str,
    content_sha256: str,
    mtime_ns: int | None,
) -> str:
    payload = {
        "task_run_id": str(task_run_id or ""),
        "scope": dict(scope or {}),
        "path": str(path or ""),
        "start_line": int(start_line or 0),
        "end_line": int(end_line or 0),
        "text_sha256": str(text_sha256 or ""),
        "content_sha256": str(content_sha256 or ""),
        "mtime_ns": int(mtime_ns) if mtime_ns is not None else None,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:32]


def _sha256_text(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8", errors="replace")).hexdigest()


def _normalize_path(path: Any) -> str:
    return str(path or "").replace("\\", "/").strip().strip("/")


def _safe_part(value: str) -> str:
    text = str(value or "").strip()
    return "".join(char if char.isalnum() or char in {"-", "_", "."} else "_" for char in text) or "artifact"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    try:
        write_json_dict(path, payload, label=str(path))
    except JsonFileStoreError as exc:
        raise RuntimeError(str(exc)) from exc


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {}, ())}
