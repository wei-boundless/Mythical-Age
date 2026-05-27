from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class SandboxPolicy:
    enabled: bool = False
    read_scopes: tuple[str, ...] = ()
    write_scopes: tuple[str, ...] = ()
    artifact_root: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["read_scopes"] = list(self.read_scopes)
        payload["write_scopes"] = list(self.write_scopes)
        return payload


def sandbox_policy_from_payload(payload: dict[str, Any] | None) -> SandboxPolicy:
    item = dict(payload or {})
    return SandboxPolicy(
        enabled=bool(item.get("enabled") is True),
        read_scopes=tuple(str(value).strip() for value in list(item.get("read_scopes") or []) if str(value).strip()),
        write_scopes=tuple(str(value).strip() for value in list(item.get("write_scopes") or []) if str(value).strip()),
        artifact_root=str(item.get("artifact_root") or "").strip(),
    )


