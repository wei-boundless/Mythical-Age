from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.runtime.compiler import RuntimeCompiler, _dynamic_context_segment_metadata
from harness.runtime.context_budget_policy import build_model_aware_context_budget_policy
from harness.runtime.artifact_scope import canonicalize_task_contract_artifacts
from harness.runtime.dynamic_context import DynamicContextProjection, VolatileSectionReport
from harness.runtime.dynamic_context.history_projector import HistoryProjector
from harness.runtime.dynamic_context.task_state_projector import TaskStateProjector
from harness.runtime.prompt_segment_plan import build_prompt_segment_plan
from runtime.memory.file_state_store import FileStateAuthorityStore
from runtime.tool_runtime.tool_result_envelope import build_tool_result_envelope


def _payload_after_title(content: str, title: str) -> dict[str, object]:
    marker = title + "\n"
    assert content.startswith(marker)
    return json.loads(content[len(marker):])


def _payload_containing_title(messages: list[dict[str, object]] | tuple[dict[str, object], ...], title: str) -> dict[str, object]:
    marker = title + "\n"
    for message in messages:
        content = str(message.get("content") or "")
        index = content.find(marker)
        if index >= 0:
            return json.loads(content[index + len(marker):])
    raise AssertionError(f"packet title not found: {title}")


def _persisted_output_path(content: str) -> Path:
    for line in str(content or "").splitlines():
        if line.startswith("Path: "):
            return Path(line.split("Path: ", 1)[1].strip())
    raise AssertionError("persisted output path not found")


def _stable_prefix_hashes(segment_plan: dict[str, object]) -> dict[str, str]:
    return {
        str(segment["kind"]): str(segment["model_message_hash"])
        for segment in list(segment_plan.get("segments") or [])
        if isinstance(segment, dict) and segment.get("kind") in {"global_static", "turn_stable", "turn_context"}
    }


def test_history_projector_keeps_session_emphasis_as_pinned_facts() -> None:
    projection = HistoryProjector().project(
        [{"role": "user", "content": "继续"}],
        session_context={
            "session_emphasis": [
                {
                    "fact_id": "phase-plan-first",
                    "content": "本会话内涉及 runtime/memory 大改时，先按计划执行。",
                    "scope": "session_task",
                    "priority": "high",
                    "source_message_ref": "message:0",
                }
            ]
        },
    )

    assert projection["pinned_facts"] == [
        {
            "fact_id": "phase-plan-first",
            "kind": "session_emphasis",
            "content": "本会话内涉及 runtime/memory 大改时，先按计划执行。",
            "scope": "session_task",
            "priority": "high",
            "source_message_ref": "message:0",
            "authority": "memory_system.session_emphasis",
        }
    ]


def test_runtime_compiler_emits_dynamic_context_report_and_projected_task_state() -> None:
    result = RuntimeCompiler().compile_task_execution_packet(
        session_id="session:dynamic-context",
        task_run={"task_run_id": "taskrun:dynamic-context", "diagnostics": {"executor_status": "running"}},
        contract={"task_run_goal": "验证动态上下文投影", "completion_criteria": ["投影进入 packet"]},
        observations=[
            {
                "observation_id": "obs:tool",
                "payload": {
                    "result_envelope": {
                        "envelope_id": "tool-result:obs",
                        "tool_name": "read_file",
                        "status": "ok",
                        "text": "file content",
                        "artifact_refs": [{"path": "artifacts/file.txt"}],
                    }
                },
            }
        ],
        execution_state={
            "system_projection": {
                "runtime_status": "running",
                "current_facts": [{"tool_name": "write_file", "summary": "已创建入口文件"}],
                "artifact_evidence": [{"path": "artifacts/file.txt", "kind": "file"}],
                "pending_user_steers": [{"steer_id": "steer:1", "summary": "改成五层"}],
            },
            "large_internal_blob": "x" * 5000,
        },
        work_rollout={
            "latest_progress": "完成第一步",
            "model_visible_history": [{"title": "第一步", "status": "completed", "summary": "完成初始化"}],
            "artifact_refs": [{"path": "artifacts/file.txt"}],
        },
        runtime_assembly={
            "profile": {"mode": "professional"},
            "task_environment": {"environment_id": "env.general.workspace"},
            "operation_authorization": {"allowed_operations": ["op.read_file"]},
        },
    )

    packet = result.packet
    manifest = packet.diagnostics["prompt_manifest"]
    volatile_payload = _payload_containing_title(packet.model_messages, "Task execution current state")

    assert "dynamic_context_report" in manifest
    assert all(item["volatility_reason"] for item in manifest["dynamic_context_report"]["section_reports"])
    task_state = volatile_payload["task_state"]
    assert task_state["artifact_evidence"][0]["path"] == "artifacts/file.txt"
    assert task_state["pending_user_steers"][0]["steer_id"] == "steer:1"
    assert "large_internal_blob" not in json.dumps(volatile_payload, ensure_ascii=False)
    assert task_state["latest_tool_results"][0]["tool_name"] == "read_file"
    assert packet.artifact_refs == ("artifacts/file.txt",)


def test_task_observation_large_tool_result_exposes_rehydration_address(tmp_path: Path) -> None:
    storage_root = tmp_path / "runtime-state"
    large_tool_output = "observation-tool-output\n" + ("y" * 9000)

    result = RuntimeCompiler().compile_task_execution_packet(
        session_id="session:observation-rehydration-address",
        task_run={
            "task_run_id": "taskrun:observation-rehydration-address",
            "diagnostics": {"executor_status": "running"},
        },
        contract={
            "task_run_goal": "验证 observation 大工具输出恢复入口",
            "completion_criteria": ["恢复入口进入模型可见状态"],
        },
        observations=[
            {
                "observation_id": "obs:large-output",
                "payload": {
                    "result_envelope": {
                        "envelope_id": "tool-result:large-output",
                        "tool_name": "read_file",
                        "status": "ok",
                        "text": large_tool_output,
                    }
                },
            }
        ],
        runtime_assembly={
            "profile": {"mode": "professional"},
            "runtime_storage_ref": {"runtime_state_root": str(storage_root)},
            "task_environment": {
                "environment_id": "env.general.workspace",
            },
        },
    )

    volatile_payload = _payload_after_title(result.packet.model_messages[-1]["content"], "Task execution current state")
    latest = volatile_payload["task_state"]["latest_tool_results"][0]
    plan = latest["rehydration_plan"]
    persisted = plan["capabilities"][0]
    path = Path(persisted["args"]["path"])
    model_text = "\n".join(str(message.get("content") or "") for message in result.packet.model_messages)

    assert persisted["tool_name"] == "read_persisted_tool_result"
    assert persisted["args"]["path"]
    assert path.exists()


def test_task_state_projects_exploration_advisory() -> None:
    result = RuntimeCompiler().compile_task_execution_packet(
        session_id="session:exploration-advisory",
        task_run={"task_run_id": "taskrun:exploration-advisory", "diagnostics": {"executor_status": "running"}},
        contract={"task_run_goal": "审查整个代码库", "completion_criteria": ["输出审查结论"]},
        observations=[],
        execution_state={
            "system_projection": {
                "exploration_advisory": {
                    "triggered": True,
                    "kind": "large_scope_exploration_streak",
                    "authority_boundary": "observation_pattern_only",
                    "consecutive_exploration_tool_calls": 6,
                    "threshold": 6,
                    "non_blocking": True,
                }
            }
        },
        runtime_assembly={
            "profile": {"mode": "professional"},
            "task_environment": {"environment_id": "env.coding.vibe_workspace"},
            "operation_authorization": {"allowed_operations": ["op.read_file", "op.search_text"]},
        },
    )

    volatile_payload = _payload_after_title(result.packet.model_messages[-1]["content"], "Task execution current state")
    advisory = volatile_payload["task_state"]["exploration_advisory"]

    assert advisory["triggered"] is True
    assert advisory["authority_boundary"] == "observation_pattern_only"
    assert advisory["consecutive_exploration_tool_calls"] == 6
    assert advisory["non_blocking"] is True
    assert "recommended_action" not in advisory


def test_read_file_content_windows_survive_task_state_projection() -> None:
    def _read_observation(ref: str, text: str, start_line: int, end_line: int, next_start_line: int | None) -> dict[str, object]:
        return {
            "observation_id": ref,
            "payload": {
                "result_envelope": {
                    "envelope_id": f"tool-result:{ref}",
                    "tool_name": "read_file",
                    "status": "ok",
                    "text": text,
                    "observed_paths": ["docs/long.md"],
                    "structured_payload": {
                        "observed_paths": ["docs/long.md"],
                        "tool_result": {
                            "kind": "text_file",
                            "path": "docs/long.md",
                            "total_lines": 30,
                            "start_line": start_line,
                            "line_count": 10,
                            "returned_lines": end_line - start_line + 1,
                            "end_line": end_line,
                            "next_start_line": next_start_line,
                            "has_more": next_start_line is not None,
                            "truncated": next_start_line is not None,
                            "content_sha256": "sha256:test",
                        },
                    },
                }
            },
        }

    result = RuntimeCompiler().compile_task_execution_packet(
        session_id="session:read-windows",
        task_run={"task_run_id": "taskrun:read-windows", "diagnostics": {"executor_status": "running"}},
        contract={"task_run_goal": "连续读取长文件", "completion_criteria": ["读取窗口可见"]},
        observations=[
            _read_observation("obs:window:1", "1 | first", 1, 10, 11),
            _read_observation("obs:window:11", "11 | next", 11, 20, 21),
        ],
        execution_state={
            "system_projection": {
                "file_state": [
                    {
                        "path": "docs/long.md",
                        "read_ranges": [
                            {"start_line": 1, "end_line": 10, "observation_ref": "obs:window:1"},
                            {"start_line": 11, "end_line": 20, "observation_ref": "obs:window:11"},
                        ],
                        "coverage": {"covered_lines": 20, "total_lines": 30, "complete": False},
                        "total_lines": 30,
                        "content_sha256": "sha256:test",
                        "last_observation_ref": "obs:window:11",
                        "has_more": True,
                        "status": "partial",
                    }
                ]
            }
        },
        runtime_assembly={
            "profile": {"mode": "professional"},
            "task_environment": {"environment_id": "env.coding.vibe_workspace"},
            "operation_authorization": {"allowed_operations": ["op.read_file"]},
        },
    )

    volatile_payload = _payload_after_title(result.packet.model_messages[-1]["content"], "Task execution current state")
    windows = [
        item
        for item in volatile_payload["task_state"]["latest_tool_results"]
        if item.get("tool_name") == "read_file"
    ]

    assert [item["content_range"]["start_line"] for item in windows] == [1, 11]
    assert windows[0]["content_range"]["next_start_line"] == 11
    assert windows[0]["evidence_policy"]["source_kind"] == "code_evidence"
    assert windows[0]["rehydration_plan"]["prompt_status"] == "file_window_only"
    assert windows[0]["rehydration_plan"]["capabilities"][0]["next_request"] == {
        "tool_name": "read_file",
        "args": {"path": "docs/long.md", "start_line": 11, "line_count": 10},
    }
    assert volatile_payload["task_state"]["file_state"][0]["read_ranges"] == [
        {"start_line": 1, "end_line": 10, "observation_ref": "obs:window:1"},
        {"start_line": 11, "end_line": 20, "observation_ref": "obs:window:11"},
    ]


def test_code_read_preview_survives_current_fact_dedupe() -> None:
    result = RuntimeCompiler().compile_task_execution_packet(
        session_id="session:code-preview-dedupe",
        task_run={"task_run_id": "taskrun:code-preview-dedupe", "diagnostics": {"executor_status": "running"}},
        contract={"task_run_goal": "读取代码并准备编辑", "completion_criteria": ["代码窗口可见"]},
        observations=[
            {
                "observation_id": "obs:read-app",
                "payload": {
                    "result_envelope": {
                        "envelope_id": "tool-result:read-app",
                        "tool_name": "read_file",
                        "status": "ok",
                        "text": "1 | def run():\n2 |     return True",
                        "observed_paths": ["src/app.py"],
                        "structured_payload": {
                            "tool_result": {
                                "kind": "text_file",
                                "path": "src/app.py",
                                "start_line": 1,
                                "end_line": 2,
                                "returned_lines": 2,
                                "line_count": 2,
                                "total_lines": 2,
                                "has_more": False,
                                "truncated": False,
                                "content_sha256": "sha256:app",
                            }
                        },
                    }
                },
            }
        ],
        execution_state={
            "system_projection": {
                "current_facts": [
                    {
                        "observation_ref": "obs:read-app",
                        "tool_name": "read_file",
                        "status": "ok",
                        "path": "src/app.py",
                        "summary": "read src/app.py",
                        "content_range": {"path": "src/app.py", "start_line": 1, "end_line": 2},
                    }
                ]
            }
        },
        runtime_assembly={
            "profile": {"mode": "professional"},
            "task_environment": {"environment_id": "env.coding.vibe_workspace"},
            "operation_authorization": {"allowed_operations": ["op.read_file"]},
        },
    )

    volatile_payload = _payload_after_title(result.packet.model_messages[-1]["content"], "Task execution current state")
    windows = [
        item
        for item in volatile_payload["task_state"]["latest_tool_results"]
        if item.get("tool_name") == "read_file"
    ]

    assert windows
    assert windows[0]["evidence_policy"]["visible_content_authority"] == "exact_visible_line_window"


def test_prefixed_read_file_source_gets_code_observation_preview_budget() -> None:
    long_window = "\n".join(f"{line} | value_{line} = {'x' * 24}" for line in range(1, 90))
    result = RuntimeCompiler().compile_task_execution_packet(
        session_id="session:prefixed-read-budget",
        task_run={"task_run_id": "taskrun:prefixed-read-budget", "diagnostics": {"executor_status": "running"}},
        contract={"task_run_goal": "读取带前缀来源的代码", "completion_criteria": ["代码窗口可见"]},
        observations=[
            {
                "observation_id": "obs:prefixed-read",
                "source": "tool:read_file",
                "text": long_window,
                "structured_payload": {
                    "tool_result": {
                        "kind": "text_file",
                        "path": "src/prefixed.py",
                        "start_line": 1,
                        "end_line": 89,
                        "returned_lines": 89,
                        "line_count": 89,
                        "total_lines": 89,
                        "has_more": False,
                        "truncated": False,
                    }
                },
            }
        ],
        runtime_assembly={
            "profile": {"mode": "professional"},
            "task_environment": {"environment_id": "env.coding.vibe_workspace"},
            "operation_authorization": {"allowed_operations": ["op.read_file"]},
        },
    )

    volatile_payload = _payload_after_title(result.packet.model_messages[-1]["content"], "Task execution current state")
    latest = volatile_payload["task_state"]["latest_tool_results"][0]

    assert latest["tool_name"] == "read_file"
    assert latest["evidence_policy"]["source_kind"] == "code_evidence"


def test_code_structure_map_survives_task_state_projection() -> None:
    code_structure = {
        "authority": "capability.codebase_search.code_structure_map",
        "source_kind": "codebase_search",
        "candidate_only": True,
        "source_authority": "locator_only",
        "instruction": "Use read_file next; do not treat snippets as complete source.",
        "files": [
            {
                "path": "backend/harness/runtime/dynamic_context/manager.py",
                "candidate_only": True,
                "must_read_source_before_edit": True,
                "evidence_refs": ["backend/harness/runtime/dynamic_context/manager.py:20"],
                "slices": [
                    {
                        "evidence_ref": "backend/harness/runtime/dynamic_context/manager.py:20",
                        "matched_line": 20,
                        "start_line": 18,
                        "end_line": 36,
                        "symbol": "DynamicContextManager",
                        "evidence_kind": "definition",
                        "score": 0.96,
                        "read_request": {
                            "tool_name": "read_file",
                            "args": {
                                "path": "backend/harness/runtime/dynamic_context/manager.py",
                                "start_line": 18,
                                "line_count": 19,
                            },
                        },
                        "snippet": "class DynamicContextManager:",
                    }
                ],
            }
        ],
        "limitations": ["not_full_source"],
    }
    result = RuntimeCompiler().compile_task_execution_packet(
        session_id="session:code-structure",
        task_run={"task_run_id": "taskrun:code-structure", "diagnostics": {"executor_status": "running"}},
        contract={"task_run_goal": "定位动态上下文结构", "completion_criteria": ["结构图可见"]},
        observations=[
            {
                "observation_id": "obs:code-structure",
                "payload": {
                    "result_envelope": {
                        "envelope_id": "tool-result:code-structure",
                        "tool_name": "codebase_search",
                        "status": "ok",
                        "text": json.dumps(
                            {
                                "status": "completed",
                                "answer_candidate": "Found DynamicContextManager",
                                "code_structure": code_structure,
                            }
                        ),
                    }
                },
            }
        ],
        runtime_assembly={
            "profile": {"mode": "professional"},
            "task_environment": {"environment_id": "env.coding.vibe_workspace"},
            "operation_authorization": {"allowed_operations": ["op.codebase_search", "op.read_file"]},
        },
    )

    volatile_payload = _payload_after_title(result.packet.model_messages[-1]["content"], "Task execution current state")
    latest = volatile_payload["task_state"]["latest_tool_results"][0]
    structure = latest["code_structure"]

    assert structure["candidate_only"] is True
    assert structure["source_authority"] == "locator_only"
    assert structure["files"][0]["slices"][0]["read_request"]["tool_name"] == "read_file"
    assert "snippet" not in structure["files"][0]["slices"][0]
    assert latest["evidence_policy"]["source_kind"] == "code_locator"
    assert latest["evidence_policy"]["must_read_source_before_edit"] is True


def test_code_structure_locator_survives_current_fact_dedupe() -> None:
    code_structure = {
        "source_authority": "locator_only",
        "candidate_only": True,
        "files": [
            {
                "path": "backend/harness/runtime/dynamic_context/manager.py",
                "must_read_source_before_edit": True,
                "slices": [
                    {
                        "read_request": {
                            "tool_name": "read_file",
                            "args": {
                                "path": "backend/harness/runtime/dynamic_context/manager.py",
                                "start_line": 18,
                                "line_count": 20,
                            },
                        }
                    }
                ],
            }
        ],
    }

    payload = TaskStateProjector().project(
        execution_projection={
            "current_facts": [
                {
                    "tool_name": "codebase_search",
                    "status": "ok",
                    "summary": "Found DynamicContextManager",
                }
            ]
        },
        observation_projection={
            "latest_observations": [
                {
                    "observation_id": "obs:code-search",
                    "source": "codebase_search",
                    "status": "ok",
                    "summary": "Found DynamicContextManager",
                    "tool_result": {
                        "tool_name": "codebase_search",
                        "status": "ok",
                        "code_structure": code_structure,
                        "evidence_policy": {
                            "source_kind": "code_locator",
                            "source_authority": "locator_only",
                            "must_read_source_before_edit": True,
                        },
                    },
                }
            ]
        },
        work_history_projection={},
        task_run_state={},
        envelope_projection={},
        include_task_run_context=False,
    )

    latest = payload["latest_tool_results"][0]
    assert latest["code_structure"]["files"][0]["slices"][0]["read_request"]["tool_name"] == "read_file"
    assert latest["evidence_policy"]["source_kind"] == "code_locator"


def test_task_execution_projects_file_state_from_execution_state(tmp_path: Path) -> None:
    storage_root = tmp_path / "runtime-state"
    read_envelope = build_tool_result_envelope(
        tool_name="read_file",
        tool_args={"path": "backend/runtime/tool_runtime/native_tools.py", "start_line": 11, "line_count": 5},
        result={
            "text": "11 | import json",
            "structured_payload": {
                "observed_paths": ["backend/runtime/tool_runtime/native_tools.py"],
                "tool_result": {
                    "kind": "text_file",
                    "path": "backend/runtime/tool_runtime/native_tools.py",
                    "start_line": 11,
                    "end_line": 15,
                    "returned_lines": 5,
                    "line_count": 5,
                    "total_lines": 30,
                    "next_start_line": 16,
                    "has_more": True,
                    "content_sha256": "sha256:native-tools",
                },
            },
        },
        tool_call_id="call:read-native",
        action_request_id="rtact:read-native",
        caller_kind="task_run",
        caller_ref="taskrun:derived-file-state",
    )
    FileStateAuthorityStore(storage_root).apply_observation(
        "taskrun:derived-file-state",
        {
            "observation_id": "obs:read-native",
            "payload": {
                "tool_name": "read_file",
                "tool_call_id": "call:read-native",
                "result_envelope": read_envelope.to_dict(),
            },
        },
    )
    file_state = FileStateAuthorityStore(storage_root).snapshot("taskrun:derived-file-state")

    result = RuntimeCompiler().compile_task_execution_packet(
        session_id="session:derived-file-state",
        task_run={"task_run_id": "taskrun:derived-file-state", "diagnostics": {"executor_status": "running"}},
        contract={"task_run_goal": "验证文件状态投影", "completion_criteria": ["file_state 来自持久 store"]},
        observations=[],
        execution_state={
            "system_projection": {
                "runtime_status": "running",
                "file_state": file_state,
                "file_state_source": "runtime.memory.file_state_store",
            }
        },
        runtime_assembly={
            "profile": {"mode": "professional"},
            "task_environment": {
                "environment_id": "env.coding.vibe_workspace",
            },
            "operation_authorization": {"allowed_operations": ["op.read_file"]},
        },
    )

    volatile_payload = _payload_after_title(result.packet.model_messages[-1]["content"], "Task execution current state")
    file_state = volatile_payload["task_state"]["file_state"]

    assert file_state[0]["path"] == "backend/runtime/tool_runtime/native_tools.py"
    assert file_state[0]["status"] == "partial"
    assert file_state[0]["next_suggested_read"]["start_line"] == 16
    assert file_state[0]["evidence_refs"] == ["obs:read-native", "obs:read-native"]


def test_task_execution_exposes_known_task_files_for_resume(tmp_path: Path) -> None:
    storage_root = tmp_path / "runtime-state"
    read_envelope = build_tool_result_envelope(
        tool_name="read_file",
        tool_args={"path": "backend/harness/runtime/compiler.py", "start_line": 21, "line_count": 10},
        result={
            "text": "21 | from prompt_composition import (",
            "structured_payload": {
                "observed_paths": ["backend/harness/runtime/compiler.py"],
                "tool_result": {
                    "kind": "text_file",
                    "path": "backend/harness/runtime/compiler.py",
                    "start_line": 21,
                    "end_line": 30,
                    "returned_lines": 10,
                    "line_count": 10,
                    "total_lines": 3000,
                    "next_start_line": 31,
                    "has_more": True,
                    "content_sha256": "sha256:compiler-window",
                },
            },
        },
        tool_call_id="call:read-compiler",
        action_request_id="rtact:read-compiler",
        caller_kind="task_run",
        caller_ref="taskrun:bound-context",
    )
    FileStateAuthorityStore(storage_root).apply_observation(
        "taskrun:bound-context",
        {
            "observation_id": "obs:read-compiler",
            "payload": {
                "tool_name": "read_file",
                "tool_call_id": "call:read-compiler",
                "result_envelope": read_envelope.to_dict(),
            },
        },
    )
    file_state = FileStateAuthorityStore(storage_root).snapshot("taskrun:bound-context")

    result = RuntimeCompiler().compile_task_execution_packet(
        session_id="session:bound-context",
        task_run={"task_run_id": "taskrun:bound-context", "diagnostics": {"executor_status": "running"}},
        contract={
            "task_run_goal": "实现 bound task context",
            "completion_criteria": ["bound context 进入 task stable prefix"],
            "plan_ref": "plan:bound-context",
            "implementation_lock": {"plan_ref": "plan:bound-context", "status": "approved"},
        },
        observations=[],
        execution_state={
            "system_projection": {
                "runtime_status": "running",
                "file_state": file_state,
                "file_state_source": "runtime.memory.file_state_store",
            }
        },
        runtime_assembly={
            "profile": {"mode": "professional"},
            "task_environment": {
                "environment_id": "env.coding.vibe_workspace",
            },
            "operation_authorization": {"allowed_operations": ["op.read_file"]},
        },
    )

    payload = _payload_containing_title(result.packet.model_messages, "Task execution bound task context")
    bound = payload["bound_task_context"]
    segment_kinds = [dict(item).get("kind") for item in result.packet.segment_plan["segments"]]
    manifest = result.packet.bound_task_context_manifest

    assert bound["plan_refs"] == ["plan:bound-context"]
    assert bound["known_task_files"][0]["path"] == "backend/harness/runtime/compiler.py"
    assert bound["known_task_files"][0]["next_suggested_read"]["start_line"] == 31
    assert "read_windows" not in bound["known_task_files"][0]
    assert "task_files" not in bound
    assert "rehydration_refs" not in bound
    assert manifest["task_files"][0]["path"] == "backend/harness/runtime/compiler.py"
    assert manifest["task_files"][0]["next_suggested_read"]["start_line"] == 31
    assert manifest["rehydration_refs"][0]["source"] == "file_state"
    assert "task_run_id" not in json.dumps(payload, ensure_ascii=False)
    assert segment_kinds.index("bound_task_context_stable") < segment_kinds.index("task_runtime_boundary_dynamic")
    assert manifest["context_hash"] == bound["context_hash"]
    bound_segment = next(item for item in result.packet.segment_plan["segments"] if item["kind"] == "bound_task_context_stable")
    assert bound_segment["cache_scope"] == "task"
    assert bound_segment["cache_role"] == "session_stable"

    second_read_envelope = build_tool_result_envelope(
        tool_name="read_file",
        tool_args={"path": "backend/harness/runtime/compiler.py", "start_line": 31, "line_count": 10},
        result={
            "text": "31 | from .bound_task_context import build_bound_task_context",
            "structured_payload": {
                "observed_paths": ["backend/harness/runtime/compiler.py"],
                "tool_result": {
                    "kind": "text_file",
                    "path": "backend/harness/runtime/compiler.py",
                    "start_line": 31,
                    "end_line": 40,
                    "returned_lines": 10,
                    "line_count": 10,
                    "total_lines": 3000,
                    "next_start_line": 41,
                    "has_more": True,
                    "content_sha256": "sha256:compiler-window-2",
                },
            },
        },
        tool_call_id="call:read-compiler-2",
        action_request_id="rtact:read-compiler-2",
        caller_kind="task_run",
        caller_ref="taskrun:bound-context",
    )
    FileStateAuthorityStore(storage_root).apply_observation(
        "taskrun:bound-context",
        {
            "observation_id": "obs:read-compiler-2",
            "payload": {
                "tool_name": "read_file",
                "tool_call_id": "call:read-compiler-2",
                "result_envelope": second_read_envelope.to_dict(),
            },
        },
    )
    second_file_state = FileStateAuthorityStore(storage_root).snapshot("taskrun:bound-context")

    result_after_replay_growth = RuntimeCompiler().compile_task_execution_packet(
        session_id="session:bound-context",
        task_run={"task_run_id": "taskrun:bound-context", "diagnostics": {"executor_status": "running"}},
        contract={
            "task_run_goal": "实现 bound task context",
            "completion_criteria": ["bound context 进入 task stable prefix"],
            "plan_ref": "plan:bound-context",
            "implementation_lock": {"plan_ref": "plan:bound-context", "status": "approved"},
        },
        observations=[],
        execution_state={
            "system_projection": {
                "runtime_status": "running",
                "file_state": second_file_state,
                "file_state_source": "runtime.memory.file_state_store",
            }
        },
        runtime_assembly={
            "profile": {"mode": "professional"},
            "task_environment": {
                "environment_id": "env.coding.vibe_workspace",
            },
            "operation_authorization": {"allowed_operations": ["op.read_file"]},
        },
    )
    second_payload = _payload_containing_title(
        result_after_replay_growth.packet.model_messages,
        "Task execution bound task context",
    )
    second_bound = second_payload["bound_task_context"]
    second_manifest = result_after_replay_growth.packet.bound_task_context_manifest
    second_bound_segment = next(
        item for item in result_after_replay_growth.packet.segment_plan["segments"] if item["kind"] == "bound_task_context_stable"
    )

    assert second_bound["known_task_files"][0]["next_suggested_read"]["start_line"] == 41
    assert second_bound["context_hash"] != bound["context_hash"]
    assert second_bound_segment["model_message_hash"] != bound_segment["model_message_hash"]
    assert second_manifest["diagnostics"]["runtime_state_hash"] != manifest["diagnostics"]["runtime_state_hash"]
    assert second_manifest["task_files"][0]["next_suggested_read"]["start_line"] == 41


def test_task_execution_prompt_uses_canonical_artifact_scope_only() -> None:
    artifact_root = "storage/task_environments/coding/vibe-workspace/artifacts"
    requested_path = "artifacts/prompt_cache_live_e2e/run/index.html"
    canonical_path = f"{artifact_root}/prompt_cache_live_e2e/run/index.html"
    result = RuntimeCompiler().compile_task_execution_packet(
        session_id="session:canonical-artifact",
        task_run={"task_run_id": "taskrun:canonical-artifact", "diagnostics": {"executor_status": "running"}},
        contract={
            "contract_id": "contract:canonical-artifact",
            "task_run_goal": "生成可打开的 HTML 页面",
            "completion_criteria": ["页面存在"],
            "required_artifacts": [
                {"artifact_kind": "html_document", "path": requested_path, "user_visible_name": "index.html"}
            ],
        },
        observations=[],
        runtime_assembly={
            "profile": {"mode": "professional"},
            "task_environment": {
                "environment_id": "env.coding.vibe_workspace",
                "storage_space": {"artifact_root": artifact_root},
                "artifact_policy": {"artifact_root": "runtime_output"},
                "sandbox_policy": {},
            },
            "operation_authorization": {"allowed_operations": ["op.write_file"]},
        },
    )

    model_input = "\n".join(str(message["content"]) for message in result.packet.model_messages)
    diagnostics = result.packet.diagnostics["artifact_scope"]
    volatile_payload = _payload_after_title(result.packet.model_messages[-1]["content"], "Task execution current state")

    assert result.envelope.artifact_policy["artifact_root"] == artifact_root
    artifact_scope_segments = [
        segment
        for segment in result.packet.segment_plan["segments"]
        if segment.get("kind") == "artifact_scope_stable"
    ]
    assert artifact_scope_segments
    assert artifact_scope_segments[0]["cache_scope"] == "task"
    assert artifact_scope_segments[0]["cache_role"] == "session_stable"
    assert volatile_payload["task_state"]["runtime_boundary"]["artifact_root"] == artifact_root
    assert diagnostics["normalizations"][0]["requested_path"] == requested_path
    assert diagnostics["normalizations"][0]["path"] == canonical_path
    assert diagnostics["canonical_output_paths"] == [canonical_path]


def test_artifact_contract_normalization_replaces_path_aliases_with_canonical_path() -> None:
    artifact_root = "storage/task_environments/coding/vibe-workspace/artifacts"
    normalized = canonicalize_task_contract_artifacts(
        {
            "required_artifacts": [
                {"artifact_kind": "html_document", "artifact_path": "artifacts/demo/index.html"}
            ],
            "required_verifications": [
                {"verification_kind": "readback", "target_path": "artifacts/demo/index.html"}
            ],
        },
        artifact_root=artifact_root,
    )

    expected = f"{artifact_root}/demo/index.html"
    assert normalized.contract["required_artifacts"][0] == {"artifact_kind": "html_document", "path": expected}
    assert normalized.contract["required_verifications"][0] == {"verification_kind": "readback", "path": expected}
    assert [item["requested_path"] for item in normalized.normalizations] == [
        "artifacts/demo/index.html",
        "artifacts/demo/index.html",
    ]


def test_task_work_rollout_only_enters_model_through_dynamic_context_projection() -> None:
    result = RuntimeCompiler().compile_task_execution_packet(
        session_id="session:work-rollout-projection",
        task_run={"task_run_id": "taskrun:work-rollout-projection", "diagnostics": {"executor_status": "running"}},
        contract={"task_run_goal": "验证工作历史投影", "completion_criteria": ["工作历史只走动态上下文投影"]},
        observations=[],
        work_rollout={
            "latest_progress": "完成初始化",
            "latest_step_title": "初始化",
            "agent_brief_output": "ROOT_AGENT_BRIEF_SHOULD_NOT_BYPASS_PROJECTOR",
            "latest_checkpoint_ref": "rtchk:old-control-point",
            "lineage": {"parent_task_run_id": "taskrun:old"},
            "model_visible_history": [
                {
                    "title": "初始化",
                    "status": "completed",
                    "summary": "已创建基础文件",
                    "event_offset": 12,
                    "refs": {"checkpoint_ref": "rtchk:old-step"},
                    "checkpoint": {"ref": "rtchk:old-step"},
                }
            ],
        },
        runtime_assembly={
            "profile": {"mode": "professional"},
            "task_environment": {"environment_id": "env.general.workspace"},
            "operation_authorization": {"allowed_operations": ["op.read_file"]},
        },
    )

    model_input = "\n".join(str(message["content"]) for message in result.packet.model_messages)
    volatile_payload = _payload_after_title(result.packet.model_messages[-1]["content"], "Task execution current state")

    work_progress = volatile_payload["task_state"]["work_progress"]
    assert work_progress["historical_work_summary"]["non_control_context"] is True
    assert "checkpoint" not in json.dumps(work_progress, ensure_ascii=False)
    assert "lineage" not in json.dumps(work_progress, ensure_ascii=False)
    assert "event_offset" not in json.dumps(work_progress, ensure_ascii=False)
    assert "refs" not in work_progress["recent_steps"][0]


def test_task_execution_state_deduplicates_observation_failures_and_preserves_retry_fields() -> None:
    observation = {
        "observation_id": "obs:image",
        "payload": {
            "tool_name": "image_generate",
            "result": json.dumps(
                {
                    "ok": False,
                    "error": "gateway timeout",
                    "structured_error": {
                        "code": "image_provider_transient_error",
                        "message": "Image API failed with status 504",
                        "retryable": True,
                        "origin": "image_provider",
                        "provider_retryable": True,
                        "agent_auto_retry_allowed": True,
                        "agent_retry_policy": "bounded_retry_with_backoff",
                        "max_agent_retry_attempts": 2,
                        "suggested_retry_delay_seconds": 15,
                        "attempts": [
                            {
                                "model": "gpt-image-2",
                                "attempt_index": 1,
                                "http_status": 504,
                                "code": "image_provider_transient_error",
                                "retryable": True,
                            }
                        ],
                    },
                }
            ),
        },
        "runtime_freshness": {"visibility": "active"},
    }
    result = RuntimeCompiler().compile_task_execution_packet(
        session_id="session:task-state-dedupe",
        task_run={"task_run_id": "taskrun:task-state-dedupe", "diagnostics": {"executor_status": "running"}},
        contract={"task_run_goal": "执行 image_generate，遇到供应商瞬时错误时允许有限退避重试", "completion_criteria": ["生成图片或说明重试耗尽"]},
        observations=[observation],
        execution_state={
            "system_projection": {
                "runtime_status": "running",
                "active_failures": [
                    {
                        "observation_ref": "obs:image",
                        "tool_name": "image_generate",
                        "status": "error",
                        "summary": "gateway timeout",
                        "error": {
                            "code": "image_provider_transient_error",
                            "message": "Image API failed with status 504",
                            "retryable": True,
                            "origin": "image_provider",
                            "provider_retryable": True,
                            "agent_auto_retry_allowed": True,
                            "agent_retry_policy": "bounded_retry_with_backoff",
                            "max_agent_retry_attempts": 2,
                            "suggested_retry_delay_seconds": 15,
                        },
                    }
                ],
                "last_action_receipts": [
                    {
                        "observation_ref": "obs:image",
                        "tool_name": "image_generate",
                        "status": "error",
                        "summary": "gateway timeout",
                    }
                ],
            }
        },
        runtime_assembly={
            "profile": {"mode": "professional"},
            "task_environment": {"environment_id": "env.coding.vibe_workspace"},
            "operation_authorization": {"allowed_operations": ["op.image_generate"]},
        },
    )

    volatile_payload = _payload_after_title(result.packet.model_messages[-1]["content"], "Task execution current state")
    task_state = volatile_payload["task_state"]
    assert "observations" not in volatile_payload
    assert "execution_state" not in volatile_payload
    assert len(task_state["active_failures"]) == 1
    error = task_state["active_failures"][0]["error"]
    assert error["provider_retryable"] is True
    assert error["agent_auto_retry_allowed"] is True
    assert error["agent_retry_policy"] == "bounded_retry_with_backoff"
    assert error["max_agent_retry_attempts"] == 2
    assert error["attempts"][0]["http_status"] == 504


def test_task_execution_state_semantically_deduplicates_repeated_tool_facts() -> None:
    result = RuntimeCompiler().compile_task_execution_packet(
        session_id="session:semantic-dedupe",
        task_run={
            "task_run_id": "taskrun:semantic-dedupe",
            "status": "running",
            "diagnostics": {"executor_status": "running"},
        },
        contract={"task_run_goal": "检查目录并继续", "completion_criteria": ["目录检查只保留一条事实"]},
        observations=[],
        execution_state={
            "system_projection": {
                "runtime_status": "running",
                "current_facts": [
                    {"observation_ref": "obs:path:1", "tool_name": "path_exists", "path": "artifacts/demo", "status": "ok", "summary": "路径不存在"},
                    {"observation_ref": "obs:path:2", "tool_name": "path_exists", "path": "artifacts/demo", "status": "ok", "summary": "路径不存在"},
                ],
                "last_action_receipts": [
                    {"observation_ref": "obs:path:2", "tool_name": "path_exists", "path": "artifacts/demo", "status": "ok", "summary": "路径不存在"},
                ],
            }
        },
        runtime_assembly={
            "profile": {"mode": "professional"},
            "task_environment": {"environment_id": "env.general.workspace"},
            "operation_authorization": {"allowed_operations": ["op.path_exists"]},
        },
    )

    volatile_payload = _payload_after_title(result.packet.model_messages[-1]["content"], "Task execution current state")
    task_state = volatile_payload["task_state"]
    assert [item["observation_ref"] for item in task_state["current_facts"]] == ["obs:path:1"]
    assert "latest_tool_results" not in task_state
    assert "task_run_id" not in json.dumps(volatile_payload, ensure_ascii=False)


def test_task_execution_state_hides_sandbox_artifact_paths_and_supersedes_missing_probe() -> None:
    artifact_path = "storage/task_environments/general/workspace/artifacts/five_floor_dungeon.html"
    result = RuntimeCompiler().compile_task_execution_packet(
        session_id="session:artifact-path-clean",
        task_run={
            "task_run_id": "taskrun:artifact-path-clean",
            "status": "running",
            "diagnostics": {"executor_status": "running"},
        },
        contract={"task_run_goal": "写入并验证 HTML", "completion_criteria": ["文件存在"]},
        observations=[],
        execution_state={
            "system_projection": {
                "runtime_status": "running",
                "current_facts": [
                    {
                        "observation_ref": "obs:missing",
                        "tool_name": "path_exists",
                        "path": artifact_path,
                        "status": "ok",
                        "summary": "false",
                    },
                    {
                        "observation_ref": "obs:write",
                        "tool_name": "write_file",
                        "path": artifact_path,
                        "status": "ok",
                        "summary": "Write succeeded",
                    },
                ],
                "last_action_receipts": [
                    {
                        "observation_ref": "obs:missing",
                        "tool_name": "path_exists",
                        "path": artifact_path,
                        "status": "ok",
                        "summary": "false",
                    },
                    {
                        "observation_ref": "obs:write",
                        "tool_name": "write_file",
                        "path": artifact_path,
                        "status": "ok",
                        "summary": "Write succeeded",
                    },
                ],
                "artifact_evidence": [
                    {
                        "path": artifact_path,
                        "absolute_path": "D:/AI应用/langchain-agent/storage/runtime_state/sandboxes/taskrun_x/storage/task_environments/general/workspace/artifacts/five_floor_dungeon.html",
                        "sandbox_path": artifact_path,
                        "kind": "file",
                        "source": "write_file",
                    }
                ],
            }
        },
        runtime_assembly={
            "profile": {"mode": "professional"},
            "task_environment": {"environment_id": "env.general.workspace"},
            "operation_authorization": {"allowed_operations": ["op.path_exists", "op.write_file"]},
        },
    )

    volatile_payload = _payload_after_title(result.packet.model_messages[-1]["content"], "Task execution current state")
    task_state = volatile_payload["task_state"]
    serialized = json.dumps(task_state, ensure_ascii=False)

    assert "absolute_path" not in serialized
    assert "sandbox_path" not in serialized
    assert "storage/runtime_state/sandboxes" not in serialized
    assert task_state["artifact_evidence"] == [{"path": artifact_path, "kind": "file", "source": "write_file"}]
    assert all(item.get("observation_ref") != "obs:missing" for item in task_state.get("current_facts", []))
    assert all(item.get("observation_ref") != "obs:missing" for item in task_state.get("latest_tool_results", []))
    assert any(item.get("observation_ref") == "obs:write" for item in task_state["current_facts"])


def test_task_execution_uses_invocation_scoped_agent_prompt_refs() -> None:
    result = RuntimeCompiler().compile_task_execution_packet(
        session_id="session:prompt-scope",
        task_run={"task_run_id": "taskrun:prompt-scope", "diagnostics": {"executor_status": "running"}},
        contract={
            "task_run_goal": "执行 image_generate 调用，供应商瞬时失败时允许有限退避重试",
            "completion_criteria": ["生成图片，或说明有限重试后仍失败"],
        },
        observations=[],
        available_tools=[
            {"tool_name": "image_generate", "operation_id": "op.image_generate"},
            {"tool_name": "python_symbol_search", "operation_id": "op.python_symbol_search"},
        ],
        runtime_assembly={
            "profile": {
                "mode": "professional",
                "metadata": {},
            },
            "agent_prompt_refs": ["agent.main_interactive_agent.single_agent_turn.work_role"],
            "agent_prompt_refs_by_invocation": {
                "single_agent_turn": ["agent.main_interactive_agent.single_agent_turn.work_role"],
                "task_execution": ["agent.main_interactive_agent.task_execution.work_role"],
            },
            "environment_prompt_refs": ["environment.coding.vibe_workspace.orientation"],
            "task_environment": {
                "environment_id": "env.coding.vibe_workspace",
                "title": "Development Sandbox",
                "description": "Project workspace boundary",
            },
            "operation_authorization": {"allowed_operations": ["op.image_generate", "op.python_symbol_search"]},
        },
    )

    manifest = result.packet.diagnostics["prompt_manifest"]
    agent_segments = [
        segment
        for segment in result.packet.segment_plan["segments"]
        if segment["kind"] == "agent_stable"
    ]
    assert len(agent_segments) == 1
    agent_segment = agent_segments[0]
    agent_message = result.packet.model_messages[agent_segment["model_message_index"]]
    assert "agent.main_interactive_agent.task_execution.work_role" in manifest["stable_prompt_refs"]
    assert "agent.main_interactive_agent.single_agent_turn.work_role" not in manifest["stable_prompt_refs"]
    assert agent_segment["source_ref"] == "agent.main_interactive_agent.task_execution.work_role"
    assert agent_segment["cache_role"] == "session_stable"
    assert agent_message["role"] == "system"
    assert "agent.main_interactive_agent.single_agent_turn.work_role" not in json.dumps(
        {
            "stable_prompt_refs": manifest["stable_prompt_refs"],
            "agent_segment": agent_segment,
        },
        ensure_ascii=False,
    )


def test_environment_strategy_prompt_ref_is_rejected_after_strategy_moves_to_agent_profile() -> None:
    obsolete_environment_strategy_ref = "strategy." + "development.execution.v1"
    with pytest.raises(ValueError, match="runtime prompt ref assembly rejected refs"):
        RuntimeCompiler().compile_task_execution_packet(
            session_id="session:structured-strategy",
            task_run={"task_run_id": "taskrun:structured-strategy", "diagnostics": {"executor_status": "running"}},
            contract={
                "task_run_goal": "执行 image_generate 调用，供应商瞬时失败时允许有限退避重试",
                "completion_criteria": ["生成图片，或说明有限重试后仍失败"],
            },
            observations=[],
            available_tools=[
                {"tool_name": "image_generate", "operation_id": "op.image_generate"},
                {"tool_name": "python_symbol_search", "operation_id": "op.python_symbol_search"},
            ],
            runtime_assembly={
                "profile": {"mode": "professional"},
                "environment_prompt_refs": [
                    "environment.coding.vibe_workspace.orientation",
                    obsolete_environment_strategy_ref,
                ],
                "task_environment": {
                    "environment_id": "env.coding.vibe_workspace",
                    "title": "Development Sandbox",
                    "description": "Project workspace boundary",
                },
                "operation_authorization": {"allowed_operations": ["op.image_generate", "op.python_symbol_search"]},
            },
        )


def test_runtime_compiler_rejects_wrong_invocation_prompt_ref() -> None:
    with pytest.raises(ValueError, match="resource_invocation_kind_mismatch"):
        RuntimeCompiler().compile_task_execution_packet(
            session_id="session:wrong-ref",
            task_run={"task_run_id": "taskrun:wrong-ref", "diagnostics": {"executor_status": "running"}},
            contract={"task_run_goal": "验证错误 prompt ref 不会静默装配", "completion_criteria": ["抛出错误"]},
            observations=[],
            runtime_assembly={
                "profile": {"mode": "professional"},
                "agent_prompt_refs_by_invocation": {
                    "task_execution": ["agent.main_interactive_agent.single_agent_turn.work_role"],
                },
                "task_environment": {"environment_id": "env.general.workspace"},
            },
        )


def test_single_agent_turn_keeps_compressed_context_outside_active_history() -> None:
    history = [
        {"role": "assistant", "content": "[Compressed session context]\n此前已经确认项目采用 DeepSeek。"},
        *({"role": "user", "content": f"user-{index}"} for index in range(8)),
    ]
    result = RuntimeCompiler().compile_single_agent_turn_packet(
        session_id="session:compressed-context",
        turn_id="turn:compressed-context",
        agent_invocation_id="aginvoke:compressed-context",
        user_message="继续检查 prompt 装载。",
        history=history,
        session_context={"compressed_context": "此前已经确认项目采用 DeepSeek。"},
        runtime_assembly={
            "profile": {"mode": "professional"},
            "task_environment": {"environment_id": "env.general.workspace"},
            "operation_authorization": {"allowed_operations": ["op.model_response"]},
        },
    )

    volatile_payload = _payload_after_title(result.packet.model_messages[-1]["content"], "Single agent turn current request")
    history_payload = _payload_containing_title(result.packet.model_messages, "Single agent turn session history")

    assert "history" not in volatile_payload
    assert len(history_payload["active_history"]) == 8
    history_segment = next(segment for segment in result.packet.segment_plan["segments"] if segment["kind"] == "session_history")
    runtime_segment = next(segment for segment in result.packet.segment_plan["segments"] if segment["kind"] == "dynamic_projection")
    assert history_segment["cache_role"] == "volatile"
    assert history_segment["compression_role"] == "summarize"
    assert history_segment["ordinal"] < runtime_segment["ordinal"]


def test_single_agent_turn_projects_vscode_editor_context_as_volatile_request() -> None:
    editor_context = {
        "source": "vscode",
        "captured_at": "2026-06-04T00:00:00Z",
        "workspace_roots": ["D:/repo"],
        "active_file": {
            "path": "D:/repo/backend/harness/runtime/compiler.py",
            "language_id": "python",
            "dirty": True,
            "selection": {
                "start": {"line": 10, "character": 0},
                "end": {"line": 12, "character": 5},
                "text": "selected code",
                "truncated": False,
            },
        },
        "visible_files": [{"path": "D:/repo/backend/harness/runtime/compiler.py", "language_id": "python", "dirty": True}],
        "diagnostics": [{"path": "D:/repo/backend/harness/runtime/compiler.py", "severity": "warning", "message": "unused value"}],
    }
    result = RuntimeCompiler().compile_single_agent_turn_packet(
        session_id="session:vscode-context",
        turn_id="turn:vscode-context",
        agent_invocation_id="aginvoke:vscode-context",
        user_message="检查当前打开文件。",
        history=[],
        session_context={"turn_input_facts": {"editor_context": editor_context}},
        runtime_assembly={
            "profile": {"mode": "conversation"},
            "task_environment": {"environment_id": "env.general.workspace"},
        },
    )

    stable_payload_text = str(result.packet.model_messages[1]["content"])
    volatile_payload = _payload_after_title(result.packet.model_messages[-1]["content"], "Single agent turn current request")
    report = result.packet.diagnostics["prompt_manifest"]["dynamic_context_report"]
    section_sources = [item["source"] for item in report["section_reports"]]

    assert volatile_payload["editor_context"]["source"] == "vscode"
    assert volatile_payload["editor_context"]["active_file"]["dirty"] is True
    assert "editor_context" not in stable_payload_text
    assert "vscode" in section_sources


def test_task_execution_inherits_parent_turn_editor_context_from_task_run() -> None:
    editor_context = {
        "source": "vscode",
        "workspace_roots": ["D:/repo"],
        "active_file": {
            "path": "D:/repo/frontend/src/App.tsx",
            "language_id": "typescriptreact",
            "dirty": False,
        },
        "visible_files": [{"path": "D:/repo/frontend/src/App.tsx", "language_id": "typescriptreact", "dirty": False}],
        "diagnostics": [],
    }
    result = RuntimeCompiler().compile_task_execution_packet(
        session_id="session:vscode-task",
        task_run={
            "task_run_id": "taskrun:vscode-task",
            "diagnostics": {
                "executor_status": "running",
                "editor_context": editor_context,
            },
        },
        contract={"task_run_goal": "修复当前打开的文件", "completion_criteria": ["当前文件已验证"]},
        observations=[],
        execution_state={},
        runtime_assembly={
            "profile": {"mode": "professional"},
            "task_environment": {"environment_id": "env.general.workspace"},
        },
    )

    volatile_payload = _payload_after_title(result.packet.model_messages[-1]["content"], "Task execution current state")
    manifest = result.packet.diagnostics["prompt_manifest"]

    assert volatile_payload["editor_context"]["active_file"]["path"] == "D:/repo/frontend/src/App.tsx"
    assert "editor_context" in manifest["volatile_state_refs"]


def test_observation_followup_projects_session_context_with_observations() -> None:
    result = RuntimeCompiler().compile_observation_followup_packet(
        session_id="session:followup-context",
        turn_id="turn:followup-context",
        agent_invocation_id="aginvoke:followup-context",
        user_message="根据工具结果继续。",
        history=[{"role": "user", "content": "先读文件。"}],
        session_context={"compressed_context": "此前决定优先修结构问题。"},
        observations=[{"observation_id": "obs:1", "content": "read_file ok"}],
        runtime_assembly={
            "profile": {"mode": "professional"},
            "task_environment": {"environment_id": "env.general.workspace"},
            "operation_authorization": {"allowed_operations": ["op.read_file"]},
        },
    )

    volatile_payload = _payload_after_title(result.packet.model_messages[-1]["content"], "Observation followup current request")
    history_payload = _payload_containing_title(result.packet.model_messages, "Observation followup session history")

    assert "history" not in volatile_payload
    assert volatile_payload["observations"]["latest_observations"]


def test_observation_followup_projects_active_work_control_observation_details() -> None:
    result = RuntimeCompiler().compile_observation_followup_packet(
        session_id="session:active-work-followup",
        turn_id="turn:active-work-followup",
        agent_invocation_id="aginvoke:active-work-followup",
        user_message="按这个补充方向继续。",
        history=[{"role": "user", "content": "继续当前工作。"}],
        session_context={},
        observations=[
            {
                "authority": "harness.loop.active_work_control_observation",
                "observation_kind": "active_work_control",
                "applied": False,
                "status": "blocked",
                "terminal_reason": "active_work_resume_failed",
                "runtime_result": "当前工作没有成功恢复：task_run_waiting_approval_requires_grant",
                "active_work_control": {"action": "append_instruction_to_active_work"},
                "admission": {"decision": "allow"},
                "followup_instruction": "基于该观察继续判断；不要仅因控制未执行就要求用户重复已经明确的请求。",
            }
        ],
        runtime_assembly={
            "profile": {"mode": "conversation"},
            "task_environment": {"environment_id": "env.general.workspace"},
        },
    )

    volatile_payload = _payload_after_title(result.packet.model_messages[-1]["content"], "Observation followup current request")
    observation = volatile_payload["observations"]["latest_observations"][0]

    assert observation["observation_kind"] == "active_work_control"
    assert observation["applied"] is False
    assert observation["terminal_reason"] == "active_work_resume_failed"
    assert "admission" not in observation


def test_single_agent_turn_projects_compressed_context_as_session_context() -> None:
    result = RuntimeCompiler().compile_single_agent_turn_packet(
        session_id="session:single-turn-context",
        turn_id="turn:single-turn-context",
        agent_invocation_id="aginvoke:single-turn-context",
        user_message="继续。",
        history=[
            {"role": "user", "content": "上一轮用户消息"},
            {"role": "assistant", "content": "上一轮助手回复"},
        ],
        session_context={"compressed_context": "此前已经完成项目结构审查。"},
        runtime_assembly={
            "profile": {"mode": "conversation"},
            "task_environment": {"environment_id": "env.general.workspace"},
        },
    )

    volatile_payload = _payload_after_title(result.packet.model_messages[-1]["content"], "Single agent turn current request")
    history_payload = _payload_containing_title(result.packet.model_messages, "Single agent turn session history")
    message_texts = [str(message["content"]) for message in result.packet.model_messages]

    assert "history" not in volatile_payload
    assert len(history_payload["active_history"]) == 2
    assert history_payload["current_user_message_ref"] == "volatile_current_request"
    assert result.packet.invocation_kind == "single_agent_turn"
    context_window = result.packet.diagnostics["prompt_manifest"]["context_window"]
    assert context_window["context_recovery_package_present"] is True
    assert str(context_window["context_recovery_package_hash"]).startswith("sha256:")


def test_single_agent_turn_projects_runtime_memory_context() -> None:
    result = RuntimeCompiler().compile_single_agent_turn_packet(
        session_id="session:runtime-memory-context",
        turn_id="turn:runtime-memory-context",
        agent_invocation_id="aginvoke:runtime-memory-context",
        user_message="继续修复记忆系统。",
        history=[],
        session_context={
            "memory_context": {
                "authority": "memory_system.runtime_memory_context",
                "memory_runtime_view_ref": "memory-runtime:session-runtime-memory",
                "context_package_ref": "context-receipt:test",
                "selected_sections": ["relevant_durable_context"],
                "model_visible_sections": {
                    "relevant_durable_context": [
                        "长期记忆：coding 环境修改必须真实运行聚焦测试。"
                    ],
                    "debug_session_trace": ["不应进入模型可见内容"],
                },
                "diagnostics": {"read_namespaces": ["env:env.coding.test"]},
            }
        },
        runtime_assembly={
            "profile": {"mode": "conversation"},
            "task_environment": {"environment_id": "env.coding.test"},
        },
    )

    dynamic_payload = _payload_containing_title(result.packet.model_messages, "Single agent turn dynamic runtime")

    memory_context = dynamic_payload["memory_context"]
    assert memory_context["read_namespaces"] == ["env:env.coding.test"]
    assert memory_context["model_visible_sections"]["relevant_durable_context"]
    assert "debug_session_trace" not in memory_context["model_visible_sections"]


def test_single_agent_turn_projects_recent_work_outcome_as_read_only_context() -> None:
    result = RuntimeCompiler().compile_single_agent_turn_packet(
        session_id="session:recent-work-outcome",
        turn_id="turn:recent-work-outcome",
        agent_invocation_id="aginvoke:recent-work-outcome",
        user_message="刚才为什么卡住了？",
        history=[
            {"role": "user", "content": "开始复杂版五层地下塔。"},
            {"role": "assistant", "content": "我会按这个目标推进。"},
        ],
        session_context={
            "recent_work_outcome": {
                "task_run_id": "taskrun:turn:session-recent:1:root",
                "status": "failed",
                "terminal_reason": "task_executor_schedule_failed",
                "user_visible_goal": "制作复杂版五层地下塔像素风游戏。",
                "latest_progress": "生图工具未配置，无法完成合同要求的真实美术资产。",
                "agent_brief_output": "image_generate returned Image generation is not configured.",
                "decision_boundary": "This is a read-only result from the most recent terminal task.",
                "continuation_state": "terminal_or_interrupted_task_record",
            }
        },
        runtime_assembly={
            "profile": {"mode": "conversation"},
            "task_environment": {"environment_id": "env.general.workspace"},
        },
    )

    volatile_payload = _payload_after_title(result.packet.model_messages[-1]["content"], "Single agent turn current request")
    history_payload = _payload_containing_title(result.packet.model_messages, "Single agent turn session history")
    outcome = history_payload["session_context"]["recent_work_outcome"]
    model_input = "\n".join(str(message.get("content") or "") for message in result.packet.model_messages)

    assert outcome["status"] == "failed"
    assert outcome["terminal_reason"] == "task_executor_schedule_failed"
    assert outcome["continuation_state"] == "terminal_or_interrupted_task_record"
    assert "history" not in volatile_payload
    assert "active_work_context" not in json.dumps(volatile_payload, ensure_ascii=False)
    assert "latest resumable executor checkpoint" not in model_input
    assert "当前工作或可恢复断点" not in model_input
    context_window = result.packet.diagnostics["prompt_manifest"]["context_window"]
    assert context_window["recent_work_outcome_present"] is True
    assert str(context_window["recent_work_outcome_hash"]).startswith("sha256:")


def test_single_agent_turn_active_work_prompt_binds_control_to_current_turn() -> None:
    result = RuntimeCompiler().compile_single_agent_turn_packet(
        session_id="session:active-work-current-turn",
        turn_id="turn:active-work-current-turn",
        agent_invocation_id="aginvoke:active-work-current-turn",
        user_message="继续，但是先说明为什么刚才卡住。",
        history=[],
        active_work_context={
            "status": "running",
            "control_state": "running",
            "user_visible_goal": "修复控制链路。",
            "latest_progress": "已定位到 active work prompt 边界。",
            "latest_step_name": "prompt audit",
            "resumable": True,
            "running": True,
            "continuation_kind": "same_run_resume",
        },
        runtime_assembly={
            "profile": {"mode": "conversation"},
            "task_environment": {"environment_id": "env.general.workspace"},
        },
    )

    dynamic_payload = _payload_containing_title(result.packet.model_messages, "Single agent turn dynamic runtime")
    active_work = dynamic_payload["active_work_context"]
    decision_boundary = str(active_work["decision_boundary"])
    model_input = "\n".join(str(message.get("content") or "") for message in result.packet.model_messages)

    assert "current active-turn-bound work" in decision_boundary
    assert "latest resumable executor checkpoint" not in decision_boundary
    assert "latest-task fallback" in decision_boundary
    assert "recent_work_outcome" in decision_boundary
    assert "当前工作或可恢复断点" not in model_input
    assert "系统在本轮显式暴露的当前 active-turn-bound work" in model_input
    assert "用户可见反馈意图" in model_input
    assert "控制动作脱节" in model_input
    assert "不等同暂停或停止" in model_input


def test_single_agent_turn_replays_api_transcript_as_real_chat_messages() -> None:
    result = RuntimeCompiler().compile_single_agent_turn_packet(
        session_id="session:deepseek-protocol",
        turn_id="turn:deepseek-protocol:2",
        agent_invocation_id="aginvoke:deepseek-protocol",
        user_message="继续查广州。",
        history=[
            {"role": "user", "content": "查杭州天气。"},
            {"role": "assistant", "content": "杭州天气结果。"},
        ],
        session_context={
            "api_transcript": [
                {"role": "user", "content": "查杭州天气。"},
                {
                    "role": "assistant",
                    "content": "",
                    "reasoning_content": "I need the date first.",
                    "tool_calls": [{"id": "call_1", "name": "get_date", "args": {}, "type": "tool_call"}],
                },
                {"role": "tool", "tool_call_id": "call_1", "content": "2026-04-20"},
                {"role": "assistant", "content": "杭州天气结果。", "reasoning_content": "Now I can answer."},
            ]
        },
        runtime_assembly={
            "profile": {"mode": "conversation"},
            "task_environment": {"environment_id": "env.general.workspace"},
        },
    )

    messages = result.packet.model_messages
    assistant_tool_message = next(item for item in messages if item.get("tool_calls"))
    tool_message = next(item for item in messages if item.get("role") == "tool")
    current_request_text = str(messages[-1].get("content") or "")

    assert assistant_tool_message["role"] == "assistant"
    assert assistant_tool_message["content"] == ""
    assert assistant_tool_message["tool_calls"][0]["id"] == "call_1"
    assert tool_message["tool_call_id"] == "call_1"
    assert any(
        segment["kind"] == "provider_protocol_history" and segment["cache_role"] == "never_cache"
        for segment in result.packet.segment_plan["segments"]
    )


def test_single_agent_turn_replays_only_hot_provider_protocol_tail() -> None:
    cold_history = [
        {"role": "user" if index % 2 == 0 else "assistant", "content": f"cold provider message {index}"}
        for index in range(40)
    ]
    result = RuntimeCompiler().compile_single_agent_turn_packet(
        session_id="session:protocol-tail",
        turn_id="turn:protocol-tail:2",
        agent_invocation_id="aginvoke:protocol-tail",
        user_message="继续。",
        history=[],
        session_context={
            "api_transcript": [
                *cold_history,
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{"id": "call_tail", "name": "read_file", "args": {}, "type": "tool_call"}],
                },
                {"role": "tool", "tool_call_id": "call_tail", "content": "tail tool output"},
            ]
        },
        runtime_assembly={
            "profile": {"mode": "conversation"},
            "task_environment": {"environment_id": "env.general.workspace"},
        },
    )

    model_text = "\n".join(str(message.get("content") or "") for message in result.packet.model_messages)
    provider_segments = [
        segment
        for segment in result.packet.segment_plan["segments"]
        if segment["kind"] == "provider_protocol_history"
    ]

    assert any(message.get("tool_calls") for message in result.packet.model_messages)
    assert any(
        int(dict(dict(segment.get("metadata") or {}).get("protocol_projection") or {}).get("non_protocol_message_count") or 0) == len(cold_history)
        for segment in provider_segments
    )


def test_single_agent_turn_replays_provider_protocol_after_compaction_boundary() -> None:
    result = RuntimeCompiler().compile_single_agent_turn_packet(
        session_id="session:protocol-after-compact",
        turn_id="turn:protocol-after-compact:3",
        agent_invocation_id="aginvoke:protocol-after-compact",
        user_message="继续。",
        history=[],
        session_context={
            "compressed_context": "旧工具轨迹已压缩成摘要。",
            "provider_protocol_compaction_created_at": 10.0,
            "api_transcript": [
                {
                    "role": "assistant",
                    "content": "",
                    "created_at": 1.0,
                    "tool_calls": [{"id": "call_old", "name": "read_file", "args": {}, "type": "tool_call"}],
                },
                {"role": "tool", "tool_call_id": "call_old", "content": "old tool output", "created_at": 1.0},
                {
                    "role": "assistant",
                    "content": "",
                    "created_at": 11.0,
                    "tool_calls": [{"id": "call_new", "name": "read_file", "args": {}, "type": "tool_call"}],
                },
                {"role": "tool", "tool_call_id": "call_new", "content": "new tool output", "created_at": 11.0},
            ],
        },
        runtime_assembly={
            "profile": {"mode": "conversation"},
            "task_environment": {"environment_id": "env.general.workspace"},
        },
    )

    model_text = "\n".join(str(message.get("content") or "") for message in result.packet.model_messages)
    provider_segments = [
        segment
        for segment in result.packet.segment_plan["segments"]
        if segment["kind"] == "provider_protocol_history"
    ]

    assert any(message.get("tool_calls", [{}])[0].get("id") == "call_new" for message in result.packet.model_messages if message.get("tool_calls"))
    assert any(
        int(dict(dict(segment.get("metadata") or {}).get("protocol_projection") or {}).get("compaction_boundary_omitted_message_count") or 0) == 2
        for segment in provider_segments
    )


def test_single_agent_turn_blocks_provider_protocol_when_compressed_without_boundary() -> None:
    result = RuntimeCompiler().compile_single_agent_turn_packet(
        session_id="session:protocol-compact-no-boundary",
        turn_id="turn:protocol-compact-no-boundary:3",
        agent_invocation_id="aginvoke:protocol-compact-no-boundary",
        user_message="继续。",
        history=[],
        session_context={
            "compressed_context": "旧工具轨迹已压缩成摘要。",
            "api_transcript": [
                {
                    "role": "assistant",
                    "content": "",
                    "created_at": 11.0,
                    "tool_calls": [{"id": "call_new", "name": "read_file", "args": {}, "type": "tool_call"}],
                },
                {"role": "tool", "tool_call_id": "call_new", "content": "new tool output", "created_at": 11.0},
            ],
        },
        runtime_assembly={
            "profile": {"mode": "conversation"},
            "task_environment": {"environment_id": "env.general.workspace"},
        },
    )

    assert not any(segment["kind"] == "provider_protocol_history" for segment in result.packet.segment_plan["segments"])
    assert not any(message.get("content") for message in result.packet.model_messages if message.get("role") == "tool")


def test_single_agent_turn_projects_large_provider_tool_output_to_persisted_preview(tmp_path: Path) -> None:
    storage_root = tmp_path / "runtime-state"
    large_tool_output = "raw-provider-tool-output\n" + ("x" * 9000)

    result = RuntimeCompiler().compile_single_agent_turn_packet(
        session_id="session-provider-large-tool",
        turn_id="turn:provider-large-tool:2",
        agent_invocation_id="aginvoke:provider-large-tool",
        user_message="继续。",
        history=[],
        session_context={
            "api_transcript": [
                {"role": "user", "content": "读取大文件。"},
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{"id": "call_big", "name": "read_file", "args": {}, "type": "tool_call"}],
                },
                {"role": "tool", "tool_call_id": "call_big", "content": large_tool_output},
                {"role": "assistant", "content": "已读取。"},
            ]
        },
        runtime_assembly={
            "profile": {"mode": "conversation"},
            "runtime_storage_ref": {"runtime_state_root": str(storage_root)},
            "task_environment": {
                "environment_id": "env.general.workspace",
            },
        },
    )

    tool_message = next(
        item
        for item in result.packet.model_messages
        if item.get("role") == "tool" and item.get("tool_call_id") == "call_big"
    )
    tool_content = str(tool_message.get("content") or "")
    persisted_path = _persisted_output_path(tool_content)
    provider_segment = next(
        segment
        for segment in result.packet.segment_plan["segments"]
        if segment["kind"] == "provider_protocol_history"
        and int(segment["model_message_index"]) == result.packet.model_messages.index(tool_message)
    )
    projection = dict(dict(provider_segment.get("metadata") or {}).get("protocol_projection") or {})
    model_text = "\n".join(str(message.get("content") or "") for message in result.packet.model_messages)

    assert dict(provider_segment.get("metadata") or {})["exact_content_required_before_final"] is True
    assert persisted_path.exists()
    assert projection["projected_tool_output_count"] == 1
    assert projection["persisted_tool_replacement_count"] == 1
    assert projection["output_chars"] < projection["input_chars"]


def test_provider_protocol_projection_preserves_stable_prefix_hashes(tmp_path: Path) -> None:
    runtime_assembly = {
        "profile": {"mode": "conversation"},
        "runtime_storage_ref": {"runtime_state_root": str(tmp_path / "runtime-state")},
        "task_environment": {"environment_id": "env.general.workspace"},
    }
    hot_protocol_tail = [
        {"role": "user", "content": "查最后一个文件。"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "call_tail", "name": "read_file", "args": {}, "type": "tool_call"}],
        },
        {"role": "tool", "tool_call_id": "call_tail", "content": "tail output"},
        {"role": "assistant", "content": "tail answer"},
    ]
    base = RuntimeCompiler().compile_single_agent_turn_packet(
        session_id="session:stable-provider-base",
        turn_id="turn:stable-provider-base",
        agent_invocation_id="aginvoke:stable-provider-base",
        user_message="继续。",
        history=[],
        session_context={"api_transcript": hot_protocol_tail},
        runtime_assembly=runtime_assembly,
    ).packet
    noisy = RuntimeCompiler().compile_single_agent_turn_packet(
        session_id="session:stable-provider-noisy",
        turn_id="turn:stable-provider-noisy",
        agent_invocation_id="aginvoke:stable-provider-noisy",
        user_message="继续。",
        history=[],
        session_context={
            "api_transcript": [
                *[
                    {
                        "role": "assistant" if index % 2 else "user",
                        "content": f"old protocol message {index} " + ("z" * 3000),
                    }
                    for index in range(24)
                ],
                *hot_protocol_tail,
            ]
        },
        runtime_assembly=runtime_assembly,
    ).packet

    noisy_protocol_segments = [
        segment
        for segment in noisy.segment_plan["segments"]
        if segment["kind"] == "provider_protocol_history"
    ]

    assert _stable_prefix_hashes(base.segment_plan) == _stable_prefix_hashes(noisy.segment_plan)
    assert any(
        int(dict(dict(segment.get("metadata") or {}).get("protocol_projection") or {}).get("non_protocol_message_count") or 0) == 26
        for segment in noisy_protocol_segments
    )


def test_model_aware_context_budget_uses_deepseek_1m_for_v4_models() -> None:
    policy = build_model_aware_context_budget_policy(
        invocation_kind="single_agent_turn",
        model_selection={
            "provider": "deepseek",
            "model": "deepseek-v4-pro",
            "context_budget_preset": "deepseek_1m",
            "max_output_tokens": 65536,
            "thinking_mode": "enabled",
            "reasoning_effort": "max",
        },
    )

    assert policy.effective_preset_id == "deepseek_1m"
    assert policy.context_window_tokens == 1_000_000
    assert policy.available_context_tokens >= 800_000
    assert policy.projection_limits["recent_history_message_limit"] > 100
    assert 6 <= policy.projection_limits["provider_protocol_message_limit"] <= 16
    assert policy.projection_limits["provider_protocol_char_budget"] <= 24_000
    assert policy.volatile_char_budget > 1_000_000
    assert policy.thinking_mode == "enabled"
    assert policy.reasoning_effort == "max"
    assert policy.diagnostics["provider_capability_source"] == "runtime.model_gateway.providers.deepseek"
    assert "deepseek_1m" in policy.diagnostics["provider_supported_context_budget_presets"]


def test_model_aware_context_budget_does_not_enable_deepseek_1m_for_other_models() -> None:
    policy = build_model_aware_context_budget_policy(
        invocation_kind="single_agent_turn",
        model_selection={
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "context_budget_preset": "deepseek_1m",
        },
    )

    assert policy.requested_preset_id == "deepseek_1m"
    assert policy.effective_preset_id == "long_128k"
    assert policy.preset_status == "incompatible_model_downgraded"
    assert policy.context_window_tokens == 128_000
    assert policy.diagnostics["preset_rejection_reason"] == "provider_capability_does_not_support_requested_context_budget_preset"
    assert policy.diagnostics["provider_capability_source"] == "runtime.model_gateway.providers.openai_compatible"


def test_model_aware_context_budget_does_not_enable_deepseek_1m_for_non_v4_deepseek_models() -> None:
    policy = build_model_aware_context_budget_policy(
        invocation_kind="single_agent_turn",
        model_selection={
            "provider": "deepseek",
            "model": "deepseek-chat",
            "context_budget_preset": "deepseek_1m",
        },
    )

    assert policy.requested_preset_id == "deepseek_1m"
    assert policy.effective_preset_id == "long_128k"
    assert policy.preset_status == "incompatible_model_downgraded"
    assert policy.diagnostics["provider_capability_source"] == "runtime.model_gateway.providers.deepseek"
    assert "deepseek_1m" not in policy.diagnostics["provider_supported_context_budget_presets"]


def test_runtime_compiler_exposes_model_budget_policy_in_context_window_report() -> None:
    result = RuntimeCompiler().compile_single_agent_turn_packet(
        session_id="session:budget-policy",
        turn_id="turn:budget-policy",
        agent_invocation_id="aginvoke:budget-policy",
        user_message="继续审查上下文预算。",
        history=[],
        model_selection={
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "context_budget_preset": "deepseek_1m",
            "thinking_mode": "enabled",
            "reasoning_effort": "high",
        },
        runtime_assembly={
            "profile": {"mode": "professional"},
            "task_environment": {"environment_id": "env.general.workspace"},
            "operation_authorization": {"allowed_operations": ["op.model_response"]},
        },
    )

    budget_report = result.packet.diagnostics["prompt_manifest"]["context_window"]["budget_report"]
    policy = budget_report["context_budget_policy"]

    assert policy["authority"] == "harness.runtime.context_budget_policy"
    assert policy["effective_preset_id"] == "deepseek_1m"
    assert policy["context_window_tokens"] == 1_000_000
    assert budget_report["volatile_char_budget"] == policy["volatile_char_budget"]


def test_dynamic_context_manager_rebinds_to_runtime_assembly_backend_dir(tmp_path: Path) -> None:
    old_backend = tmp_path / "old_backend"
    new_backend = tmp_path / "new_backend"
    result = RuntimeCompiler(base_dir=old_backend).compile_task_execution_packet(
        session_id="session:backend-dir",
        task_run={"task_run_id": "taskrun:backend-dir", "diagnostics": {"executor_status": "running"}},
        contract={"task_run_goal": "验证动态上下文存储根目录", "completion_criteria": ["写入新 backend_dir"]},
        observations=[
            {
                "observation_id": "obs:backend-dir",
                "payload": {
                    "result_envelope": {
                        "envelope_id": "tool-result:backend-dir",
                        "tool_name": "read_file",
                        "status": "ok",
                        "text": "file content",
                    }
                },
            }
        ],
        runtime_assembly={
            "backend_dir": str(new_backend),
            "profile": {"mode": "professional"},
            "task_environment": {"environment_id": "env.test"},
            "operation_authorization": {"allowed_operations": ["op.read_file"]},
        },
    )

    assert result.packet.context_refs
    assert (new_backend / "runtime_state" / "dynamic_context" / "replacements").exists()
    assert not (old_backend / "runtime_state" / "dynamic_context" / "replacements").exists()


def test_prompt_segment_plan_can_enforce_dynamic_context_metadata() -> None:
    with pytest.raises(ValueError):
        build_prompt_segment_plan(
            packet_id="packet:missing-report",
            invocation_kind="task_execution",
            enforce_dynamic_context_reports=True,
            message_specs=[
                {
                    "role": "user",
                    "content": "Task execution current state\n{}",
                    "kind": "volatile_task_state",
                    "cache_role": "volatile",
                }
            ],
        )

    plan = build_prompt_segment_plan(
        packet_id="packet:with-report",
        invocation_kind="task_execution",
        enforce_dynamic_context_reports=True,
        message_specs=[
            {
                "role": "user",
                "content": "Task execution current state\n{}",
                "kind": "volatile_task_state",
                "cache_role": "volatile",
                "metadata": {
                    "dynamic_context_report_ref": "dynamic_context:task_execution:task_state",
                    "volatility_reason": "task state changes each step",
                },
            }
        ],
    )
    assert plan.segments[0].metadata["dynamic_context_report_ref"] == "dynamic_context:task_execution:task_state"


def test_dynamic_context_metadata_lookup_does_not_fallback_to_wrong_section() -> None:
    projection = DynamicContextProjection(
        section_reports=(
            VolatileSectionReport(
                section_id="dynamic_context:task_execution:runtime_delta",
                source="runtime_delta",
                volatility_reason="runtime delta changes by invocation",
            ),
        )
    )

    with pytest.raises(ValueError, match="execution_state"):
        _dynamic_context_segment_metadata(projection, source="execution_state")
