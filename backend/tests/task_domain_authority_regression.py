from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from task_system.domains import bind_task_domain


def test_task_domain_binding_requires_explicit_system_domain(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="explicit user/session/order/task-graph domain"):
        bind_task_domain(
            base_dir=tmp_path,
            task_id="task:test",
            requested_domain="",
            task_goal_domain="development",
        )


def test_task_domain_binding_ignores_goal_domain_when_system_domain_exists(tmp_path: Path) -> None:
    binding = bind_task_domain(
        base_dir=tmp_path,
        task_id="task:test",
        requested_domain="domain.general",
        task_goal_domain="development",
    )

    payload = binding.to_dict()
    assert payload["bound_domain_id"] == "domain.general"
    assert payload["diagnostics"]["task_goal_domain_ignored"] == "development"
    assert payload["diagnostics"]["agent_can_select_domain"] is False
    assert payload["diagnostics"]["domain_binding_source_must_be_system"] is True


