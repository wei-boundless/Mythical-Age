from __future__ import annotations

import json
from pathlib import Path

from runtime.memory.state_index import RuntimeStateIndex
from runtime.shared.models import AgentRun, TaskRun
from project_layout import ProjectLayout
from soul.activity_service import SoulActivityService


def test_soul_work_log_is_read_only_summary_view(tmp_path: Path) -> None:
    base_dir = tmp_path / "backend"
    projection_dir = base_dir / "soul" / "projections"
    projection_dir.mkdir(parents=True)
    (projection_dir / "catalog.json").write_text(
        json.dumps(
            {
                "selected_projection_id": "projection.worker.summary",
                "cards": [
                    {
                        "projection_id": "projection.worker.summary",
                        "soul_id": "hebo",
                        "title": "摘要投影",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    task_run_id = "taskrun:soul-activity:1"
    index = RuntimeStateIndex(ProjectLayout.from_backend_dir(base_dir).runtime_state_dir)
    index.upsert_task_run(
        TaskRun(
            task_run_id=task_run_id,
            session_id="session:soul-activity",
            task_id="task.summary",
            status="completed",
            created_at=10.0,
            updated_at=20.0,
            diagnostics={
                "task_title": "整理材料",
                "projection_id": "projection.worker.summary",
            },
        )
    )
    index.upsert_agent_run(
        AgentRun(
            agent_run_id="agrun:soul-activity:1",
            task_run_id=task_run_id,
            agent_id="agent:hebo",
            agent_profile_id="summary_agent",
            status="completed",
            created_at=11.0,
            updated_at=19.0,
        )
    )

    view = SoulActivityService(base_dir).work_log("hebo").to_dict()

    assert view["read_model_only"] is True
    assert view["stores_memory_content"] is False
    assert view["event_count"] == 1
    event = view["events"][0]
    assert event["soul_id"] == "hebo"
    assert event["projection_id"] == "projection.worker.summary"
    assert event["task_run_id"] == task_run_id
    assert event["title"] == "整理材料"
    assert event["summary"] == "整理材料：completed"
    assert "memory_content" not in event
    assert "content" not in event


def test_soul_work_log_does_not_guess_unmapped_projection(tmp_path: Path) -> None:
    base_dir = tmp_path / "backend"
    (base_dir / "soul" / "projections").mkdir(parents=True)
    (base_dir / "soul" / "projections" / "catalog.json").write_text(
        json.dumps({"selected_projection_id": "", "cards": []}),
        encoding="utf-8",
    )
    RuntimeStateIndex(ProjectLayout.from_backend_dir(base_dir).runtime_state_dir).upsert_task_run(
        TaskRun(
            task_run_id="taskrun:soul-activity:unmapped",
            session_id="session:soul-activity",
            task_id="task.unmapped",
            status="completed",
            diagnostics={"projection_id": "projection.unknown"},
        )
    )

    view = SoulActivityService(base_dir).work_log("hebo").to_dict()

    assert view["event_count"] == 0


