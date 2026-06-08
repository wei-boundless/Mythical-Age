from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from .registry import HealthRegistry
from .runtime_adapter import build_health_runtime_adapter

logger = logging.getLogger(__name__)


class HealthCommandSupervisor:
    def __init__(
        self,
        *,
        base_dir: Path,
        runtime: Any,
        poll_interval_seconds: float = 8.0,
        batch_limit: int = 4,
    ) -> None:
        self.base_dir = Path(base_dir)
        self.runtime = runtime
        self.poll_interval_seconds = max(2.0, float(poll_interval_seconds or 8.0))
        self.batch_limit = max(1, int(batch_limit or 4))

    async def run_forever(self) -> None:
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("health command supervision tick failed")
            await asyncio.sleep(self.poll_interval_seconds)

    async def run_once(self) -> dict[str, Any]:
        registry = HealthRegistry(self.base_dir)
        pending = self._list_pending_commands(registry)
        processed: list[str] = []
        for command in pending[: self.batch_limit]:
            await registry.command_service.handle_command(
                command,
                agent_runtime=build_health_runtime_adapter(self.runtime),
                model_response_executor=self.runtime.harness_runtime.model_response_executor,
                tool_runtime_executor=self.runtime.harness_runtime.tool_runtime_executor,
                tool_instances=self.runtime.harness_runtime._all_tool_instances(),
            )
            processed.append(command.command_id)
        return {
            "authority": "health_system.command_supervisor",
            "pending_count": len(pending),
            "processed_count": len(processed),
            "processed_command_ids": processed,
        }

    def _list_pending_commands(self, registry: HealthRegistry) -> list[Any]:
        commands = [
            command
            for command in registry.list_commands()
            if command.status == "pending"
            and not (
                command.command_type == "analyze_trace"
                and command.health_action == "graph_breakpoint_diagnostics"
                and command.source == "health_system.graph_breakpoint_supervisor"
            )
        ]
        commands.sort(key=lambda item: (float(item.created_at or 0.0), str(item.command_id or "")))
        return commands
