from __future__ import annotations

from typing import Protocol

from agents.a2a_runtime import A2ATaskEnvelope


class A2ATransport(Protocol):
    """Transport seam for future local/hybrid/remote A2A execution."""

    async def submit_task(self, envelope: A2ATaskEnvelope) -> A2ATaskEnvelope:
        ...


class LocalA2ATransport:
    """No-op local transport used until worker agents are split out of process."""

    async def submit_task(self, envelope: A2ATaskEnvelope) -> A2ATaskEnvelope:
        return envelope
