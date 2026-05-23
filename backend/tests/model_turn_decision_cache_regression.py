from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from runtime.unit_runtime.loop import _invoke_model_turn_decision_with_turn_cache


class _CacheOwner:
    def __init__(self) -> None:
        self._model_turn_decision_cache = {}


class _DecisionInvoker:
    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, _messages, **_kwargs):
        self.calls += 1
        return SimpleNamespace(
            content=json.dumps(
                {
                    "authority": "agent_runtime.model_turn_decision",
                    "decision_id": f"model-turn-decision:test:{self.calls}",
                    "user_message": "hello",
                    "interaction_intent": "answer",
                    "action_intent": "answer_only",
                    "work_mode": "conversation",
                    "task_goal_type": "light_qa",
                    "task_domain": "general",
                    "confidence": 0.95,
                    "target_objects": [],
                    "desired_outcome": "answer",
                    "deliverables": [],
                    "constraints": [],
                    "forbidden_actions": [],
                    "context_binding_decision": {},
                    "planning_required": False,
                    "todo_required": False,
                    "completion_criteria": ["answer the user"],
                    "needs_clarification": False,
                    "clarification_question": "",
                    "ambiguity": [],
                },
                ensure_ascii=False,
            )
        )


def test_model_turn_decision_cache_reuses_accepted_decision_for_same_payload() -> None:
    owner = _CacheOwner()
    invoker = _DecisionInvoker()
    request_facts = {"session_id": "session:test", "turn_id": "turn:1"}
    boundary_policy = {"allowed": True}
    context_candidates = {"candidates": []}

    async def _run():
        first = await _invoke_model_turn_decision_with_turn_cache(
            cache_owner=owner,
            invoker=invoker,
            user_message="hello",
            request_facts=request_facts,
            boundary_policy=boundary_policy,
            context_candidates=context_candidates,
        )
        second = await _invoke_model_turn_decision_with_turn_cache(
            cache_owner=owner,
            invoker=invoker,
            user_message="hello",
            request_facts=request_facts,
            boundary_policy=boundary_policy,
            context_candidates=context_candidates,
        )
        return first, second

    first, second = asyncio.run(_run())

    assert invoker.calls == 1
    assert first[0]["decision_id"] == "model-turn-decision:test:1"
    assert second[0]["decision_id"] == "model-turn-decision:test:1"
    assert second[1]["sidecar_status"] == "cached_accepted"
    assert second[1]["model_call_performed"] is False


def test_model_turn_decision_cache_misses_when_payload_changes() -> None:
    owner = _CacheOwner()
    invoker = _DecisionInvoker()

    async def _run():
        await _invoke_model_turn_decision_with_turn_cache(
            cache_owner=owner,
            invoker=invoker,
            user_message="hello",
            request_facts={"session_id": "session:test", "turn_id": "turn:1"},
            boundary_policy={"allowed": True},
            context_candidates={"candidates": []},
        )
        await _invoke_model_turn_decision_with_turn_cache(
            cache_owner=owner,
            invoker=invoker,
            user_message="hello again",
            request_facts={"session_id": "session:test", "turn_id": "turn:1"},
            boundary_policy={"allowed": True},
            context_candidates={"candidates": []},
        )

    asyncio.run(_run())

    assert invoker.calls == 2
