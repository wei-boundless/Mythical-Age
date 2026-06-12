from __future__ import annotations

import asyncio
from pathlib import Path

from capability_system.skills.paths import CapabilitySkillPaths
from capability_system.skills.registry import SkillRegistry
from capability_system.skills.scanner import refresh_snapshot
from capability_system.tools.registry import refresh_tool_registry
from capability_system.tools.native_tool_runtime import ToolRuntime
from capability_system.mcp.paths import CapabilityMCPPaths
from capability_system.tools.paths import CapabilityToolPaths
from memory_system import MemoryFacade
from memory_system.governance_service import DEFAULT_GOVERNANCE_MIN_INTERVAL_SECONDS
from memory_system.layout import durable_memory_namespace_id_for_task_environment
from permissions import PermissionService
from harness.entrypoint import HarnessRuntimeFacade
from bootstrap.settings import AppSettingsService
from capability_system.capabilities.retrieval import RetrievalService
from health_system.graph_breakpoint_command_supervisor import GraphBreakpointCommandSupervisor
from health_system.graph_breakpoint_supervisor import GraphBreakpointSupervisor
from sessions import SessionManager
from runtime import ModelRuntime
from runtime.prompt_accounting import PromptAccountingLedger
from project_layout import ProjectLayout


class AppRuntime:
    def __init__(self) -> None:
        self.base_dir: Path | None = None
        self.settings: AppSettingsService | None = None
        self.session_manager: SessionManager | None = None
        self.skill_registry: SkillRegistry | None = None
        self.tool_runtime: ToolRuntime | None = None
        self.memory_facade: MemoryFacade | None = None
        self.retrieval_service: RetrievalService | None = None
        self.permission_service: PermissionService | None = None
        self.model_runtime: ModelRuntime | None = None
        self.harness_runtime: HarnessRuntimeFacade | None = None
        self.graph_breakpoint_supervisor: GraphBreakpointSupervisor | None = None
        self.graph_breakpoint_command_supervisor: GraphBreakpointCommandSupervisor | None = None
        self._background_services_started = False

    def initialize(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        CapabilitySkillPaths.from_base_dir(base_dir).ensure()
        CapabilityToolPaths.from_base_dir(base_dir).ensure()
        CapabilityMCPPaths.from_base_dir(base_dir).ensure()
        self.settings = AppSettingsService(base_dir)
        refresh_snapshot(base_dir)
        refresh_tool_registry(base_dir)
        self.session_manager = SessionManager(base_dir)
        self.skill_registry = SkillRegistry(base_dir)
        self.tool_runtime = ToolRuntime(base_dir)
        self.memory_facade = MemoryFacade(base_dir, context_budget_provider=self.settings.context_budget_settings)
        self.retrieval_service = RetrievalService(base_dir)
        self.permission_service = PermissionService(self.settings, self.tool_runtime)
        self.model_runtime = ModelRuntime(
            self.settings,
            prompt_accounting_ledger=PromptAccountingLedger(ProjectLayout.from_backend_dir(base_dir).runtime_state_dir),
        )
        self.memory_facade.set_model_invoker(self.model_runtime.invoke_messages)
        self.memory_facade.set_session_compactor_kwargs_provider(self._session_compactor_kwargs)
        self.memory_facade.set_durable_memory_saved_callback(self._on_durable_memory_saved)
        self.memory_facade.background_task_manager.register_handler(
            "durable_memory_index_rebuild",
            self._run_durable_memory_index_rebuild,
        )
        self.memory_facade.background_task_manager.register_handler(
            "durable_memory_governance_tick",
            self._run_durable_memory_governance_tick,
        )
        self.harness_runtime = HarnessRuntimeFacade(
            base_dir=base_dir,
            settings_service=self.settings,
            session_manager=self.session_manager,
            memory_facade=self.memory_facade,
            retrieval_service=self.retrieval_service,
            tool_runtime=self.tool_runtime,
            skill_registry=self.skill_registry,
            permission_service=self.permission_service,
            model_runtime=self.model_runtime,
        )
        self.graph_breakpoint_supervisor = GraphBreakpointSupervisor(
            base_dir=base_dir,
            runtime=self,
        )
        self.graph_breakpoint_command_supervisor = GraphBreakpointCommandSupervisor(
            base_dir=base_dir,
            runtime=self,
        )

    async def start_background_services(self) -> None:
        runtime = self.require_ready()
        if self._background_services_started:
            return
        host = runtime.harness_runtime.single_agent_runtime_host
        supervisor = self.graph_breakpoint_supervisor
        command_supervisor = self.graph_breakpoint_command_supervisor
        if supervisor is not None:
            host.spawn_background_task(
                self._run_background_service_after_startup(supervisor.run_forever),
                name="health-graph-breakpoint-supervisor",
            )
        if command_supervisor is not None:
            host.spawn_background_task(
                self._run_background_service_after_startup(command_supervisor.run_forever),
                name="health-graph-breakpoint-command-supervisor",
            )
        self._background_services_started = True

    async def _run_background_service_after_startup(self, runner, *, initial_delay_seconds: float = 1.0) -> None:
        if initial_delay_seconds > 0:
            await asyncio.sleep(initial_delay_seconds)
        result = runner()
        if hasattr(result, "__await__"):
            await result

    def _session_compactor_kwargs(self, session_id: str) -> dict[str, object]:
        if self.base_dir is None or self.model_runtime is None:
            return {}
        kwargs: dict[str, object] = {
            "microcompact_cache_state_provider": lambda payload=None: self._microcompact_cache_state(
                {**dict(payload or {}), "session_id": session_id}
            ),
            "post_compact_hook": self._on_context_compact_boundary,
        }
        from harness.runtime import build_registered_semantic_compaction_worker

        resolver = (
            self.harness_runtime.agent_runtime_registry.get_profile
            if self.harness_runtime is not None
            else None
        )
        worker = build_registered_semantic_compaction_worker(
            base_dir=self.base_dir,
            model_runtime=self.model_runtime,
            agent_runtime_profile_resolver=resolver,
        )
        if worker is not None:
            kwargs["semantic_compactor"] = worker
        return kwargs

    def _microcompact_cache_state(self, payload: dict[str, object]) -> dict[str, object]:
        model_runtime = self.model_runtime
        ledger = getattr(model_runtime, "prompt_accounting_ledger", None) if model_runtime is not None else None
        if ledger is None or not hasattr(ledger, "list_prompt_cache"):
            return {"cache_temperature": "unknown", "source": "app_runtime.no_prompt_accounting_ledger"}
        session_id = str(dict(payload or {}).get("session_id") or "")
        task_run_id = str(dict(payload or {}).get("task_run_id") or "")
        run_id = str(dict(payload or {}).get("run_id") or "")
        records = ledger.list_prompt_cache(run_id=run_id, task_run_id=task_run_id, session_id=session_id)
        if not records:
            return {"cache_temperature": "unknown", "source": "app_runtime.prompt_cache_empty"}
        latest = records[-1]
        cached_tokens = max(int(getattr(latest, "cached_tokens", 0) or 0), int(getattr(latest, "cache_read_tokens", 0) or 0))
        return {
            "cache_temperature": "warm" if str(getattr(latest, "status", "") or "") == "hit" or cached_tokens > 0 else "cold",
            "cache_record_id": str(getattr(latest, "cache_record_id", "") or ""),
            "cache_key": str(getattr(latest, "cache_key", "") or ""),
            "prefix_hash": str(getattr(latest, "prefix_hash", "") or ""),
            "status": str(getattr(latest, "status", "") or ""),
            "cached_tokens": cached_tokens,
            "provider_cache_editing_supported": False,
            "source": "app_runtime.latest_prompt_cache_record",
        }

    def _on_context_compact_boundary(self, receipt: object) -> dict[str, object]:
        payload = receipt.to_dict() if hasattr(receipt, "to_dict") else dict(receipt or {}) if isinstance(receipt, dict) else {}
        if bool(payload.get("blocked")):
            return {"allowed": True, "reason": "compact_blocked_no_baseline_reset"}
        if str(payload.get("trigger") or "") == "preview":
            return {"allowed": True, "reason": "compact_preview_no_baseline_reset"}
        applied_strategy = str(payload.get("applied_strategy") or "")
        replaced_count = int(payload.get("replaced_message_count") or 0)
        if applied_strategy != "full_compact" and replaced_count <= 0:
            return {"allowed": True, "reason": "compact_no_prompt_rewrite"}
        model_runtime = self.model_runtime
        ledger = getattr(model_runtime, "prompt_accounting_ledger", None) if model_runtime is not None else None
        if ledger is None or not hasattr(ledger, "reset_prompt_cache_baseline"):
            return {"allowed": True, "reason": "prompt_accounting_ledger_unavailable"}
        reset = ledger.reset_prompt_cache_baseline(
            request_id=f"pcachebaseline-reset:{payload.get('request_id') or 'context_compact'}",
            session_id=str(payload.get("session_id") or ""),
            task_run_id=str(payload.get("task_run_id") or ""),
            reason=f"context_compaction:{applied_strategy or 'unknown'}",
            reset_ref=str(payload.get("receipt_id") or ""),
            diagnostics={
                "trigger": str(payload.get("trigger") or ""),
                "pressure_level": str(payload.get("pressure_level") or ""),
                "replaced_message_count": replaced_count,
            },
        )
        return {
            "allowed": True,
            "reason": "prompt_cache_baseline_reset_after_compact",
            "diagnostics": {"baseline_reset_id": reset.baseline_id},
        }

    def require_ready(self) -> "AppRuntime":
        if (
            self.base_dir is None
            or self.settings is None
            or self.session_manager is None
            or self.skill_registry is None
            or self.tool_runtime is None
            or self.memory_facade is None
            or self.retrieval_service is None
            or self.permission_service is None
            or self.model_runtime is None
            or self.harness_runtime is None
        ):
            raise RuntimeError("App runtime is not initialized")
        return self

    def refresh_catalogs(self) -> None:
        runtime = self.require_ready()
        refresh_snapshot(runtime.base_dir)
        refresh_tool_registry(runtime.base_dir)
        runtime.skill_registry.reload()
        runtime.tool_runtime.reload()

    async def shutdown(self) -> None:
        host = getattr(getattr(self, "harness_runtime", None), "single_agent_runtime_host", None)
        if host is not None:
            await host.cancel_background_tasks(
                names={
                    "health-graph-breakpoint-supervisor",
                    "health-graph-breakpoint-command-supervisor",
                },
                reason="app_runtime_shutdown",
            )
        self._background_services_started = False
        model_runtime = self.model_runtime
        if model_runtime is not None:
            close = getattr(model_runtime, "close", None)
            if callable(close):
                await close()

    def refresh_indexes_for_path(self, relative_path: str) -> None:
        runtime = self.require_ready()
        normalized = relative_path.replace("\\", "/")
        if normalized.startswith("capability_system/skills/") or normalized.startswith("capability_system/tools/registries/"):
            self.refresh_catalogs()
            return
        if normalized.startswith("durable_memory/") or normalized.startswith("storage/memory/durable/"):
            namespace_id = self._namespace_from_durable_relative_path(normalized)
            runtime.memory_facade.mark_durable_memory_namespaces_dirty(
                {namespace_id: 1},
                reason="durable_memory_path_refresh",
            )
            runtime.memory_facade.background_task_manager.enqueue(
                "durable_memory_index_rebuild",
                payload={"collection": "durable_memory", "source_path": normalized},
                source="bootstrap.app_runtime",
                coalesce_key="durable_memory",
            )
            runtime.memory_facade.background_task_manager.enqueue(
                "durable_memory_governance_tick",
                payload={
                    "reason": "durable_memory_path_refresh",
                    "source_path": normalized,
                },
                source="bootstrap.app_runtime",
                coalesce_key="durable_memory_governance",
            )
            return
        if normalized.startswith("session-memory/") or normalized.startswith("storage/memory/session/"):
            runtime.retrieval_service.rebuild_session_memory()
            return
        if normalized.startswith("knowledge/"):
            runtime.retrieval_service.rebuild_knowledge()

    def _on_durable_memory_saved(self, saved_namespaces: dict[str, int]) -> None:
        runtime = self.require_ready()
        normalized = {
            str(namespace_id or "").strip() or "global_common": max(0, int(count or 0))
            for namespace_id, count in dict(saved_namespaces or {}).items()
        }
        normalized = {namespace_id: count for namespace_id, count in normalized.items() if count > 0}
        saved_count = sum(normalized.values())
        if saved_count <= 0:
            return
        if runtime.memory_facade is not None:
            runtime.memory_facade.background_task_manager.enqueue(
                "durable_memory_index_rebuild",
                payload={
                    "collection": "durable_memory",
                    "saved_count": saved_count,
                    "saved_namespaces": normalized,
                },
                source="bootstrap.app_runtime",
                coalesce_key="durable_memory",
            )
            runtime.memory_facade.background_task_manager.enqueue(
                "durable_memory_governance_tick",
                payload={
                    "reason": "durable_memory_saved",
                    "saved_namespaces": normalized,
                },
                source="bootstrap.app_runtime",
                coalesce_key="durable_memory_governance",
            )

    async def _run_durable_memory_index_rebuild(self, payload: dict[str, object]) -> dict[str, object]:
        runtime = self.require_ready()
        collection = str(payload.get("collection") or "durable_memory")
        if collection != "durable_memory":
            return {"collection": collection, "status": "skipped"}
        result = runtime.retrieval_service.rebuild_durable_memory()
        return {"collection": collection, "status": "queued_or_completed", "result": result}

    async def _run_durable_memory_governance_tick(self, payload: dict[str, object]) -> dict[str, object]:
        runtime = self.require_ready()
        namespace_ids = [
            str(item or "").strip()
            for item in list(payload.get("namespace_ids") or [])
            if str(item or "").strip()
        ] or None
        result = runtime.memory_facade.run_durable_memory_governance_tick(
            namespace_ids=namespace_ids,
            force=bool(payload.get("force", False)),
            min_interval_seconds=int(payload.get("min_interval_seconds") or DEFAULT_GOVERNANCE_MIN_INTERVAL_SECONDS),
            reason=str(payload.get("reason") or "background_tick"),
            source="bootstrap.app_runtime",
        )
        ran = [dict(item or {}) for item in list(result.get("ran") or [])]
        if any(str(item.get("namespace_id") or "") == "global_common" and int(item.get("updated") or 0) > 0 for item in ran):
            runtime.retrieval_service.rebuild_durable_memory()
        return dict(result)

    def _namespace_from_durable_relative_path(self, normalized_path: str) -> str:
        parts = str(normalized_path or "").replace("\\", "/").split("/")
        if len(parts) >= 3 and parts[0] == "durable_memory" and parts[1] == "environments":
            return durable_memory_namespace_id_for_task_environment(parts[2])
        if len(parts) >= 5 and parts[:3] == ["storage", "memory", "durable"] and parts[3] == "environments":
            return durable_memory_namespace_id_for_task_environment(parts[4])
        return "global_common"


app_runtime = AppRuntime()
