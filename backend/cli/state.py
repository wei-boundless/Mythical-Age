from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_API_BASE = "http://127.0.0.1:8003/api"


@dataclass(slots=True)
class CliState:
    api_base: str = DEFAULT_API_BASE
    selected_session_id: str = ""


class CliStateStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or _default_state_path()

    def load(self) -> CliState:
        if not self.path.exists():
            return CliState(api_base=_default_api_base())
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return CliState(api_base=_default_api_base())
        if not isinstance(payload, dict):
            return CliState(api_base=_default_api_base())
        return CliState(
            api_base=str(payload.get("api_base") or _default_api_base()).rstrip("/"),
            selected_session_id=str(payload.get("selected_session_id") or ""),
        )

    def save(self, state: CliState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "api_base": state.api_base.rstrip("/") or DEFAULT_API_BASE,
            "selected_session_id": state.selected_session_id,
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def update(self, **changes: Any) -> CliState:
        state = self.load()
        next_state = CliState(
            api_base=str(changes.get("api_base", state.api_base) or DEFAULT_API_BASE).rstrip("/"),
            selected_session_id=str(changes.get("selected_session_id", state.selected_session_id) or ""),
        )
        self.save(next_state)
        return next_state


def _default_api_base() -> str:
    return str(os.environ.get("AGENT_API_BASE") or DEFAULT_API_BASE).rstrip("/")


def _default_state_path() -> Path:
    override = os.environ.get("AGENT_CLI_STATE_PATH")
    if override:
        return Path(override)
    return Path.home() / ".langchain-agent-cli.json"

