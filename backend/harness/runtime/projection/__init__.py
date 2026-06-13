"""Canonical public projection system.

Legacy public projection sources have been removed. Runtime code must import
from this package only.
"""

from .projector import attach_public_projection_event, project_public_projection_event

__all__ = [
    "attach_public_projection_event",
    "project_public_projection_event",
]
