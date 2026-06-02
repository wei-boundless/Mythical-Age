from __future__ import annotations

from types import SimpleNamespace

from harness.loop.work_rollout import append_work_rollout_item, work_rollout_ref, work_rollout_summary


class _RuntimeObjects:
    def __init__(self) -> None:
        self._objects: dict[str, dict] = {}

    def put_object(self, kind: str, object_id: str, payload: dict) -> str:
        ref = work_rollout_ref(object_id) if kind == "work_rollout" else f"rtobj:{kind}:{object_id}"
        self._objects[ref] = dict(payload)
        return ref

    def get_object(self, ref: str) -> dict:
        return dict(self._objects.get(ref) or {})


def test_model_invisible_rollout_item_stays_out_of_model_history() -> None:
    host = SimpleNamespace(runtime_objects=_RuntimeObjects())
    task_run = SimpleNamespace(
        task_run_id="taskrun:rollout-visibility",
        session_id="session:rollout-visibility",
        task_id="task:rollout-visibility",
        status="running",
        latest_event_offset=-1,
        latest_checkpoint_ref="",
        diagnostics={},
    )

    append_work_rollout_item(
        host,
        task_run=task_run,
        item_type="progress",
        title="确认下一步",
        status="running",
        summary="继续读取后半部分。",
        payload={"model_visible": False},
    )
    append_work_rollout_item(
        host,
        task_run=task_run,
        item_type="progress",
        title="执行操作",
        status="running",
        summary="工具调用已完成，正在根据结果继续。",
    )

    summary = work_rollout_summary(host, task_run.task_run_id)

    assert [item["summary"] for item in summary["progress_timeline"]] == [
        "继续读取后半部分。",
        "工具调用已完成，正在根据结果继续。",
    ]
    assert [item["summary"] for item in summary["model_visible_history"]] == [
        "工具调用已完成，正在根据结果继续。",
    ]
