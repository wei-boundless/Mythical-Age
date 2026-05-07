from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from orchestration.runtime_loop.artifact_refs import ArtifactRefIndex
from orchestration.runtime_loop.continuation_inputs import ContinuationInputBinder
from orchestration.runtime_loop.continuation_policy import CoordinationStageContract


class _Index:
    def list_task_runs(self):
        return [
            SimpleNamespace(
                task_run_id="run:bible",
                task_id="taskinst:1:novel_bible_build",
                task_contract_ref="task.writing.novel_bible_build",
                updated_at=10,
            ),
            SimpleNamespace(
                task_run_id="run:volume",
                task_id="taskinst:2:volume_planning",
                task_contract_ref="task.writing.volume_planning",
                updated_at=20,
            ),
        ]


class _Trace:
    def get_trace(self, task_run_id: str, *, include_payloads: bool = False, include_model_messages: bool = False):
        return {
            "run:bible": {"task_result": {"output_refs": ["ref:novel_bible"]}},
            "run:volume": {"task_result": {"step_runs": [{"output_refs": ["ref:volume_plan"]}]}},
        }.get(task_run_id)


def test_continuation_input_binder_uses_stage_contract_refs() -> None:
    binder = ContinuationInputBinder(ArtifactRefIndex(state_index=_Index(), trace_reader=_Trace()))
    contract = CoordinationStageContract(
        stage_id="chapter_pipeline",
        task_ref="task.writing.chapter_drafting",
        required_inputs=("context_refs",),
        input_bindings=(
            {
                "input_key": "context_refs",
                "source": "collect",
                "required": True,
                "items": [
                    {"source": "latest_output", "task_ref": "task.writing.novel_bible_build"},
                    {"source": "latest_output", "task_ref": "task.writing.volume_planning"},
                ],
            },
        ),
    )

    result = binder.bind(stage_contract=contract, inherited_inputs={"artifact_root": "artifacts"})

    assert result.blocked is False
    assert result.explicit_inputs["context_refs"] == ["ref:novel_bible", "ref:volume_plan"]
    assert result.explicit_inputs["artifact_root"] == "artifacts"


def test_continuation_input_binder_blocks_missing_required_refs() -> None:
    binder = ContinuationInputBinder(ArtifactRefIndex(state_index=_Index(), trace_reader=_Trace()))
    contract = CoordinationStageContract(
        stage_id="volume_planning",
        task_ref="task.writing.volume_planning",
        required_inputs=("project_spec_ref",),
        input_bindings=(
            {
                "input_key": "project_spec_ref",
                "source": "latest_output",
                "task_ref": "task.writing.longform_novel_project",
                "required": True,
            },
        ),
    )

    result = binder.bind(stage_contract=contract)

    assert result.blocked is True
    assert result.missing_required_inputs == ("project_spec_ref",)


def test_continuation_input_binder_uses_named_stage_outputs() -> None:
    binder = ContinuationInputBinder(ArtifactRefIndex(state_index=_Index(), trace_reader=_Trace()))
    contract = CoordinationStageContract(
        stage_id="chapter_pipeline",
        task_ref="task.writing.chapter_drafting",
        required_inputs=("chapter_plan_ref", "context_refs"),
        input_bindings=(
            {
                "input_key": "chapter_plan_ref",
                "source": "stage_output",
                "output_key": "chapter_plan_ref",
                "required": True,
            },
            {
                "input_key": "context_refs",
                "source": "collect",
                "required": True,
                "items": [
                    {"source": "stage_output", "output_key": "novel_bible_ref"},
                    {"source": "stage_output", "output_key": "volume_plan_ref"},
                    {"source": "stage_output", "output_key": "chapter_plan_ref"},
                ],
            },
        ),
    )

    result = binder.bind(
        stage_contract=contract,
        stage_outputs={
            "novel_bible_ref": "ref:novel_bible",
            "volume_plan_ref": "ref:volume_plan",
            "chapter_plan_ref": "ref:chapter_plan",
        },
    )

    assert result.blocked is False
    assert result.explicit_inputs["chapter_plan_ref"] == "ref:chapter_plan"
    assert result.explicit_inputs["context_refs"] == ["ref:novel_bible", "ref:volume_plan", "ref:chapter_plan"]
