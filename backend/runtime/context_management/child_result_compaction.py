from __future__ import annotations

from pathlib import Path
from typing import Any

from runtime_objects.tool_result_storage import DEFAULT_FIELD_SIZE_LIMIT_BYTES, DEFAULT_PREVIEW_SIZE_BYTES, ToolResultStore


def compact_child_result_observation(
    observation: dict[str, Any],
    *,
    root_dir: Path,
    run_id: str,
    field_limit_bytes: int = DEFAULT_FIELD_SIZE_LIMIT_BYTES,
    preview_size_bytes: int = DEFAULT_PREVIEW_SIZE_BYTES,
) -> dict[str, Any]:
    compact = dict(observation)
    evidence_summary = _evidence_summary_from_observation(compact)
    if evidence_summary:
        compact["answer_candidate"] = _compact_answer_candidate(
            summary=str(compact.get("summary") or ""),
            evidence_summary=evidence_summary,
            limitations=list(compact.get("limitations") or []),
        )
        compact["model_visible_evidence_summary"] = evidence_summary
    store = ToolResultStore(root_dir, run_id=run_id, namespace="runtime_context")
    budgeted, replacements = store.apply_budget(
        compact,
        field_limit_bytes=field_limit_bytes,
        preview_size_bytes=preview_size_bytes,
    )
    diagnostics = dict(budgeted.get("context_compaction") or {})
    diagnostics.update(
        {
            "applied": bool(replacements or evidence_summary),
            "mode": "child_result_observation_microcompact",
            "content_replacements": [item.to_dict() for item in replacements],
            "model_visible_evidence_summary_used": bool(evidence_summary),
        }
    )
    budgeted["context_compaction"] = diagnostics
    return budgeted


def _evidence_summary_from_observation(observation: dict[str, Any]) -> str:
    diagnostics = dict(observation.get("diagnostics") or {})
    direct = str(diagnostics.get("visible_packet_summary") or "").strip()
    if direct:
        return direct
    packet = dict(diagnostics.get("agent_evidence_packet") or {})
    if not packet:
        return ""
    lines = [
        f"Evidence packet {packet.get('packet_id') or ''} for {packet.get('domain') or 'other'}.",
        f"Confidence: {packet.get('confidence') or 'unknown'}.",
    ]
    facts = list(packet.get("facts") or [])
    if facts:
        lines.append("Facts:")
        for fact in facts[:4]:
            claim = str(dict(fact).get("claim") or "").strip()
            if claim:
                lines.append(f"- {claim}")
    unknowns = list(packet.get("unknowns") or [])
    if unknowns:
        lines.append("Unknowns:")
        for unknown in unknowns[:2]:
            description = str(dict(unknown).get("description") or "").strip()
            if description:
                lines.append(f"- {description}")
    return "\n".join(line for line in lines if line.strip()).strip()


def _compact_answer_candidate(*, summary: str, evidence_summary: str, limitations: list[Any]) -> str:
    lines = [str(summary or "").strip(), evidence_summary.strip()]
    clean_limits = [str(item).strip() for item in limitations if str(item).strip()]
    if clean_limits:
        lines.append("Limitations:")
        for item in clean_limits[:4]:
            lines.append(f"- {item}")
    return "\n".join(line for line in lines if line.strip()).strip()



