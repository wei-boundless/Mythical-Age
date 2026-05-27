from pathlib import Path

from harness.loop.artifact_materializer import materialize_task_artifacts


def _base_policy(target: str) -> dict:
    return {
        "artifact_policy": {
            "enabled": True,
            "required": True,
            "default_artifact_root": "output/novel_artifacts/modular_novel/runs",
            "subdir_template": "{project_id}",
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


def _draft_policy(target: str) -> dict:
    return {
        "artifact_policy": {
            "enabled": True,
            "required": True,
            "default_artifact_root": "output/novel_artifacts/modular_novel/runs",
            "subdir_template": "{project_id}",
            "artifacts": [
                {
                    "path": target,
                    "required": True,
                    "content_source": "section",
                    "section_keys": ["章节正文候选"],
                    "stop_section_keys": ["承接说明", "本章目标完成说明", "公开摘要"],
                    "fallback_to_full_content": False,
                },
                {
                    "path": target.replace("draft_round_001.md", "draft_manifest_round_001.md"),
                    "required": False,
                    "content_source": "section",
                    "section_keys": ["承接说明", "本章目标完成说明", "公开摘要"],
                    "fallback_to_full_content": False,
                },
            ],
        }
    }


def test_project_brief_stage_materializes_only_target_artifact(tmp_path: Path) -> None:
    result = materialize_task_artifacts(
        workspace_root=tmp_path,
        task_run_id="taskrun:test:project_brief:0001",
        session_id="session-brief",
        task_ref="task.writing.modular_novel.node.project_brief",
        coordination_run_id="coordrun:test",
        final_content="# 项目启动包\n\n这是启动包正文。",
        user_message="请生成项目启动包。",
        explicit_inputs={"title": "洪荒时代", "project_id": "project:test-honghuang"},
        task_policy=_base_policy("project_brief.md"),
    )

    artifact_root = tmp_path / "output" / "novel_artifacts" / "modular_novel" / "runs" / "project-test-honghuang"
    assert not (artifact_root / "00_project_brief.md").exists()
    assert (artifact_root / "project_brief.md").exists()
    assert all(not item.startswith("00_project_brief") for item in result.created_files)
    assert "project_brief.md" in result.created_files


def test_non_project_brief_stage_does_not_emit_brief_versions(tmp_path: Path) -> None:
    result = materialize_task_artifacts(
        workspace_root=tmp_path,
        task_run_id="taskrun:test:world_candidate:0001",
        session_id="session-world",
        task_ref="task.writing.modular_novel.node.world_design",
        coordination_run_id="coordrun:test",
        final_content="# 世界观候选\n\n这是世界观正文。",
        user_message="请生成世界观候选。",
        explicit_inputs={"title": "洪荒时代", "project_id": "project:test-honghuang"},
        task_policy=_base_policy("world/world_candidate.md"),
    )

    artifact_root = tmp_path / "output" / "novel_artifacts" / "modular_novel" / "runs" / "project-test-honghuang"
    assert not (artifact_root / "00_project_brief.md").exists()
    assert not any(artifact_root.glob("00_project_brief_v*.md"))
    assert (artifact_root / "world" / "world_candidate.md").exists()
    assert all(not item.startswith("00_project_brief") for item in result.created_files)


def test_artifact_root_does_not_append_session_twice(tmp_path: Path) -> None:
    result = materialize_task_artifacts(
        workspace_root=tmp_path,
        task_run_id="taskrun:test:chapter_draft:0001",
        session_id="session-chapters",
        task_ref="task.writing.modular_novel.node.chapter_draft",
        coordination_run_id="coordrun:test",
        final_content="# 第十一章\n\n正文。",
        user_message="请生成章节。",
        explicit_inputs={
            "artifact_root": "output/novel_artifacts/modular_novel/runs/session-chapters",
            "project_id": "project:test-honghuang",
            "batch_index": 2,
            "batch_start_index": 11,
            "batch_end_index": 20,
        },
        task_policy=_base_policy("chapters/batch_{batch_index:03d}_chapters_{batch_start_index:03d}_{batch_end_index:03d}/draft_round_001.md"),
    )

    artifact_root = tmp_path / "output" / "novel_artifacts" / "modular_novel" / "runs" / "session-chapters"
    assert result.artifact_root == "output/novel_artifacts/modular_novel/runs/session-chapters"
    assert (artifact_root / "chapters" / "batch_002_chapters_011_020" / "draft_round_001.md").exists()
    assert not (artifact_root / "session-chapters").exists()


def test_explicit_artifact_root_is_stable_across_reruns(tmp_path: Path) -> None:
    explicit_root = "output/novel_artifacts/modular_novel/runs/project-test-honghuang"
    policy = _base_policy("world/world_candidate_round_{round_index:03d}.md")

    first = materialize_task_artifacts(
        workspace_root=tmp_path,
        task_run_id="taskrun:test:world_design:first",
        session_id="session-stable",
        task_ref="task.writing.modular_novel.node.world_design",
        coordination_run_id="coordrun:test",
        final_content="# 世界观候选\n\n第一版。",
        user_message="请生成世界观候选。",
        explicit_inputs={"artifact_root": explicit_root, "project_id": "project:test-honghuang", "round_index": 1},
        task_policy=policy,
        task_status="completed",
    )
    second = materialize_task_artifacts(
        workspace_root=tmp_path,
        task_run_id="taskrun:test:world_design:revision",
        session_id="session-stable",
        task_ref="task.writing.modular_novel.node.world_design",
        coordination_run_id="coordrun:test",
        final_content="# 世界观候选\n\n返修版。",
        user_message="请返修世界观候选。",
        explicit_inputs={"artifact_root": explicit_root, "project_id": "project:test-honghuang", "round_index": 2},
        task_policy=policy,
        task_status="completed",
    )

    artifact_root = tmp_path / "output" / "novel_artifacts" / "modular_novel" / "runs" / "project-test-honghuang"
    assert first.artifact_root == explicit_root
    assert second.artifact_root == explicit_root
    assert (artifact_root / "world" / "world_candidate_round_001.md").exists()
    assert (artifact_root / "world" / "world_candidate_round_002.md").exists()
    assert not (artifact_root / "world" / "world_candidate.md").exists()
    assert not any(path.name.startswith("taskrun-test-world-design") for path in artifact_root.iterdir())


def test_failed_empty_stage_does_not_create_misleading_required_artifact(tmp_path: Path) -> None:
    result = materialize_task_artifacts(
        workspace_root=tmp_path,
        task_run_id="taskrun:test:outline_candidate:0001",
        session_id="session-outline-failed",
        task_ref="task.writing.modular_novel.node.outline_design",
        coordination_run_id="coordrun:test",
        final_content="",
        user_message="请生成大纲候选。",
        explicit_inputs={"title": "洪荒时代", "project_id": "project:test-honghuang"},
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

    artifact_root = tmp_path / "output" / "novel_artifacts" / "modular_novel" / "runs" / "project-test-honghuang"
    assert not (artifact_root / "outline" / "outline_candidate.md").exists()
    assert "outline/outline_candidate.md" in result.skipped_files
    report_path = artifact_root / "debug" / "run_report_task-writing-modular-novel-node-outline-design.md"
    assert report_path.exists()
    report_text = report_path.read_text(encoding="utf-8")
    assert "失败诊断" in report_text
    assert "401 Unauthorized from upstream provider" in report_text


def test_rejected_stage_artifact_is_isolated_from_official_output(tmp_path: Path) -> None:
    result = materialize_task_artifacts(
        workspace_root=tmp_path,
        task_run_id="taskrun:test:chapter_draft:rejected",
        session_id="session-rejected",
        task_ref="task.writing.modular_novel.node.chapter_draft",
        coordination_run_id="coordrun:test",
        final_content="# 【章节正文候选】\n\n第1章 正文不足。",
        user_message="写第1-10章。",
        explicit_inputs={
            "artifact_root": "output/novel_artifacts/modular_novel/runs/session-rejected",
            "project_id": "project:test-honghuang",
            "batch_start_index": 1,
            "batch_end_index": 10,
            "round_index": 6,
        },
        task_policy=_base_policy("volume_001/chapters/chapter_001_010/draft_round_006.md"),
        task_status="completed",
        acceptance_status="rejected",
        stage_id="chapter_draft",
        request_id="nodeexec:test:chapter_draft:old",
    )

    artifact_root = tmp_path / "output" / "novel_artifacts" / "modular_novel" / "runs" / "session-rejected"
    assert not (artifact_root / "volume_001" / "chapters" / "chapter_001_010" / "draft_round_006.md").exists()
    assert (
        artifact_root
        / "rejected"
        / "chapter-draft"
        / "batch_001_010_round_006"
        / "nodeexec-test-chapter-draft-old"
        / "volume_001"
        / "chapters"
        / "chapter_001_010"
        / "draft_round_006.md"
    ).exists()
    assert all("/rejected/" in ref for ref in result.artifact_refs)


def test_chapter_draft_artifact_splits_bracket_sections_without_debug_wrapper(tmp_path: Path) -> None:
    final_content = "\n\n".join(
        [
            "# 【章节正文候选】",
            "## 第1章「泽中」\n正文一。",
            "## 第2章「灾异」\n正文二。",
            "## 【承接说明】\n只允许进入 manifest。",
            "## 【公开摘要】\n摘要也只允许进入 manifest。",
        ]
    )

    result = materialize_task_artifacts(
        workspace_root=tmp_path,
        task_run_id="taskrun:test:chapter_draft:split",
        session_id="session-split",
        task_ref="task.writing.modular_novel.node.chapter_draft",
        coordination_run_id="coordrun:test",
        final_content=final_content,
        user_message="写第1-2章。",
        explicit_inputs={
            "project_id": "project:test-honghuang",
            "batch_start_index": 1,
            "batch_end_index": 2,
        },
        task_policy=_draft_policy("volume_001/chapters/chapter_001_002/draft_round_001.md"),
        task_status="completed",
    )

    artifact_root = tmp_path / "output" / "novel_artifacts" / "modular_novel" / "runs" / "project-test-honghuang"
    draft_path = artifact_root / "volume_001" / "chapters" / "chapter_001_002" / "draft_round_001.md"
    manifest_path = artifact_root / "volume_001" / "chapters" / "chapter_001_002" / "draft_manifest_round_001.md"
    assert draft_path.exists()
    assert manifest_path.exists()
    draft_text = draft_path.read_text(encoding="utf-8")
    manifest_text = manifest_path.read_text(encoding="utf-8")
    assert "本文件由任务产物规则创建" not in draft_text
    assert "第1章" in draft_text
    assert "第2章" in draft_text
    assert "承接说明" not in draft_text
    assert "公开摘要" not in draft_text
    assert "承接说明" in manifest_text
    assert "公开摘要" in manifest_text
    assert "draft_round_001.md" in result.created_files
