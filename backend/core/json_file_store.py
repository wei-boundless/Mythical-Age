from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator


class JsonFileStoreError(RuntimeError):
    pass


class JsonFilePayloadCorrupt(JsonFileStoreError):
    pass


_LOCKS_GUARD = threading.Lock()
_FILE_LOCKS: dict[str, threading.RLock] = {}


def read_json_dict(
    path: Path,
    *,
    label: str,
    missing_factory: Callable[[], dict[str, Any]] | None = None,
    read_retries: int = 16,
) -> dict[str, Any]:
    if not path.exists():
        return missing_factory() if missing_factory is not None else {}
    raw = ""
    last_error: OSError | None = None
    for attempt in range(max(1, read_retries)):
        try:
            raw = path.read_text(encoding="utf-8")
            last_error = None
            break
        except PermissionError as exc:
            last_error = exc
            if attempt == max(1, read_retries) - 1:
                break
            time.sleep(min(0.75, 0.05 * (attempt + 1)))
        except UnicodeDecodeError as exc:
            raise JsonFilePayloadCorrupt(f"corrupt {label}: {path.name}") from exc
        except OSError as exc:
            raise JsonFileStoreError(f"failed to read {label}: {path}") from exc
    if last_error is not None:
        raise JsonFileStoreError(f"failed to read {label}: {path}") from last_error
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise JsonFilePayloadCorrupt(f"corrupt {label}: {path.name}") from exc
    if not isinstance(payload, dict):
        raise JsonFilePayloadCorrupt(f"invalid {label} root: {path.name}")
    return payload


def write_json_dict(
    path: Path,
    payload: dict[str, Any],
    *,
    label: str,
    sort_keys: bool = False,
    trailing_newline: bool = True,
    replace_retries: int = 16,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=sort_keys)
    if trailing_newline:
        content += "\n"
    tmp_path: Path | None = None
    last_error: OSError | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            tmp_path = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(max(1, replace_retries)):
            try:
                os.replace(tmp_path, path)
                tmp_path = None
                return
            except PermissionError as exc:
                last_error = exc
                if attempt == max(1, replace_retries) - 1:
                    break
                time.sleep(min(0.75, 0.05 * (attempt + 1)))
    except OSError as exc:
        last_error = exc
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
    if last_error is not None:
        raise JsonFileStoreError(f"failed to write {label}: {path}") from last_error
    raise JsonFileStoreError(f"failed to write {label}: {path}")


@contextmanager
def json_file_lock(path: Path) -> Iterator[None]:
    key = _lock_key(path)
    with _LOCKS_GUARD:
        lock = _FILE_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _FILE_LOCKS[key] = lock
    with lock:
        yield


def _lock_key(path: Path) -> str:
    normalized = os.path.normcase(os.path.abspath(os.path.normpath(str(path))))
    if normalized.startswith("\\\\?\\"):
        normalized = normalized[4:]
    return normalized
