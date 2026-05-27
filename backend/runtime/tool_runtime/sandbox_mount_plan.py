from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class SandboxMount:
    source: str
    target: str
    mode: str = "read"
    kind: str = "material"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SandboxMountPlan:
    mounts: tuple[SandboxMount, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"mounts": [mount.to_dict() for mount in self.mounts]}


def sandbox_mount_plan_from_payload(payload: dict[str, Any] | None) -> SandboxMountPlan:
    mounts: list[SandboxMount] = []
    for item in list(dict(payload or {}).get("mounts") or []):
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or "").strip()
        target = str(item.get("target") or "").strip()
        if not source or not target:
            continue
        mounts.append(
            SandboxMount(
                source=source,
                target=target,
                mode=str(item.get("mode") or "read").strip() or "read",
                kind=str(item.get("kind") or "material").strip() or "material",
            )
        )
    return SandboxMountPlan(mounts=tuple(mounts))


