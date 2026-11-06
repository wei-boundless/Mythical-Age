from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Any

from capability_system.capabilities.office_document import OfficeDocumentRequest, OfficeDocumentRuntime
from capability_system.tools.workspace_file_service import WorkspaceFileService
from evidence.models import EvidenceArtifact, EvidenceEnvelope, EvidenceItem, SourceObjectRef
from .mcp_models import CanonicalResult, MCPRequest, MCPResult


class OfficeDocumentWorker:
    def __init__(
        self,
        *,
        root_dir: Path | str,
        runtime: OfficeDocumentRuntime | None = None,
    ) -> None:
        self.root_dir = Path(root_dir).resolve()
        self.files = WorkspaceFileService(self.root_dir)
        self.runtime = runtime or OfficeDocumentRuntime(repo_root=self.files.workspace_root)

    async def run(self, request: MCPRequest) -> MCPResult:
        path_text = self._request_path(request)
        if not path_text:
            return _missing_path_result()
        action = self._request_action(request)
        try:
            source_path = self.files.resolve(path_text, require_path=True)
            output_path = self._output_path(request)
        except ValueError as exc:
            return _error_result(str(exc) or "office_document_path_resolution_failed")

        result = await asyncio.to_thread(
            self.runtime.run,
            OfficeDocumentRequest(
                action=action,
                source_path=source_path,
                output_path=output_path,
                target_file_type=str(request.constraints.get("target_file_type") or "").strip().lower(),
                root_dir=self.files.workspace_root,
                read_scope=str(request.constraints.get("read_scope") or "document").strip() or "document",
                max_blocks=_safe_int(request.constraints.get("max_blocks"), default=80, minimum=1, maximum=400),
                metadata={
                    "operations": [dict(item) for item in list(request.constraints.get("operations") or []) if isinstance(item, dict)],
                    "allow_overwrite": bool(request.constraints.get("allow_overwrite", False)),
                    "verification_level": str(request.constraints.get("verification_level") or "semantic").strip() or "semantic",
                    "target_file_type": str(request.constraints.get("target_file_type") or "").strip().lower(),
                },
            ),
        )
        payload = result.to_dict()
        rel_source = self.files.relative_path(source_path)
        rel_output = self.files.relative_path(payload["output_path"]) if payload.get("output_path") else ""
        ok = bool(payload.get("ok"))
        status = str(payload.get("status") or ("ok" if ok else "error"))
        return MCPResult(
            mcp_name="office_document",
            status="ok" if ok else "clarify" if status == "clarify" else "degraded" if status == "degraded" else "error",
            evidence_envelope=self._to_evidence_envelope(
                request=request,
                payload=payload,
                source_path=rel_source,
                output_path=rel_output,
            ),
            canonical_result=self._to_canonical_result(payload=payload, source_path=rel_source, output_path=rel_output),
            emitted_object_handles=self._object_handles(payload=payload, source_path=rel_source, output_path=rel_output),
            emitted_result_handles=self._result_handles(payload=payload, source_path=rel_source, output_path=rel_output),
            diagnostics={
                "answer_source": "office_document_worker",
                "office_document_status": status,
                "action": str(payload.get("action") or action),
                "file_type": str(payload.get("file_type") or ""),
                "limitations": list(payload.get("limitations") or []),
            },
            binding_owner_task_id=str(request.owner_task_id or "").strip(),
        )

    def _request_path(self, request: MCPRequest) -> str:
        candidates = [
            request.bindings.get("active_document"),
            request.constraints.get("path"),
            request.task_frame.get("active_document"),
            request.task_frame.get("path"),
        ]
        for item in candidates:
            value = str(item or "").strip()
            if value:
                return value
        return ""

    def _request_action(self, request: MCPRequest) -> str:
        action = str(request.constraints.get("action") or request.constraints.get("mode") or "").strip().lower()
        if action:
            return action
        query = str(request.query or "").lower()
        if any(token in query for token in ("创建", "新建", "create")):
            return "create"
        if any(token in query for token in ("编辑", "修改", "替换", "edit", "update")):
            return "edit"
        return "inspect"

    def _output_path(self, request: MCPRequest) -> Path | None:
        value = str(request.constraints.get("output_path") or "").strip()
        return self.files.resolve(value, require_path=True) if value else None

    def _to_evidence_envelope(
        self,
        *,
        request: MCPRequest,
        payload: dict[str, Any],
        source_path: str,
        output_path: str,
    ) -> EvidenceEnvelope:
        source_object_id = _stable_id("source:office_document", source_path)
        output_object_id = _stable_id("artifact:office_document", output_path or source_path)
        preview = _preview(payload)
        source_object = SourceObjectRef(
            object_id=source_object_id,
            object_type="office_document",
            uri=source_path,
            locator={"path": source_path, "file_type": str(payload.get("file_type") or "")},
            metadata={
                "action": str(payload.get("action") or ""),
                "status": str(payload.get("status") or ""),
                "output_path": output_path,
            },
        )
        artifacts: list[EvidenceArtifact] = []
        if output_path:
            artifacts.append(
                EvidenceArtifact(
                    artifact_id=output_object_id,
                    artifact_type="office_document",
                    source_object_id=source_object_id,
                    content_ref=output_path,
                    canonical_preview=preview[:220],
                    visibility="model_visible" if payload.get("ok") else "debug_only",
                    consumable_by=["office_document", "answer_finalizer"],
                    metadata={
                        "path": output_path,
                        "plan_id": str(payload.get("patch_plan_id") or ""),
                        "verified": bool(dict(payload.get("verification_report") or {}).get("ok")),
                    },
                )
            )
        evidence_items = [
            EvidenceItem(
                kind="office_document_result",
                source=output_path or source_path,
                text=preview,
                score=1.0 if payload.get("ok") else 0.0,
                metadata={
                    "source_object_id": source_object_id,
                    "artifact_id": output_object_id if output_path else "",
                    "action": str(payload.get("action") or ""),
                    "file_type": str(payload.get("file_type") or ""),
                },
                visibility="model_visible" if preview and payload.get("ok") else "debug_only",
            )
        ] if preview else []
        return EvidenceEnvelope(
            query=str(request.query or "").strip(),
            source_mcp="office_document",
            evidence_items=evidence_items,
            source_objects=[source_object],
            derived_artifacts=artifacts,
            diagnostics={
                "office_document_status": str(payload.get("status") or ""),
                "action": str(payload.get("action") or ""),
                "output_path": output_path,
                "evidence_count": len(evidence_items),
            },
        )

    def _to_canonical_result(self, *, payload: dict[str, Any], source_path: str, output_path: str) -> CanonicalResult:
        ok = bool(payload.get("ok"))
        answer = str(payload.get("summary") or "").strip() if ok else ""
        source_object_id = _stable_id("source:office_document", source_path)
        result_handle_id = _stable_id("result:office_document", f"{source_path}:{output_path}:{payload.get('patch_plan_id')}")
        return CanonicalResult(
            result_kind="office_document_result",
            ok=ok,
            answer=answer,
            artifact_refs=[output_path] if output_path else [],
            bindings={
                "active_document": output_path or source_path,
                **({"office_output_path": output_path} if output_path else {}),
            },
            projection_policy="persist_canonical" if ok else "do_not_persist",
            degraded_reason="" if ok else str(payload.get("summary") or "office_document_operation_failed"),
            diagnostics={
                "answer_source": "office_document_worker",
                "office_document": payload,
            },
            object_handle_ids=[source_object_id],
            result_handle_ids=[result_handle_id],
            primary_result_handle_id=result_handle_id,
            degraded_reason_typed="" if ok else _typed_reason(payload),
        )

    def _object_handles(self, *, payload: dict[str, Any], source_path: str, output_path: str) -> list[dict[str, Any]]:
        handles = [
            {
                "handle_id": _stable_id("source:office_document", source_path),
                "handle_kind": "source_object",
                "object_type": "office_document",
                "uri": source_path,
                "file_type": str(payload.get("file_type") or ""),
            }
        ]
        if output_path:
            handles.append(
                {
                    "handle_id": _stable_id("artifact:office_document", output_path),
                    "handle_kind": "artifact",
                    "artifact_type": "office_document",
                    "uri": output_path,
                    "file_type": str(payload.get("file_type") or ""),
                }
            )
        return handles

    def _result_handles(self, *, payload: dict[str, Any], source_path: str, output_path: str) -> list[dict[str, Any]]:
        return [
            {
                "handle_id": _stable_id("result:office_document", f"{source_path}:{output_path}:{payload.get('patch_plan_id')}"),
                "handle_kind": "result",
                "result_kind": "office_document_result",
                "object_handle_id": _stable_id("source:office_document", source_path),
                "artifact_path": output_path,
                "action": str(payload.get("action") or ""),
            }
        ]


def _missing_path_result() -> MCPResult:
    return MCPResult(
        mcp_name="office_document",
        status="clarify",
        canonical_result=CanonicalResult(
            result_kind="office_document_result",
            ok=False,
            answer="",
            projection_policy="do_not_persist",
            degraded_reason="missing_office_document_path",
            diagnostics={"answer_source": "office_document_worker"},
            degraded_reason_typed="missing_object_handle",
        ),
    )


def _error_result(reason: str) -> MCPResult:
    return MCPResult(
        mcp_name="office_document",
        status="error",
        canonical_result=CanonicalResult(
            result_kind="office_document_result",
            ok=False,
            answer="",
            projection_policy="do_not_persist",
            degraded_reason=reason,
            diagnostics={"answer_source": "office_document_worker", "reason": reason},
            degraded_reason_typed="contract_blocked",
        ),
    )


def _preview(payload: dict[str, Any]) -> str:
    summary = str(payload.get("summary") or "").strip()
    blocks = list(payload.get("extracted_content") or [])
    block_text = "\n".join(str(item.get("text") or "").strip() for item in blocks[:8] if isinstance(item, dict) and str(item.get("text") or "").strip())
    return "\n".join(item for item in (summary, block_text) if item).strip()


def _typed_reason(payload: dict[str, Any]) -> str:
    limitations = [str(item or "").strip() for item in list(payload.get("limitations") or []) if str(item or "").strip()]
    if limitations:
        return limitations[0]
    status = str(payload.get("status") or "").strip()
    return status or "office_document_operation_failed"


def _safe_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha1(str(value or "").encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"
