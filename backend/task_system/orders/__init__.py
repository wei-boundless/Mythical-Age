"""Task order authority objects and services."""

from __future__ import annotations

from typing import Any

__all__ = [
    "ConversationTurn",
    "ExecutionChannel",
    "TaskExecutionEnvelope",
    "TaskIntentDecision",
    "TaskIntentDecisionService",
    "TaskOrder",
    "TaskOrderCreation",
    "TaskOrderDraft",
    "TaskOrderFactory",
    "TaskOrderRegistry",
    "TaskOrderRun",
]


def __getattr__(name: str) -> Any:
    if name in {
        "ConversationTurn",
        "ExecutionChannel",
        "TaskExecutionEnvelope",
        "TaskIntentDecision",
        "TaskOrder",
        "TaskOrderDraft",
        "TaskOrderRun",
    }:
        from . import models

        return getattr(models, name)
    if name == "TaskIntentDecisionService":
        from .intent_decision import TaskIntentDecisionService

        return TaskIntentDecisionService
    if name in {"TaskOrderFactory", "TaskOrderCreation"}:
        from . import order_factory

        return getattr(order_factory, name)
    if name == "TaskOrderRegistry":
        from .order_registry import TaskOrderRegistry

        return TaskOrderRegistry
    raise AttributeError(name)
