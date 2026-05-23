from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from runtime.unit_runtime.sandbox_policy import (  # noqa: E402
    prepare_runtime_sandbox_policy,
    prepare_runtime_sandbox_policy_for_turn,
    sandbox_workspace_key,
)


class _StateIndexStub:
    def __init__(self, task_runs: list[object]) -> None:
        self._task_runs = task_runs

    def list_session_task_runs(self, _session_id: str) -> list[object]:
        return list(self._task_runs)


class _EventLogStub:
    def __init__(self, events_by_task_run_id: dict[str, list[object]]) -> None:
        self._events_by_task_run_id = events_by_task_run_id

    def list_events(self, task_run_id: str) -> list[object]:
        return list(self._events_by_task_run_id.get(task_run_id, []))


def test_sandbox_policy_uses_output_scope_as_workspace_key(tmp_path: Path) -> None:
    task_contract = {
        "task_requirement_contract": {
            "execution_obligation": {
                "required_output_paths": ["output/novel_artifacts/modular_novel/world/world_candidate.md"],
            },
        },
    }

    workspace_key = sandbox_workspace_key(
        session_id="session-writing",
        task_run_id="taskrun-001",
        task_contract=task_contract,
        user_message="继续写 output/novel_artifacts/modular_novel/world/world_candidate.md",
    )
    policy = prepare_runtime_sandbox_policy(
        root_dir=tmp_path / "backend",
        session_id="session-writing",
        task_run_id="taskrun-001",
        task_contract=task_contract,
        user_message="继续写 output/novel_artifacts/modular_novel/world/world_candidate.md",
        selected_recipe_payload={"metadata": {"sandbox_policy": {"enabled": True}}},
        task_selection={},
    )

    assert workspace_key == "session:session-writing:scope:output/novel_artifacts/modular_novel/world"
    assert policy["workspace_key"] == workspace_key
    assert policy["enabled"] is True
    assert str(policy["sandbox_root"]).endswith("workspace")
    assert Path(policy["sandbox_root"]).exists()


def test_sandbox_policy_inherits_previous_workspace_for_compatible_professional_turn(tmp_path: Path) -> None:
    previous_key = "session:session-writing:scope:output/novel_artifacts/modular_novel/world"
    previous_task_run = SimpleNamespace(task_run_id="taskrun-previous", updated_at=2.0, created_at=1.0)
    previous_event = SimpleNamespace(
        event_type="runtime_sandbox_prepared",
        payload={"sandbox_policy": {"enabled": True, "workspace_key": previous_key}},
    )
    task_contract = {
        "task_requirement_contract": {
            "execution_obligation": {
                "required_output_paths": ["output/novel_artifacts/modular_novel/world/world_candidate_v2.md"],
            },
        },
    }

    policy = prepare_runtime_sandbox_policy_for_turn(
        root_dir=tmp_path / "backend",
        session_id="session-writing",
        task_run_id="taskrun-current",
        task_contract=task_contract,
        user_message="继续修正世界观文件",
        selected_recipe_payload={"metadata": {"sandbox_policy": {"enabled": True}}},
        task_selection={"interaction_mode": "professional_mode"},
        state_index=_StateIndexStub([previous_task_run]),
        event_log=_EventLogStub({"taskrun-previous": [previous_event]}),
    )

    assert policy["workspace_key"] == previous_key
    assert previous_key.replace(":", "_").replace("/", "_") in str(policy["sandbox_root"])


def test_sandbox_policy_does_not_inherit_workspace_for_unrelated_scope(tmp_path: Path) -> None:
    previous_key = "session:session-writing:scope:output/novel_artifacts/modular_novel/world"
    previous_task_run = SimpleNamespace(task_run_id="taskrun-previous", updated_at=2.0, created_at=1.0)
    previous_event = SimpleNamespace(
        event_type="runtime_sandbox_prepared",
        payload={"sandbox_policy": {"enabled": True, "workspace_key": previous_key}},
    )
    task_contract = {
        "task_requirement_contract": {
            "execution_obligation": {
                "required_output_paths": ["output/novel_artifacts/modular_novel/volume_001/outline.md"],
            },
        },
    }

    policy = prepare_runtime_sandbox_policy_for_turn(
        root_dir=tmp_path / "backend",
        session_id="session-writing",
        task_run_id="taskrun-current",
        task_contract=task_contract,
        user_message="写第一卷大纲",
        selected_recipe_payload={"metadata": {"sandbox_policy": {"enabled": True}}},
        task_selection={"interaction_mode": "professional_mode"},
        state_index=_StateIndexStub([previous_task_run]),
        event_log=_EventLogStub({"taskrun-previous": [previous_event]}),
    )

    assert policy["workspace_key"] == "session:session-writing:scope:output/novel_artifacts/modular_novel/volume_001"
