"""Canonical public projection system.

Legacy public projection sources are archived under the repository-level
projection_legacy/ directory. Runtime code must import from this package only.
"""

from .projector import attach_public_projection_event, project_public_projection_event
from .timeline_builder import project_public_timeline_from_events, project_runtime_monitor_event_public_delta
from .task_projection import build_single_agent_task_projection, build_single_agent_task_projection_for_event

__all__ = [
    "attach_public_projection_event",
    "build_single_agent_task_projection",
    "build_single_agent_task_projection_for_event",
    "project_public_projection_event",
    "project_public_timeline_from_events",
    "project_runtime_monitor_event_public_delta",
]
