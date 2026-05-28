from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

from harness.loop.model_action_protocol import ModelActionRequest
from harness.loop.task_lifecycle import start_task_lifecycle

from .models import EngagementContract, EngagementEvent, EngagementRunRecord
from .run_repository import EngagementRunRepository
from .task_run_adapter import task_run_contract_from_engagement


class EngagementDispatcher:
    def __init__(self, backend_dir: Path | str) -> None:
        self.backend_dir = Path(backend_dir)
        self.runs = EngagementRunRepository(self.backend_dir)

    def dispatch(
        self,
        *,
        runtime_host: Any,
        session_id: str,
        turn_id: str,
        contract: EngagementContract,
        agent_profile_ref: str,
    ) -> dict[str, Any]:
        run = EngagementRunRecord(
            engagement_run_id=f"engrun:{uuid.uuid4().hex[:12]}",
            request_id=contract.request_id,
            contract_id=contract.contract_id,
            plan_id=contract.plan_id,
            plan_version=contract.plan_version,
            strategy_kind=contract.execution_strategy.kind,
            status="admitted",
        )
        self.runs.upsert_run(run)
        if hasattr(runtime_host, "runtime_objects"):
            runtime_host.runtime_objects.put_object(
                "engagement_run",
                run.engagement_run_id,
                run.to_dict(),
            )
        self._event(run.engagement_run_id, "admitted", "特定任务合同已通过准入。")
        kind = contract.execution_strategy.kind
        if kind == "single_agent_task_run":
            return self._dispatch_task_run(
                runtime_host=runtime_host,
                session_id=session_id,
                turn_id=turn_id,
                contract=contract,
                run=run,
                agent_profile_ref=agent_profile_ref,
            )
        if kind in {"workflow_run", "human_gate"}:
            blocked = self.runs.update_run(
                run.engagement_run_id,
                status="blocked",
                closeout={"reason": f"unsupported_strategy:{kind}"},
            )
            self._event(blocked.engagement_run_id, "blocked", f"执行策略尚未接通：{kind}。")
            return {
                "decision": "unsupported_strategy",
                "engagement_run": blocked.to_dict(),
                "execution_strategy": kind,
                "closeout": dict(blocked.closeout),
            }
        completed = self.runs.update_run(
            run.engagement_run_id,
            status="completed",
            closeout={"acceptance": "turn_acceptance_pending_runtime_loop"},
        )
        self._event(completed.engagement_run_id, "closed", "当前 turn 合同已记录，等待 turn runtime 消费。")
        return {
            "decision": "completed",
            "engagement_run": completed.to_dict(),
            "execution_strategy": kind,
            "turn_result": {"status": "recorded"},
            "closeout": dict(completed.closeout),
        }

    def _dispatch_task_run(
        self,
        *,
        runtime_host: Any,
        session_id: str,
        turn_id: str,
        contract: EngagementContract,
        run: EngagementRunRecord,
        agent_profile_ref: str,
    ) -> dict[str, Any]:
        task_run_contract = task_run_contract_from_engagement(contract)
        task_run_contract = _with_engagement_run_ref(task_run_contract, run.engagement_run_id)
        action_request = ModelActionRequest(
            request_id=f"engagement-action:{contract.request_id}",
            turn_id=turn_id,
            action_type="request_task_run",
            task_contract_seed=task_run_contract.to_dict(),
            diagnostics={"engagement_contract_ref": contract.contract_id, "engagement_plan_ref": contract.plan_id},
        )
        task_run, agent_run, lifecycle, events = start_task_lifecycle(
            runtime_host,
            session_id=session_id,
            turn_id=turn_id,
            task_id=contract.plan_id,
            action_request=action_request,
            contract=task_run_contract,
            agent_profile_ref=agent_profile_ref,
        )
        updated = self.runs.update_run(run.engagement_run_id, status="running", task_run_id=task_run.task_run_id)
        if hasattr(runtime_host, "runtime_objects"):
            runtime_host.runtime_objects.put_object(
                "engagement_run",
                updated.engagement_run_id,
                updated.to_dict(),
            )
        self._event(updated.engagement_run_id, "dispatched", "特定任务已进入单 agent TaskRun 生命周期。")
        return {
            "decision": "started",
            "engagement_run": updated.to_dict(),
            "execution_strategy": contract.execution_strategy.kind,
            "task_run": task_run.to_dict(),
            "agent_run": agent_run.to_dict(),
            "lifecycle": lifecycle.to_dict(),
            "events": events,
        }

    def _event(self, engagement_run_id: str, event_type: str, summary: str) -> None:
        self.runs.append_event(
            EngagementEvent(
                engagement_run_id=engagement_run_id,
                event_type=event_type,
                summary=summary,
                created_at=str(time.time()),
            )
        )


def _with_engagement_run_ref(task_run_contract: Any, engagement_run_id: str) -> Any:
    from dataclasses import replace

    runtime_profile = dict(task_run_contract.runtime_profile or {})
    runtime_profile["engagement_run_ref"] = engagement_run_id
    return replace(task_run_contract, runtime_profile=runtime_profile)
