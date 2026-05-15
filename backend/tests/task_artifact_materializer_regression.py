from pathlib import Path

from orchestration.runtime_loop.task_artifact_materializer import materialize_task_artifacts


def _base_policy(target: str) -> dict:
    return {
        "artifact_policy": {
            "enabled": True,
            "required": True,
            "default_artifact_root": "output/novel_artifacts/simple_novel/runs",
            "subdir_template": "{session_id}",
            "artifact_target": target,
            "artifacts": [
                {
                    "path": target,
                    "required": True,
                    "content_source": "final_content",
                    "fallback_to_full_content": False,
                }
            ],
        }
    }


def test_project_brief_stage_materializes_brief_and_target_artifact(tmp_path: Path) -> None:
    result = materialize_task_artifacts(
        workspace_root=tmp_path,
        task_run_id="taskrun:test:project_brief:0001",
        session_id="session-brief",
        task_ref="task.writing.simple_novel.project_brief",
        coordination_run_id="coordrun:test",
        final_content="# 项目启动包\n\n这是启动包正文。",
        user_message="请生成项目启动包。",
        explicit_inputs={"title": "洪荒时代"},
        task_policy=_base_policy("project_brief.md"),
    )

    artifact_root = tmp_path / "output" / "novel_artifacts" / "simple_novel" / "runs" / "session-brief"
    assert (artifact_root / "00_project_brief.md").exists()
    assert (artifact_root / "project_brief.md").exists()
    assert "00_project_brief.md" in result.created_files
    assert "project_brief.md" in result.created_files


def test_non_project_brief_stage_does_not_emit_brief_versions(tmp_path: Path) -> None:
    result = materialize_task_artifacts(
        workspace_root=tmp_path,
        task_run_id="taskrun:test:world_candidate:0001",
        session_id="session-world",
        task_ref="task.writing.simple_novel.world_candidate",
        coordination_run_id="coordrun:test",
        final_content="# 世界观候选\n\n这是世界观正文。",
        user_message="请生成世界观候选。",
        explicit_inputs={"title": "洪荒时代"},
        task_policy=_base_policy("world/world_candidate.md"),
    )

    artifact_root = tmp_path / "output" / "novel_artifacts" / "simple_novel" / "runs" / "session-world"
    assert not (artifact_root / "00_project_brief.md").exists()
    assert not any(artifact_root.glob("00_project_brief_v*.md"))
    assert (artifact_root / "world" / "world_candidate.md").exists()
    assert all(not item.startswith("00_project_brief") for item in result.created_files)


def test_failed_empty_stage_does_not_create_misleading_required_artifact(tmp_path: Path) -> None:
    result = materialize_task_artifacts(
        workspace_root=tmp_path,
        task_run_id="taskrun:test:outline_candidate:0001",
        session_id="session-outline-failed",
        task_ref="task.writing.simple_novel.outline_candidate",
        coordination_run_id="coordrun:test",
        final_content="",
        user_message="请生成大纲候选。",
        explicit_inputs={"title": "洪荒时代"},
        task_policy=_base_policy("outline/outline_candidate.md"),
        task_status="failed",
        terminal_reason="executor_failed",
        task_diagnostics={
            "last_error": {
                "message": "模型配置有误，请检查提供商和密钥设置。",
                "detail": "401 Unauthorized from upstream provider",
                "code": "configuration",
            }
        },
    )

    artifact_root = tmp_path / "output" / "novel_artifacts" / "simple_novel" / "runs" / "session-outline-failed"
    assert not (artifact_root / "outline" / "outline_candidate.md").exists()
    assert "outline/outline_candidate.md" in result.skipped_files
    report_path = artifact_root / "debug" / "run_report_task-writing-simple-novel-outline-candidate.md"
    assert report_path.exists()
    report_text = report_path.read_text(encoding="utf-8")
    assert "失败诊断" in report_text
    assert "401 Unauthorized from upstream provider" in report_text
