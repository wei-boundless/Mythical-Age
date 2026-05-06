from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Any

from .models import ExternalMCPServerConfig


SERVER_ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{1,63}$")


class ExternalMCPConfigStore:
    def __init__(self, backend_dir: Path) -> None:
        self.backend_dir = Path(backend_dir).resolve()
        self.path = self.backend_dir / "mcp_external_servers.json"

    def list_servers(self) -> list[ExternalMCPServerConfig]:
        payload = self._load_payload()
        items = payload.get("servers")
        if not isinstance(items, list):
            return []
        servers = []
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                server = ExternalMCPServerConfig.from_dict(item)
            except Exception:
                continue
            if server.server_id:
                servers.append(server)
        return sorted(servers, key=lambda item: item.server_id)

    def get_server(self, server_id: str) -> ExternalMCPServerConfig | None:
        normalized = validate_server_id(server_id)
        return next((server for server in self.list_servers() if server.server_id == normalized), None)

    def upsert_server(self, config: ExternalMCPServerConfig) -> ExternalMCPServerConfig:
        validate_server_id(config.server_id)
        validate_server_config(config)
        servers = [server for server in self.list_servers() if server.server_id != config.server_id]
        servers.append(config)
        self._save_servers(servers)
        return config

    def delete_server(self, server_id: str) -> None:
        normalized = validate_server_id(server_id)
        self._save_servers([server for server in self.list_servers() if server.server_id != normalized])

    def _load_payload(self) -> dict[str, Any]:
        if not self.path.exists():
            self._write_payload({"schema_version": 1, "servers": []})
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {"schema_version": 1, "servers": []}
            self._write_payload(payload)
        return payload if isinstance(payload, dict) else {"schema_version": 1, "servers": []}

    def _save_servers(self, servers: list[ExternalMCPServerConfig]) -> None:
        self._write_payload(
            {
                "schema_version": 1,
                "authority": "mcp_client.external_config_store",
                "servers": [server.to_dict() for server in sorted(servers, key=lambda item: item.server_id)],
            }
        )

    def _write_payload(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(payload, ensure_ascii=False, indent=2)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=str(self.path.parent),
            delete=False,
            prefix=f"{self.path.name}.",
            suffix=".tmp",
        ) as handle:
            handle.write(content)
            tmp_path = Path(handle.name)
        tmp_path.replace(self.path)


def validate_server_id(server_id: str) -> str:
    normalized = str(server_id or "").strip()
    if not SERVER_ID_PATTERN.fullmatch(normalized):
        raise ValueError("server_id must be 2-64 letters, numbers, hyphens, or underscores")
    return normalized


def validate_server_config(config: ExternalMCPServerConfig) -> None:
    transport = str(config.transport or "").strip().lower()
    if transport not in {"stdio", "streamable_http"}:
        raise ValueError("transport must be stdio or streamable_http")
    if transport == "stdio" and not config.command:
        raise ValueError("stdio MCP server requires command")
    if transport == "streamable_http" and not config.url:
        raise ValueError("streamable_http MCP server requires url")
