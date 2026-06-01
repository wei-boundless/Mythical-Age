from __future__ import annotations

from task_system.contracts.execution_obligation import build_execution_obligation
from request_intent.request_signals import build_request_signals
from task_system.services.assembly_support import build_runtime_task_intent_contract


def test_execution_obligation_does_not_infer_write_or_pytest_from_user_text() -> None:
    obligation = build_execution_obligation(
        session_id="session-obligation",
        task_id="task-repair",
        user_goal=(
            "追踪 backend/tests/fixtures/professional_task_suite/failing_sixty_turn_summary.json 的失败原因，"
            "修复代码，然后运行 pytest 验证。"
        ),
    )
    payload = obligation.to_dict()

    assert payload["authority"] == "runtime.execution_obligation"
    assert payload["required_reads"][0]["path"] == "backend/tests/fixtures/professional_task_suite/failing_sixty_turn_summary.json"
    assert payload["required_writes"] == []
    assert payload["required_commands"] == []
    assert payload["required_verifications"] == []
    assert payload["extraction_evidence"]["natural_language_action_inference_removed"] is True
    assert payload["extraction_evidence"]["execution_actions_compiled_from"] == []


def test_execution_obligation_forbid_write_wins_for_analysis_only_goal() -> None:
    contract = build_runtime_task_intent_contract(
        session_id="session-obligation-forbid",
        task_id="task-analysis-only",
        user_goal=(
            "先分析 backend/tests/fixtures/professional_task_suite/failing_sixty_turn_summary.json 的失败原因，"
            "不要改代码，也不要修改文件。"
        ),
        query_understanding=build_request_signals(
            "先分析 backend/tests/fixtures/professional_task_suite/failing_sixty_turn_summary.json 的失败原因，"
            "不要改代码，也不要修改文件。"
        ).to_dict(),
        current_turn_context={
            "model_turn_decision": _decision(
                action_intent="read_context",
                work_mode="read_only_analysis",
                interaction_intent="inspect",
                target_objects=["backend/tests/fixtures/professional_task_suite/failing_sixty_turn_summary.json"],
                forbidden_actions=["modify_code", "write_file", "edit_file"],
            ),
            "task_goal_spec": {
                "authority": "agent_runtime.model_turn_goal_projection",
                "task_goal_type": "inspection",
                "task_domain": "workspace",
                "forbidden_actions": ["modify_code", "write_file", "edit_file"],
            },
        },
    )
    obligation = contract.execution_obligation
    semantic = contract.task_requirement_contract

    assert obligation["required_reads"]
    assert obligation["required_writes"] == []
    assert "modify_code" in obligation["forbidden_actions"]
    assert "modify_code" in semantic["forbidden_actions"]
    assert "apply_real_change" not in semantic["required_actions"]
    assert obligation["extraction_evidence"]["forbid_write_authority"] == "model_turn_decision_or_boundary_policy"
    assert obligation["extraction_evidence"]["hard_write_authority"] == "operation_gate_and_sandbox_policy"
    assert obligation["extraction_evidence"]["natural_language_write_forbid_signal"] is True
    assert obligation["extraction_evidence"]["structured_write_forbidden"] is True


def test_execution_obligation_trims_material_path_before_following_chinese_clause() -> None:
    obligation = build_execution_obligation(
        session_id="session-material-path",
        task_id="task-material-path",
        user_goal=(
            "请结合 knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf 和 "
            "knowledge/E-commerce Data/inventory.xlsx，写一份风险与行动建议。"
        ),
    ).to_dict()

    paths = [item["path"] for item in obligation["required_reads"]]
    assert "knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf" in paths
    assert "knowledge/E-commerce Data/inventory.xlsx" in paths
    assert not any("写一份" in path or "行动建议" in path for path in paths)


def test_execution_obligation_treats_structured_game_files_as_writes_not_reads() -> None:
    obligation = build_execution_obligation(
        session_id="session-game-writes",
        task_id="task-game-writes",
        user_goal=(
            "请在 sandbox overlay 中完成多文件网页工程，目录必须是 frontend/public/games/snake_plus/。"
            "必须写入 index.html、styles.css、game.js、README.md。"
        ),
        current_turn_context={
            "model_turn_decision": {
                "resource_contract": {
                    "required_write_files": [
                        "frontend/public/games/snake_plus/index.html",
                        "frontend/public/games/snake_plus/styles.css",
                        "frontend/public/games/snake_plus/game.js",
                        "frontend/public/games/snake_plus/README.md",
                    ],
                }
            }
        },
    ).to_dict()

    assert obligation["required_reads"] == []
    assert [item["path"] for item in obligation["required_writes"]] == [
        "frontend/public/games/snake_plus/index.html",
        "frontend/public/games/snake_plus/styles.css",
        "frontend/public/games/snake_plus/game.js",
        "frontend/public/games/snake_plus/README.md",
    ]
    assert obligation["extraction_evidence"]["resource_contract_used"] is True


def test_execution_obligation_extracts_input_material_and_uses_structured_output_file() -> None:
    obligation = build_execution_obligation(
        session_id="session-read-write-same-sentence",
        task_id="task-review-report",
        user_goal=(
            "请根据 tests/fixtures/professional_task_suite/node_status_filter_contract.json，"
            "审查状态筛选功能并写入 output/vibe-code-smoke/status-filter-review.md。"
        ),
        current_turn_context={
            "model_turn_decision": {
                "resource_contract": {
                    "required_write_files": ["output/vibe-code-smoke/status-filter-review.md"],
                }
            }
        },
    ).to_dict()

    assert [item["path"] for item in obligation["required_reads"]] == [
        "tests/fixtures/professional_task_suite/node_status_filter_contract.json",
    ]
    assert "output/vibe-code-smoke/status-filter-review.md" in [
        item["path"] for item in obligation["required_writes"]
    ]


def test_execution_obligation_does_not_treat_output_path_after_write_marker_as_material() -> None:
    obligation = build_execution_obligation(
        session_id="session-read-write-verify",
        task_id="task-code-fix-report",
        user_goal=(
            "请先读取 tests/fixtures/professional_task_suite/README.md，"
            "再写入 output/vibe-code-smoke/verify-drift-report.md，"
            "然后用 terminal 验证文件存在。"
        ),
        current_turn_context={
            "model_turn_decision": _decision(
                action_intent="edit_workspace",
                work_mode="implementation",
                interaction_intent="modify",
                task_goal_type="code_fix_execution",
                completion_criteria=["verify the written output file exists with terminal"],
            ),
            "semantic_task_type": "code_fix_execution",
        },
    ).to_dict()

    read_paths = [item["path"] for item in obligation["required_reads"]]
    assert read_paths == ["tests/fixtures/professional_task_suite/README.md"]
    assert "output/vibe-code-smoke/verify-drift-report.md" not in read_paths


def test_task_requirement_contract_filters_output_path_from_material_scan_for_code_fix() -> None:
    contract = build_runtime_task_intent_contract(
        session_id="session-contract-read-write",
        task_id="task-code-fix-report",
        user_goal=(
            "请先读取 tests/fixtures/professional_task_suite/README.md，"
            "再写入 output/vibe-code-smoke/verify-drift-report.md，"
            "然后用 terminal 验证文件存在。"
        ),
        query_understanding=build_request_signals(
            "请先读取 tests/fixtures/professional_task_suite/README.md，"
            "再写入 output/vibe-code-smoke/verify-drift-report.md，"
            "然后用 terminal 验证文件存在。"
        ).to_dict(),
        current_turn_context={
            "model_turn_decision": _decision(
                action_intent="edit_workspace",
                work_mode="implementation",
                interaction_intent="modify",
                task_goal_type="code_fix_execution",
                completion_criteria=["verify the written output file exists with terminal"],
            ),
            "semantic_task_type": "code_fix_execution",
        },
    )
    semantic = contract.task_requirement_contract
    material_paths = [item["path"] for item in semantic["materials"]]

    assert material_paths == ["tests/fixtures/professional_task_suite/README.md"]
    assert "output/vibe-code-smoke/verify-drift-report.md" not in material_paths


def test_execution_obligation_write_deliverables_do_not_leak_code_fix_terms_into_artifacts() -> None:
    obligation = build_execution_obligation(
        session_id="session-artifact-delivery",
        task_id="task-artifact",
        user_goal="写入 output/vibe-code-smoke/report.md，然后验证文件存在。",
        current_turn_context={
            "model_turn_decision": _decision(
                action_intent="edit_workspace",
                work_mode="implementation",
                interaction_intent="create",
                task_goal_type="artifact_delivery",
                completion_criteria=["verify the written output file exists with terminal"],
                resource_contract={"required_write_files": ["output/vibe-code-smoke/report.md"]},
            ),
            "semantic_task_type": "artifact_delivery",
        },
    ).to_dict()

    assert "change_summary" not in obligation["required_deliverables"]
    assert "changed_files" not in obligation["required_deliverables"]
    assert "verification_result_or_limitation" in obligation["required_deliverables"]


def test_execution_obligation_derives_browser_game_requirements_from_goal_frame() -> None:
    message = "做一个可运行的浏览器端 2D 肉鸽游戏垂直切片，需要真实接入至少一个图像资产。"
    goal_frame = {
        "authority": "agent_runtime.model_turn_goal_projection",
        "task_goal_type": "game_vertical_slice_delivery",
        "task_domain": "development",
        "required_verifications": [{"kind": "browser_verification"}],
        "required_capabilities": ["browser", "asset_integration"],
    }
    obligation = build_execution_obligation(
        session_id="session-game-goal-frame",
        task_id="task-game-goal-frame",
        user_goal=message,
        current_turn_context={"task_goal_spec": goal_frame},
    ).to_dict()

    write_kinds = {item["kind"] for item in obligation["required_writes"]}
    verification_kinds = {item["kind"] for item in obligation["required_verifications"]}
    command_kinds = {item["kind"] for item in obligation["required_commands"]}

    assert "workspace_change" in write_kinds
    assert "asset_integration" in write_kinds
    assert "browser_or_runtime_check" in command_kinds
    assert "browser_verification" in verification_kinds
    assert "runnable_artifact_refs" in obligation["required_deliverables"]
    assert obligation["extraction_evidence"]["profile_obligation"]["matched"] is True


def test_execution_obligation_scopes_do_not_modify_source_project_without_global_write_ban() -> None:
    obligation = build_execution_obligation(
        session_id="session-vibe-code",
        task_id="task-source-readonly-report",
        user_goal=(
            "请在 sandbox 中读取 .materials/source_projects/source_01/README.md 和 "
            ".materials/source_projects/source_01/backend/api/chat.py，不要修改源项目，"
            "然后写入 output/vibe-code-smoke/langchain-mini-chat-api-review.md。"
        ),
        current_turn_context={
            "model_turn_decision": {
                "resource_contract": {
                    "source_projects": [
                        {"path": ".materials/source_projects/source_01", "role": "source", "required": True}
                    ],
                    "required_read_files": [
                        ".materials/source_projects/source_01/README.md",
                        ".materials/source_projects/source_01/backend/api/chat.py",
                    ],
                    "required_write_files": ["output/vibe-code-smoke/langchain-mini-chat-api-review.md"],
                }
            }
        },
    ).to_dict()

    assert obligation["forbidden_actions"] == []
    assert [item["path"] for item in obligation["required_reads"]] == [
        ".materials/source_projects/source_01/README.md",
        ".materials/source_projects/source_01/backend/api/chat.py",
    ]
    assert [item["path"] for item in obligation["required_writes"]] == [
        "output/vibe-code-smoke/langchain-mini-chat-api-review.md",
    ]
    assert obligation["required_writes"][0]["write_scope_policy"] == "sandbox_or_target_only"
    assert obligation["extraction_evidence"]["scoped_write_constraints"][0]["target"] == "source_project"


def test_execution_obligation_keeps_contract_writes_without_target_projects() -> None:
    obligation = build_execution_obligation(
        session_id="session-vibe-code",
        task_id="task-contract-write-no-target",
        user_goal="写入 output/vibe-code-smoke/report.md。",
        current_turn_context={
            "model_turn_decision": {
                "resource_contract": {
                    "source_projects": [{"path": "D:/AI应用/agent-vibe-sandboxes/langchain-mini-clean"}],
                    "target_projects": [],
                    "required_write_files": ["output/vibe-code-smoke/report.md"],
                    "required_write_dirs": ["output/vibe-code-smoke"],
                }
            }
        },
    ).to_dict()

    assert [item["path"] for item in obligation["required_writes"]] == [
        "output/vibe-code-smoke/report.md",
        "output/vibe-code-smoke",
    ]


def test_execution_obligation_does_not_duplicate_target_project_prefix_for_qualified_writes() -> None:
    obligation = build_execution_obligation(
        session_id="session-vibe-code",
        task_id="task-qualified-target-writes",
        user_goal="写入浏览器游戏工程。",
        current_turn_context={
            "model_turn_decision": {
                "resource_contract": {
                    "target_projects": [{"path": "frontend/public/games/arcane_dungeon_studio"}],
                    "required_write_files": [
                        "frontend/public/games/arcane_dungeon_studio/index.html",
                        "frontend/public/games/arcane_dungeon_studio/game.js",
                    ],
                    "required_write_dirs": [
                        "frontend/public/games/arcane_dungeon_studio/assets",
                        "assets",
                    ],
                }
            }
        },
    ).to_dict()

    paths = [item["path"] for item in obligation["required_writes"]]
    assert "frontend/public/games/arcane_dungeon_studio/index.html" in paths
    assert "frontend/public/games/arcane_dungeon_studio/game.js" in paths
    assert "frontend/public/games/arcane_dungeon_studio/assets" in paths
    assert "frontend/public/games/arcane_dungeon_studio/frontend/public/games/arcane_dungeon_studio/index.html" not in paths
    assert "frontend/public/games/arcane_dungeon_studio/frontend/public/games/arcane_dungeon_studio/assets" not in paths


def test_execution_obligation_preserves_material_mount_paths_from_resource_contract() -> None:
    obligation = build_execution_obligation(
        session_id="session-vibe-code",
        task_id="task-mounted-material-read",
        user_goal="读取挂载材料并写报告。",
        current_turn_context={
            "model_turn_decision": {
                "resource_contract": {
                    "source_projects": [{"path": "D:/AI应用/agent-vibe-sandboxes/langchain-mini-clean"}],
                    "required_read_files": [
                        ".materials/source_projects/source_01/README.md",
                        ".materials/source_projects/source_01/backend/api/chat.py",
                    ],
                }
            }
        },
    ).to_dict()

    assert [item["path"] for item in obligation["required_reads"]] == [
        ".materials/source_projects/source_01/README.md",
        ".materials/source_projects/source_01/backend/api/chat.py",
    ]


def test_execution_obligation_global_no_file_write_marker_is_diagnostic_without_structured_forbid() -> None:
    obligation = build_execution_obligation(
        session_id="session-global-no-write",
        task_id="task-analysis-only",
        user_goal="只分析 backend/app.py，不要写任何文件，也不要生成报告文件。",
    ).to_dict()

    assert obligation["required_writes"] == []
    assert obligation["forbidden_actions"] == []
    assert obligation["extraction_evidence"]["natural_language_write_forbid_signal"] is True
    assert obligation["extraction_evidence"]["structured_write_forbidden"] is False


def test_execution_obligation_structured_no_write_forbids_writes() -> None:
    obligation = build_execution_obligation(
        session_id="session-structured-no-write",
        task_id="task-analysis-only",
        user_goal="只分析 backend/app.py，不要写任何文件，也不要生成报告文件。",
        current_turn_context={
            "model_turn_decision": {
                "forbidden_actions": ["modify_code", "write_file", "edit_file"],
            },
            "task_goal_spec": {
                "task_goal_type": "inspection",
                "forbidden_actions": ["modify_code", "write_file", "edit_file"],
            },
        },
    ).to_dict()

    assert obligation["required_writes"] == []
    assert "write_file" in obligation["forbidden_actions"]
    assert obligation["extraction_evidence"]["natural_language_write_forbid_signal"] is True
    assert obligation["extraction_evidence"]["structured_write_forbidden"] is True


def _decision(
    *,
    action_intent: str,
    work_mode: str,
    interaction_intent: str,
    target_objects: list[str] | None = None,
    forbidden_actions: list[str] | None = None,
    task_goal_type: str = "inspection",
    completion_criteria: list[str] | None = None,
    resource_contract: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "authority": "agent_runtime.model_turn_decision",
        "decision_id": "model-turn-decision:test",
        "user_message": "test",
        "interaction_intent": interaction_intent,
        "action_intent": action_intent,
        "work_mode": work_mode,
        "task_goal_type": task_goal_type,
        "target_objects": list(target_objects or []),
        "desired_outcome": "test",
        "deliverables": [],
        "resource_contract": dict(resource_contract or {}),
        "constraints": [],
        "forbidden_actions": list(forbidden_actions or []),
        "context_binding_decision": {},
        "planning_required": False,
        "todo_required": False,
        "completion_criteria": list(completion_criteria or []),
        "needs_clarification": False,
        "clarification_question": "",
        "confidence": 0.9,
        "ambiguity": [],
    }


