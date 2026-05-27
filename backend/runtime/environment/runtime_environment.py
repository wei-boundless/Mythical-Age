from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class RuntimeEnvironment:
    workspace_root: Path
    sandbox_root: Path | None = None
    frontend_url: str = "http://127.0.0.1:3000"
    backend_url: str = "http://127.0.0.1:8003"
    api_base: str = "http://127.0.0.1:8003/api"
    browser_policy: str = "edge"

    def snapshot(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["workspace_root"] = str(self.workspace_root)
        payload["sandbox_root"] = str(self.sandbox_root) if self.sandbox_root is not None else ""
        payload["fixed_ports"] = {"frontend": 3000, "backend": 8003}
        payload["authority"] = "runtime.environment"
        return payload


