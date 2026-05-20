from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
from typing import Any

from project_layout import ProjectLayout

from .models import (
    HealthAgentConversationMessage,
    HealthAgentConversationSession,
    HealthAgentRun,
    HealthIssue,
    HealthManagementCommand,
    HealthManagementReceipt,
    HealthReport,
    HealthTaskRequest,
    HealthTestRun,
    VerificationArtifact,
    VerificationArtifactManifest,
    VerificationRun,
)


class HealthStore:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.store_dir = ProjectLayout.from_backend_dir(self.base_dir).health_system_dir
        self.issues_path = self.store_dir / "issues.jsonl"
        self.agent_runs_path = self.store_dir / "agent_runs.jsonl"
        self.agent_results_path = self.store_dir / "agent_results.jsonl"
        self.task_requests_path = self.store_dir / "task_requests.jsonl"
        self.commands_path = self.store_dir / "commands.jsonl"
        self.receipts_path = self.store_dir / "receipts.jsonl"
        self.reports_path = self.store_dir / "reports.jsonl"
        self.conversation_sessions_path = self.store_dir / "conversation_sessions.jsonl"
        self.conversation_messages_path = self.store_dir / "conversation_messages.jsonl"
        self.health_test_runs_path = self.store_dir / "health_test_runs.jsonl"
        self.verification_runs_path = self.store_dir / "verification_runs.jsonl"
        self.verification_manifests_path = self.store_dir / "verification_artifact_manifests.jsonl"
        self._bad_jsonl_line_count = 0

    def load_agent_runs(self) -> list[HealthAgentRun]:
        return [_agent_run_from_payload(item) for item in self._read_jsonl_dicts(self.agent_runs_path)]

    def load_issues(self) -> list[HealthIssue]:
        return [_issue_from_payload(item) for item in self._read_jsonl_dicts(self.issues_path)]

    def load_task_requests(self) -> list[HealthTaskRequest]:
        return [_task_request_from_payload(item) for item in self._read_jsonl_dicts(self.task_requests_path)]

    def load_commands(self) -> list[HealthManagementCommand]:
        return [_command_from_payload(item) for item in self._read_jsonl_dicts(self.commands_path)]

    def load_receipts(self) -> list[HealthManagementReceipt]:
        return [_receipt_from_payload(item) for item in self._read_jsonl_dicts(self.receipts_path)]

    def load_reports(self) -> list[HealthReport]:
        return [_report_from_payload(item) for item in self._read_jsonl_dicts(self.reports_path)]

    def load_conversation_sessions(self) -> list[HealthAgentConversationSession]:
        return [_conversation_session_from_payload(item) for item in self._read_jsonl_dicts(self.conversation_sessions_path)]

    def load_conversation_messages(self) -> list[HealthAgentConversationMessage]:
        return [_conversation_message_from_payload(item) for item in self._read_jsonl_dicts(self.conversation_messages_path)]

    def load_health_test_runs(self) -> list[HealthTestRun]:
        return [_health_test_run_from_payload(item) for item in self._read_jsonl_dicts(self.health_test_runs_path)]

    def load_verification_runs(self) -> list[VerificationRun]:
        return [_verification_run_from_payload(item) for item in self._read_jsonl_dicts(self.verification_runs_path)]

    def load_verification_artifact_manifests(self) -> list[VerificationArtifactManifest]:
        return [_verification_artifact_manifest_from_payload(item) for item in self._read_jsonl_dicts(self.verification_manifests_path)]

    def load_agent_results(self) -> list[dict[str, Any]]:
        return self._read_jsonl_dicts(self.agent_results_path)

    def store_health(self) -> dict[str, Any]:
        paths = [
            self.issues_path,
            self.agent_runs_path,
            self.agent_results_path,
            self.task_requests_path,
            self.commands_path,
            self.receipts_path,
            self.reports_path,
            self.conversation_sessions_path,
            self.conversation_messages_path,
            self.health_test_runs_path,
            self.verification_runs_path,
            self.verification_manifests_path,
        ]
        return {
            "authority": "health_system.store_health",
            "store_dir": str(self.store_dir),
            "bad_jsonl_line_count": self._bad_jsonl_line_count,
            "file_count": sum(1 for path in paths if path.exists()),
            "files": {
                path.name: {
                    "exists": path.exists(),
                    "size_bytes": path.stat().st_size if path.exists() else 0,
                }
                for path in paths
            },
        }

    def upsert_issue(self, issue: HealthIssue) -> None:
        issues = [item for item in self.load_issues() if item.issue_id != issue.issue_id]
        issues.append(issue)
        self._write_jsonl_models(self.issues_path, issues)

    def upsert_task_request(self, request: HealthTaskRequest) -> None:
        requests = [item for item in self.load_task_requests() if item.request_id != request.request_id]
        requests.append(request)
        self._write_jsonl_models(self.task_requests_path, requests)

    def upsert_command(self, command: HealthManagementCommand) -> None:
        self._upsert_jsonl(self.commands_path, "command_id", command.command_id, command.to_dict())

    def append_receipt(self, receipt: HealthManagementReceipt) -> None:
        self._append_jsonl(self.receipts_path, receipt.to_dict())

    def append_report(self, report: HealthReport) -> None:
        self._append_jsonl(self.reports_path, report.to_dict())

    def upsert_conversation_session(self, session: HealthAgentConversationSession) -> None:
        self._upsert_jsonl(self.conversation_sessions_path, "session_id", session.session_id, session.to_dict())

    def append_conversation_message(self, message: HealthAgentConversationMessage) -> None:
        self._append_jsonl(self.conversation_messages_path, message.to_dict())

    def upsert_health_test_run(self, run: HealthTestRun) -> None:
        self._upsert_jsonl(self.health_test_runs_path, "health_test_run_id", run.health_test_run_id, run.to_dict())

    def upsert_verification_run(self, run: VerificationRun) -> None:
        self._upsert_jsonl(self.verification_runs_path, "verification_run_id", run.verification_run_id, run.to_dict())

    def upsert_verification_artifact_manifest(self, manifest: VerificationArtifactManifest) -> None:
        self._upsert_jsonl(self.verification_manifests_path, "manifest_id", manifest.manifest_id, manifest.to_dict())

    def append_command_ref_to_session(self, session: HealthAgentConversationSession, command_id: str) -> HealthAgentConversationSession:
        command_refs = tuple(dict.fromkeys((*session.command_refs, command_id)))
        updated = HealthAgentConversationSession(
            session_id=session.session_id,
            agent_id=session.agent_id,
            agent_profile_id=session.agent_profile_id,
            workflow_id=session.workflow_id,
            runtime_lane=session.runtime_lane,
            active_issue_ref=session.active_issue_ref,
            active_run_ref=session.active_run_ref,
            command_refs=command_refs,
            status=session.status,
            created_at=session.created_at,
            updated_at=time.time(),
        )
        self.upsert_conversation_session(updated)
        return updated

    def upsert_agent_run(self, run: HealthAgentRun) -> None:
        runs = [item for item in self.load_agent_runs() if item.run_id != run.run_id]
        runs.append(run)
        self._write_jsonl_models(self.agent_runs_path, runs)

    def append_agent_result(self, payload: dict[str, Any]) -> None:
        self._append_jsonl(self.agent_results_path, payload)

    def _write_jsonl_models(self, path: Path, rows: list[Any]) -> None:
        self.store_dir.mkdir(parents=True, exist_ok=True)
        payloads = [
            item.to_dict() if hasattr(item, "to_dict") else dict(item)
            for item in rows
        ]
        self._atomic_write_text(path, "\n".join(json.dumps(item, ensure_ascii=False) for item in payloads) + ("\n" if payloads else ""))

    def _read_jsonl_dicts(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                self._bad_jsonl_line_count += 1
                continue
            if isinstance(payload, dict):
                rows.append(payload)
        return rows

    def _append_jsonl(self, path: Path, payload: dict[str, Any]) -> None:
        self.store_dir.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _upsert_jsonl(self, path: Path, key: str, value: str, payload: dict[str, Any]) -> None:
        self.store_dir.mkdir(parents=True, exist_ok=True)
        rows = [item for item in self._read_jsonl_dicts(path) if str(item.get(key) or "") != value]
        rows.append(payload)
        self._atomic_write_text(path, "\n".join(json.dumps(item, ensure_ascii=False) for item in rows) + ("\n" if rows else ""))

    def _atomic_write_text(self, path: Path, content: str) -> None:
        tmp_dir = path.parent
        tmp_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8", dir=tmp_dir, prefix=f".{path.stem}.", suffix=".tmp") as handle:
            handle.write(content)
            tmp_name = handle.name
        Path(tmp_name).replace(path)


def _agent_run_from_payload(payload: dict[str, Any]) -> HealthAgentRun:
    return HealthAgentRun(
        run_id=str(payload.get("run_id") or ""),
        request_id=str(payload.get("request_id") or ""),
        issue_id=str(payload.get("issue_id") or ""),
        task_run_id=str(payload.get("task_run_id") or ""),
        agent_id=str(payload.get("agent_id") or ""),
        agent_profile_id=str(payload.get("agent_profile_id") or ""),
        runtime_lane=str(payload.get("runtime_lane") or ""),
        health_action=str(payload.get("health_action") or ""),
        workflow_id=str(payload.get("workflow_id") or ""),
        admission_status=str(payload.get("admission_status") or ""),
        projection_id=str(payload.get("projection_id") or ""),
        prompt_manifest_id=str(payload.get("prompt_manifest_id") or ""),
        status=str(payload.get("status") or "unknown"),
        terminal_reason=str(payload.get("terminal_reason") or ""),
        blocked_reasons=tuple(str(item) for item in list(payload.get("blocked_reasons") or [])),
        report_refs=tuple(str(item) for item in list(payload.get("report_refs") or [])),
        trace_refs=tuple(str(item) for item in list(payload.get("trace_refs") or [])),
        artifact_refs=tuple(str(item) for item in list(payload.get("artifact_refs") or [])),
        result_ref=str(payload.get("result_ref") or ""),
        created_at=float(payload.get("created_at") or 0.0),
        metadata=dict(payload.get("metadata") or {}),
    )


def _issue_from_payload(payload: dict[str, Any]) -> HealthIssue:
    return HealthIssue(
        issue_id=str(payload.get("issue_id") or ""),
        title=str(payload.get("title") or ""),
        owner_system=str(payload.get("owner_system") or ""),
        severity=str(payload.get("severity") or "medium"),
        status=str(payload.get("status") or "triage_ready"),
        source=str(payload.get("source") or "manual"),
        conversation_ref=str(payload.get("conversation_ref") or ""),
        runtime_trace_refs=tuple(str(item) for item in list(payload.get("runtime_trace_refs") or [])),
        prompt_manifest_refs=tuple(str(item) for item in list(payload.get("prompt_manifest_refs") or [])),
        memory_refs=tuple(str(item) for item in list(payload.get("memory_refs") or [])),
        assertion_refs=tuple(str(item) for item in list(payload.get("assertion_refs") or [])),
        duplicate_of=str(payload.get("duplicate_of") or ""),
        created_at=float(payload.get("created_at") or 0.0),
        updated_at=float(payload.get("updated_at") or 0.0),
        metadata=dict(payload.get("metadata") or {}),
    )


def _task_request_from_payload(payload: dict[str, Any]) -> HealthTaskRequest:
    return HealthTaskRequest(
        request_id=str(payload.get("request_id") or ""),
        issue_id=str(payload.get("issue_id") or ""),
        task_kind=str(payload.get("task_kind") or ""),
        task_id=str(payload.get("task_id") or ""),
        flow_id=str(payload.get("flow_id") or ""),
        required_evidence_refs=tuple(str(item) for item in list(payload.get("required_evidence_refs") or [])),
        requested_by=str(payload.get("requested_by") or ""),
        created_at=float(payload.get("created_at") or 0.0),
        metadata=dict(payload.get("metadata") or {}),
    )


def _command_from_payload(payload: dict[str, Any]) -> HealthManagementCommand:
    return HealthManagementCommand(
        command_id=str(payload.get("command_id") or ""),
        command_type=str(payload.get("command_type") or ""),
        initiator_type=str(payload.get("initiator_type") or "user"),
        initiator_ref=str(payload.get("initiator_ref") or ""),
        requested_by=str(payload.get("requested_by") or ""),
        source=str(payload.get("source") or "health_system.command_api"),
        conversation_session_ref=str(payload.get("conversation_session_ref") or ""),
        target_scope=str(payload.get("target_scope") or ""),
        target_ref=str(payload.get("target_ref") or ""),
        health_action=str(payload.get("health_action") or ""),
        payload=dict(payload.get("payload") or {}),
        status=str(payload.get("status") or "pending"),
        created_at=float(payload.get("created_at") or 0.0),
        updated_at=float(payload.get("updated_at") or 0.0),
    )


def _receipt_from_payload(payload: dict[str, Any]) -> HealthManagementReceipt:
    return HealthManagementReceipt(
        receipt_id=str(payload.get("receipt_id") or ""),
        command_ref=str(payload.get("command_ref") or ""),
        accepted=bool(payload.get("accepted", False)),
        status=str(payload.get("status") or "unknown"),
        health_issue_ref=str(payload.get("health_issue_ref") or ""),
        health_run_ref=str(payload.get("health_run_ref") or ""),
        test_run_ref=str(payload.get("test_run_ref") or ""),
        verification_run_ref=str(payload.get("verification_run_ref") or ""),
        report_ref=str(payload.get("report_ref") or ""),
        admission_status=str(payload.get("admission_status") or ""),
        run_status=str(payload.get("run_status") or ""),
        blocked_reasons=tuple(str(item) for item in list(payload.get("blocked_reasons") or [])),
        diagnostics=dict(payload.get("diagnostics") or {}),
        created_at=float(payload.get("created_at") or 0.0),
    )


def _report_from_payload(payload: dict[str, Any]) -> HealthReport:
    return HealthReport(
        report_id=str(payload.get("report_id") or ""),
        report_type=str(payload.get("report_type") or ""),
        issue_ref=str(payload.get("issue_ref") or ""),
        command_ref=str(payload.get("command_ref") or ""),
        agent_run_ref=str(payload.get("agent_run_ref") or ""),
        test_run_ref=str(payload.get("test_run_ref") or ""),
        evidence_refs=tuple(str(item) for item in list(payload.get("evidence_refs") or [])),
        verdict=str(payload.get("verdict") or "unknown"),
        severity=str(payload.get("severity") or "medium"),
        summary=str(payload.get("summary") or ""),
        recommended_actions=tuple(str(item) for item in list(payload.get("recommended_actions") or [])),
        created_at=float(payload.get("created_at") or 0.0),
    )


def _conversation_session_from_payload(payload: dict[str, Any]) -> HealthAgentConversationSession:
    return HealthAgentConversationSession(
        session_id=str(payload.get("session_id") or ""),
        agent_id=str(payload.get("agent_id") or ""),
        agent_profile_id=str(payload.get("agent_profile_id") or ""),
        workflow_id=str(payload.get("workflow_id") or payload.get("skill_workflow_id") or ""),
        runtime_lane=str(payload.get("runtime_lane") or ""),
        active_issue_ref=str(payload.get("active_issue_ref") or ""),
        active_run_ref=str(payload.get("active_run_ref") or ""),
        command_refs=tuple(str(item) for item in list(payload.get("command_refs") or [])),
        status=str(payload.get("status") or "active"),
        created_at=float(payload.get("created_at") or 0.0),
        updated_at=float(payload.get("updated_at") or 0.0),
    )


def _conversation_message_from_payload(payload: dict[str, Any]) -> HealthAgentConversationMessage:
    return HealthAgentConversationMessage(
        message_id=str(payload.get("message_id") or ""),
        session_id=str(payload.get("session_id") or ""),
        role=str(payload.get("role") or "user"),
        content=str(payload.get("content") or ""),
        command_ref=str(payload.get("command_ref") or ""),
        receipt_ref=str(payload.get("receipt_ref") or ""),
        report_ref=str(payload.get("report_ref") or ""),
        created_at=float(payload.get("created_at") or 0.0),
    )


def _health_test_run_from_payload(payload: dict[str, Any]) -> HealthTestRun:
    return HealthTestRun(
        health_test_run_id=str(payload.get("health_test_run_id") or ""),
        command_ref=str(payload.get("command_ref") or ""),
        test_system_run_ref=str(payload.get("test_system_run_ref") or ""),
        profile=str(payload.get("profile") or ""),
        scenario_refs=tuple(str(item) for item in list(payload.get("scenario_refs") or [])),
        status=str(payload.get("status") or "unknown"),
        verdict=str(payload.get("verdict") or "unknown"),
        artifact_refs=tuple(str(item) for item in list(payload.get("artifact_refs") or [])),
        issue_refs=tuple(str(item) for item in list(payload.get("issue_refs") or [])),
        report_refs=tuple(str(item) for item in list(payload.get("report_refs") or [])),
        started_at=float(payload.get("started_at") or 0.0),
        finished_at=float(payload.get("finished_at") or 0.0),
    )


def _verification_artifact_from_payload(payload: dict[str, Any]) -> VerificationArtifact:
    return VerificationArtifact(
        name=str(payload.get("name") or ""),
        artifact_type=str(payload.get("artifact_type") or payload.get("type") or ""),
        path=str(payload.get("path") or ""),
        relative_ref=str(payload.get("relative_ref") or ""),
        producer=str(payload.get("producer") or ""),
        required=bool(payload.get("required", False)),
        present=bool(payload.get("present", False)),
        checksum=str(payload.get("checksum") or ""),
        size_bytes=int(payload.get("size_bytes") or 0),
    )


def _verification_artifact_manifest_from_payload(payload: dict[str, Any]) -> VerificationArtifactManifest:
    return VerificationArtifactManifest(
        manifest_id=str(payload.get("manifest_id") or ""),
        verification_run_id=str(payload.get("verification_run_id") or ""),
        schema_version=str(payload.get("schema_version") or "2026-05-08"),
        artifacts=tuple(
            _verification_artifact_from_payload(item)
            for item in list(payload.get("artifacts") or [])
            if isinstance(item, dict)
        ),
        created_at=float(payload.get("created_at") or 0.0),
        metadata=dict(payload.get("metadata") or {}),
    )


def _verification_run_from_payload(payload: dict[str, Any]) -> VerificationRun:
    return VerificationRun(
        verification_run_id=str(payload.get("verification_run_id") or ""),
        profile_id=str(payload.get("profile_id") or payload.get("profile") or ""),
        status=str(payload.get("status") or "unknown"),
        command_ref=str(payload.get("command_ref") or ""),
        source_run_ref=str(payload.get("source_run_ref") or ""),
        process_ref=str(payload.get("process_ref") or ""),
        output_dir=str(payload.get("output_dir") or ""),
        log_path=str(payload.get("log_path") or ""),
        artifact_manifest_ref=str(payload.get("artifact_manifest_ref") or ""),
        summary=dict(payload.get("summary") or {}),
        artifact_refs=tuple(str(item) for item in list(payload.get("artifact_refs") or [])),
        issue_refs=tuple(str(item) for item in list(payload.get("issue_refs") or [])),
        report_refs=tuple(str(item) for item in list(payload.get("report_refs") or [])),
        trace_refs=tuple(str(item) for item in list(payload.get("trace_refs") or [])),
        started_at=float(payload.get("started_at") or 0.0),
        ended_at=float(payload.get("ended_at") or 0.0),
        metadata=dict(payload.get("metadata") or {}),
    )
