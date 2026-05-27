from __future__ import annotations

from typing import Any

from runtime.shared.artifact_refs import collect_task_result_output_refs


def _node_result_output_bundle(
    *,
    state: dict[str, Any],
    event: dict[str, Any],
    artifact_refs: list[str],
    mapped_outputs: dict[str, Any],
) -> dict[str, Any]:
    current_task_result = dict(state.get("current_task_result") or {})
    diagnostics = dict(event.get("diagnostics") or {})
    final_outputs = _first_dict(
        current_task_result.get("final_outputs"),
        diagnostics.get("task_result_outputs"),
        diagnostics.get("final_outputs"),
    )
    outputs = _first_dict(
        current_task_result.get("outputs"),
        diagnostics.get("outputs"),
        diagnostics.get("structured_outputs"),
    )
    task_result_diagnostics = _first_dict(current_task_result.get("diagnostics"))
    artifact_materialization = _first_dict(
        final_outputs.get("artifact_materialization"),
        task_result_diagnostics.get("artifact_materialization"),
        diagnostics.get("artifact_materialization"),
    )
    output_refs = collect_task_result_output_refs(current_task_result) or [
        str(item).strip()
        for item in list(event.get("artifact_refs") or artifact_refs or [])
        if str(item).strip()
    ]
    return {
        "mapped_outputs": dict(mapped_outputs or {}),
        "final_outputs": final_outputs,
        "outputs": outputs,
        "diagnostics": diagnostics,
        "task_result_diagnostics": task_result_diagnostics,
        "task_result": current_task_result,
        "artifact_materialization": artifact_materialization,
        "artifact_refs": list(artifact_refs or []),
        "output_refs": output_refs,
        "result_refs": [str(event.get("task_result_ref") or "")] if str(event.get("task_result_ref") or "") else [],
    }


def _structured_outputs_from_output_bundle(output_bundle: dict[str, Any]) -> dict[str, Any]:
    outputs: dict[str, Any] = {}
    for section in (
        "outputs",
        "final_outputs",
        "mapped_outputs",
    ):
        for key, value in dict(output_bundle.get(section) or {}).items():
            if str(key).strip():
                outputs[str(key).strip()] = value
    artifact_refs = [str(item).strip() for item in list(output_bundle.get("artifact_refs") or []) if str(item).strip()]
    output_refs = [str(item).strip() for item in list(output_bundle.get("output_refs") or []) if str(item).strip()]
    if artifact_refs:
        outputs.setdefault("artifact_refs", artifact_refs)
    if output_refs:
        outputs.setdefault("output_refs", output_refs)
    return outputs


def _extract_source_output_value(
    key: str,
    *,
    candidates: list[dict[str, Any]],
    output_bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_key = str(key or "").strip()
    if not source_key:
        return {"found": False}
    bundle = dict(output_bundle or {})
    direct_sources = [
        ("mapped_outputs", dict(bundle.get("mapped_outputs") or {})),
        ("final_outputs", dict(bundle.get("final_outputs") or {})),
        ("outputs", dict(bundle.get("outputs") or {})),
        ("diagnostics", dict(bundle.get("diagnostics") or {})),
        ("task_result_diagnostics", dict(bundle.get("task_result_diagnostics") or {})),
        ("artifact_materialization", dict(bundle.get("artifact_materialization") or {})),
    ]
    task_result = dict(bundle.get("task_result") or {})
    direct_sources.extend(
        [
            ("task_result.final_outputs", dict(task_result.get("final_outputs") or {})),
            ("task_result.outputs", dict(task_result.get("outputs") or {})),
            ("task_result", task_result),
        ]
    )
    for source_name, payload in direct_sources:
        if source_key in payload:
            return {"found": True, "value": payload.get(source_key), "source": source_name}
        nested = _lookup_path(payload, source_key)
        if nested.get("found"):
            return {"found": True, "value": nested.get("value"), "source": f"{source_name}.{source_key}"}
    if source_key in {"artifact_refs", "output_refs", "result_refs"}:
        values = [str(item).strip() for item in list(bundle.get(source_key) or []) if str(item).strip()]
        if values:
            return {"found": True, "value": values, "source": source_key}
    for index, candidate in enumerate(candidates):
        payload = dict(candidate.get("payload") or {}) if isinstance(candidate, dict) else {}
        if source_key in candidate:
            return {"found": True, "value": candidate.get(source_key), "source": f"working_memory_candidates[{index}]"}
        if str(candidate.get("output_key") or "").strip() == source_key:
            return {"found": True, "value": candidate, "source": f"working_memory_candidates[{index}]"}
        if source_key in payload:
            return {"found": True, "value": payload.get(source_key), "source": f"working_memory_candidates[{index}].payload"}
        nested = _lookup_path(payload, source_key)
        if nested.get("found"):
            return {"found": True, "value": nested.get("value"), "source": f"working_memory_candidates[{index}].payload.{source_key}"}
    return {"found": False}


def _candidate_from_source_output(
    *,
    source_output_key: str,
    value: Any,
    source: str,
    fallback_candidate: dict[str, Any],
) -> dict[str, Any]:
    fallback = dict(fallback_candidate or {})
    fallback_artifact_refs = _refs_from_output_value(fallback.get("artifact_refs"))
    if isinstance(value, dict):
        payload = dict(value)
        canonical_text = str(
            payload.get("canonical_text")
            or payload.get("text")
            or payload.get("content")
            or payload.get("markdown")
            or payload.get("body")
            or payload.get("final_answer")
            or ""
        ).strip()
        artifact_refs = _refs_from_output_value(payload.get("artifact_refs") or payload.get("output_refs")) or fallback_artifact_refs
        summary = str(payload.get("summary") or canonical_text or fallback.get("summary") or "").strip()
        title = str(payload.get("title") or fallback.get("title") or source_output_key).strip()
        kind = str(payload.get("kind") or fallback.get("kind") or "").strip()
        record_key = str(payload.get("record_key") or fallback.get("record_key") or "").strip()
    elif isinstance(value, str):
        canonical_text = value
        payload = {"source_output_key": source_output_key, source_output_key: value, "canonical_text": value}
        artifact_refs = fallback_artifact_refs
        summary = str(fallback.get("summary") or value[:280]).strip()
        title = str(fallback.get("title") or source_output_key).strip()
        kind = str(fallback.get("kind") or "").strip()
        record_key = str(fallback.get("record_key") or "").strip()
    else:
        payload = {"source_output_key": source_output_key, source_output_key: value}
        artifact_refs = _refs_from_output_value(value) if source_output_key in {"artifact_refs", "output_refs"} else fallback_artifact_refs
        canonical_text = "" if artifact_refs else _json_text(value)
        summary = str(fallback.get("summary") or canonical_text[:280] or source_output_key).strip()
        title = str(fallback.get("title") or source_output_key).strip()
        kind = str(fallback.get("kind") or "").strip()
        record_key = str(fallback.get("record_key") or "").strip()
    metadata = dict(fallback.get("metadata") or {})
    return {
        **fallback,
        "title": title,
        "summary": summary,
        "kind": kind or str(fallback.get("kind") or ""),
        "record_key": record_key,
        "canonical_text": canonical_text,
        "payload": payload,
        "artifact_refs": artifact_refs,
        "metadata": {
            **metadata,
            "source_output_key": source_output_key,
            "source_output_extraction": source,
        },
    }


def _lookup_path(payload: dict[str, Any], path: str) -> dict[str, Any]:
    if "." not in path:
        return {"found": False}
    current: Any = payload
    for part in [item for item in path.split(".") if item]:
        if not isinstance(current, dict) or part not in current:
            return {"found": False}
        current = current.get(part)
    return {"found": True, "value": current}


def _refs_from_output_value(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, dict):
        refs: list[str] = []
        for key in ("work_memory_id", "working_memory_ref", "version_id", "candidate_version_id", "ref"):
            item = str(value.get(key) or "").strip()
            if item and item not in refs:
                refs.append(item)
        for key in ("refs", "artifact_refs", "output_refs", "working_memory_refs", "formal_memory_refs"):
            for item in _refs_from_output_value(value.get(key)):
                if item not in refs:
                    refs.append(item)
        return refs
    if isinstance(value, (list, tuple, set)):
        refs: list[str] = []
        for item in value:
            for ref in _refs_from_output_value(item):
                if ref not in refs:
                    refs.append(ref)
        return refs
    return []


def _scalar_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("verdict", "status", "value", "result"):
            text = str(value.get(key) or "").strip()
            if text:
                return text
    return str(value or "").strip()


def _first_dict(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict):
            return dict(value)
    return {}


def _json_text(value: Any) -> str:
    try:
        import json

        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        return str(value or "")


def _contract_requires_file_artifact_refs(contract: dict[str, Any]) -> bool:
    artifact_policy = dict(contract.get("artifact_policy") or {})
    return bool(artifact_policy.get("enabled") or contract.get("artifact_targets") or contract.get("artifact_target") or contract.get("output_path"))


def _required_artifact_outputs_satisfied(
    output_mappings: list[dict[str, Any]],
    artifact_refs: list[str],
    *,
    requires_file_artifact_refs: bool,
) -> bool:
    if not requires_file_artifact_refs:
        return True
    if not _contract_has_required_artifact_outputs(output_mappings, requires_file_artifact_refs=requires_file_artifact_refs):
        return True
    return bool(artifact_refs)


def _contract_has_required_artifact_outputs(
    output_mappings: list[dict[str, Any]],
    *,
    requires_file_artifact_refs: bool,
) -> bool:
    if not requires_file_artifact_refs:
        return False
    return any(
        item.get("required") is True and str(item.get("output_key") or "").endswith(":artifact_refs")
        for item in output_mappings
        if isinstance(item, dict)
    )


def _latest_timeline_result_record(*, state: dict[str, Any], stage_id: str) -> dict[str, Any]:
    for item in reversed([dict(record) for record in list(state.get("timeline_result_records") or []) if isinstance(record, dict)]):
        if str(item.get("stage_id") or "") == stage_id:
            return item
    latest_id = str(dict(state.get("latest_stage_result_records") or {}).get(stage_id) or "")
    if latest_id:
        return dict(dict(state.get("result_record_index") or {}).get(latest_id) or {})
    return {}


def _stage_outputs_from_artifact_refs(*, contract: dict[str, Any], artifact_refs: list[str]) -> dict[str, Any]:
    outputs: dict[str, Any] = {}
    for mapping in [dict(item) for item in list(contract.get("output_mappings") or []) if isinstance(item, dict)]:
        output_key = str(mapping.get("output_key") or "").strip()
        if not output_key:
            continue
        outputs[output_key] = artifact_refs if mapping.get("single") is False else (artifact_refs[0] if artifact_refs else "")
    if artifact_refs:
        outputs.setdefault("artifact_refs", list(artifact_refs))
        outputs.setdefault("output_refs", list(artifact_refs))
    return outputs


def _collect_stage_outputs(stage_results: dict[str, Any]) -> dict[str, Any]:
    outputs: dict[str, Any] = {}
    for result in dict(stage_results or {}).values():
        if not isinstance(result, dict):
            continue
        for key, value in dict(result.get("outputs") or {}).items():
            if str(key):
                outputs[str(key)] = value
    return outputs

