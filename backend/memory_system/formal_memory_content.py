from __future__ import annotations

from pathlib import Path
from typing import Any


def materialize_formal_memory_candidate(
    *,
    candidate: dict[str, Any],
    edge: dict[str, Any],
    fallback_write_policy: dict[str, Any],
    output_bundle: dict[str, Any] | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    policy = formal_memory_materialization_policy(
        edge=edge,
        fallback_write_policy=fallback_write_policy,
    )
    content_requirement = formal_memory_content_requirement_from_payloads(
        edge=edge,
        policy=policy,
        candidate=candidate,
    )
    candidate = {
        **dict(candidate),
        **({"content_requirement": content_requirement} if content_requirement else {}),
    }
    payload = dict(candidate.get("payload") or {})
    if _candidate_has_canonical_text(candidate, payload=payload):
        return candidate, []
    if policy and policy.get("enabled") is False:
        return candidate, formal_memory_content_requirement_errors(
            edge=edge,
            candidate=candidate,
            content_requirement=content_requirement,
            reason="materialization_disabled",
        )
    materialization_required = bool(content_requirement.get("canonical_text_required")) or bool(policy.get("enabled"))
    if not materialization_required:
        return candidate, []
    source_value = _materialization_source_value(
        candidate=candidate,
        policy=policy,
        output_bundle=output_bundle,
    )
    refs = formal_memory_artifact_refs_from_value(source_value)
    if not refs:
        refs = formal_memory_artifact_refs_from_value(candidate.get("artifact_refs"))
    filters = dict(policy.get("artifact_filters") or policy.get("artifact_ref_filters") or {})
    refs = filter_materialization_artifact_refs(refs, filters=filters)
    texts: list[tuple[str, str]] = []
    max_chars = max(_safe_int(policy.get("max_chars"), 0), 0)
    artifact_roots = _materialization_artifact_roots(output_bundle=output_bundle, policy=policy)
    for ref in refs:
        text = read_artifact_ref_text(ref, roots=artifact_roots)
        if not text:
            continue
        texts.append((ref, text[:max_chars] if max_chars else text))
    if not texts:
        return candidate, formal_memory_content_requirement_errors(
            edge=edge,
            candidate={**candidate, "artifact_refs": refs or list(candidate.get("artifact_refs") or [])},
            content_requirement=content_requirement,
            reason="artifact_text_not_available",
        )
    canonical_text_mode = str(policy.get("canonical_text_mode") or policy.get("mode") or "full_text").strip()
    if canonical_text_mode in {"none", "refs_only"}:
        canonical_text = ""
    else:
        canonical_text = "\n\n".join(text for _, text in texts).strip()
    summary_mode = str(policy.get("summary_mode") or "").strip()
    summary = str(candidate.get("summary") or "").strip()
    generic_summary_values = {
        "",
        "artifact_refs",
        "output_refs",
        str(policy.get("source_output_key") or "").strip(),
        str(policy.get("source_key") or "").strip(),
    }
    if summary in generic_summary_values and canonical_text:
        summary = summary_from_text(canonical_text, mode=summary_mode)
    payload = {
        **payload,
        "canonical_text": canonical_text,
        "materialized_from_artifact_refs": [ref for ref, _ in texts],
        "materialization_policy": policy,
    }
    materialized = {
        **candidate,
        "canonical_text": canonical_text,
        "summary": summary,
        "payload": payload,
        "artifact_refs": refs or [ref for ref, _ in texts],
        "metadata": {
            **dict(candidate.get("metadata") or {}),
            "formal_memory_materialization": {
                "source": str(policy.get("source") or "artifact_refs"),
                "artifact_refs": [ref for ref, _ in texts],
                "canonical_text_mode": canonical_text_mode,
                "authority": "formal_memory.materialization_policy",
            },
        },
    }
    return materialized, formal_memory_content_requirement_errors(
        edge=edge,
        candidate=materialized,
        content_requirement=content_requirement,
        reason="content_requirement_not_satisfied_after_materialization",
    )


def formal_memory_materialization_policy(
    *,
    edge: dict[str, Any],
    fallback_write_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fallback = dict(fallback_write_policy or {})
    return dict(
        edge.get("materialization_policy")
        or edge.get("candidate_materialization_policy")
        or fallback.get("candidate_materialization_policy")
        or fallback.get("materialization_policy")
        or {}
    )


def formal_memory_content_requirement_from_payloads(
    *,
    edge: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
    candidate: dict[str, Any] | None = None,
    collection_requirement: dict[str, Any] | None = None,
) -> dict[str, Any]:
    edge_payload = dict(edge or {})
    candidate_payload = dict(candidate or {})
    selector = dict(edge_payload.get("selector") or {})
    metadata = dict(candidate_payload.get("metadata") or {})
    requirement = _merge_content_requirements(
        trusted=[
            dict(collection_requirement or {}),
            dict(edge_payload.get("content_requirement") or {}),
            dict(selector.get("content_requirement") or {}),
            dict((policy or {}).get("content_requirement") or {}),
        ],
        candidate=[
            dict(candidate_payload.get("content_requirement") or {}),
            dict(metadata.get("content_requirement") or {}),
        ],
    )
    return {str(key): value for key, value in requirement.items() if str(key).strip()}


def formal_memory_artifact_refs_from_value(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip().startswith("artifact:") else []
    if isinstance(value, dict):
        refs: list[str] = []
        for key in ("artifact_refs", "output_refs", "refs", "source_artifact_refs"):
            for ref in formal_memory_artifact_refs_from_value(value.get(key)):
                if ref not in refs:
                    refs.append(ref)
        return refs
    if isinstance(value, (list, tuple, set)):
        refs: list[str] = []
        for item in value:
            for ref in formal_memory_artifact_refs_from_value(item):
                if ref not in refs:
                    refs.append(ref)
        return refs
    return []


def filter_materialization_artifact_refs(refs: list[str], *, filters: dict[str, Any]) -> list[str]:
    include_extensions = {
        str(item).strip().lower()
        for item in list(filters.get("include_extensions") or [".md", ".txt", ".json"])
        if str(item).strip()
    }
    exclude_contains = [
        str(item).strip().replace("\\", "/")
        for item in list(filters.get("exclude_path_contains") or ["/debug/", "\\debug\\", "/run_report", "run_report"])
        if str(item).strip()
    ]
    filtered: list[str] = []
    for ref in refs:
        raw = str(ref or "").strip()
        if not raw.startswith("artifact:"):
            continue
        normalized = raw.replace("\\", "/")
        if any(item and item in normalized for item in exclude_contains):
            continue
        suffix = Path(normalized.removeprefix("artifact:")).suffix.lower()
        if include_extensions and suffix and suffix not in include_extensions:
            continue
        if raw not in filtered:
            filtered.append(raw)
    return filtered


def read_artifact_ref_text(ref: str, *, roots: list[str | Path] | tuple[str | Path, ...] = ()) -> str:
    raw = str(ref or "").strip()
    if not raw.startswith("artifact:"):
        return ""
    rel = raw[len("artifact:") :]
    relative = Path(rel)
    candidates: list[Path] = []
    for root in roots:
        root_path = Path(root)
        candidates.append(root_path / relative)
    if relative.is_absolute():
        candidates.append(relative)
    seen: set[str] = set()
    for path in candidates:
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        try:
            if resolved.exists() and resolved.is_file():
                return resolved.read_text(encoding="utf-8")
        except OSError:
            continue
    return ""


def summary_from_text(text: str, *, mode: str = "") -> str:
    stripped = str(text or "").strip()
    if not stripped:
        return ""
    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    if mode in {"first_heading", "first_heading_or_excerpt"}:
        for line in lines:
            if line.startswith("#"):
                return line.lstrip("#").strip()[:500]
    return stripped[:500]


def formal_memory_content_requirement_errors(
    *,
    edge: dict[str, Any],
    candidate: dict[str, Any],
    content_requirement: dict[str, Any],
    reason: str,
) -> list[dict[str, Any]]:
    requirement = dict(content_requirement or {})
    if not requirement:
        return []
    canonical_text = str(candidate.get("canonical_text") or dict(candidate.get("payload") or {}).get("canonical_text") or "").strip()
    summary = str(candidate.get("summary") or "").strip()
    refs = formal_memory_artifact_refs_from_value(candidate.get("artifact_refs"))
    has_refs = bool(refs)
    if bool(requirement.get("canonical_text_required")) and not canonical_text:
        if not (has_refs and bool(requirement.get("artifact_ref_only_allowed"))):
            return [
                {
                    "edge_id": str(edge.get("edge_id") or ""),
                    "repository_id": str(edge.get("repository") or ""),
                    "collection_id": str(edge.get("collection") or ""),
                    "error": reason,
                    "severity": "error",
                    "content_requirement": requirement,
                    "content_state": "refs_only" if has_refs else "empty",
                }
            ]
    if bool(requirement.get("summary_required")) and not summary:
        return [
            {
                "edge_id": str(edge.get("edge_id") or ""),
                "repository_id": str(edge.get("repository") or ""),
                "collection_id": str(edge.get("collection") or ""),
                "error": "summary_required",
                "severity": "error",
                "content_requirement": requirement,
            }
        ]
    return []


def formal_memory_content_state(*, canonical_text: str, artifact_refs: list[str] | tuple[str, ...]) -> str:
    if str(canonical_text or "").strip():
        return "canonical"
    if _strings(artifact_refs):
        return "refs_only"
    return "empty"


def formal_memory_content_requirement_satisfied(
    *,
    canonical_text: str,
    summary: str,
    artifact_refs: list[str] | tuple[str, ...],
    requirement: dict[str, Any],
) -> bool:
    policy = dict(requirement or {})
    if not policy:
        return True
    has_canonical = bool(str(canonical_text or "").strip())
    has_summary = bool(str(summary or "").strip())
    has_refs = bool(_strings(artifact_refs))
    if bool(policy.get("canonical_text_required")) and not has_canonical:
        if not (has_refs and bool(policy.get("artifact_ref_only_allowed"))):
            return False
    if bool(policy.get("summary_required")) and not has_summary:
        return False
    if has_refs and policy.get("artifact_refs_allowed") is False:
        return False
    if not has_canonical and has_refs and policy.get("artifact_ref_only_allowed") is False:
        return False
    return True


def formal_memory_content_warnings(
    *,
    canonical_text: str,
    artifact_refs: list[str] | tuple[str, ...],
    requirement: dict[str, Any],
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    if not str(canonical_text or "").strip() and _strings(artifact_refs):
        warnings.append(
            {
                "code": "formal_memory_record_refs_only",
                "message": "This formal memory record has artifact refs but no canonical_text.",
                "blocks_required_canonical_memory": not bool(dict(requirement or {}).get("artifact_ref_only_allowed")),
            }
        )
    return warnings


def _candidate_has_canonical_text(candidate: dict[str, Any], *, payload: dict[str, Any]) -> bool:
    return bool(
        str(
            candidate.get("canonical_text")
            or payload.get("canonical_text")
            or payload.get("text")
            or payload.get("content")
            or ""
        ).strip()
    )


def _materialization_source_value(
    *,
    candidate: dict[str, Any],
    policy: dict[str, Any],
    output_bundle: dict[str, Any] | None,
) -> Any:
    source_key = str(policy.get("source_output_key") or policy.get("source_key") or "").strip()
    if source_key:
        extraction = _extract_source_output_value(source_key, candidates=[candidate], output_bundle=output_bundle)
        if extraction.get("found"):
            return extraction.get("value")
    source = str(policy.get("source") or "artifact_refs").strip()
    if source in {"output_refs", "accepted_artifact_refs"}:
        return dict(output_bundle or {}).get("output_refs")
    if source in {"result_artifact_refs", "artifact_refs"}:
        return dict(output_bundle or {}).get("artifact_refs") or candidate.get("artifact_refs")
    if source == "candidate_payload":
        return dict(candidate.get("payload") or {})
    return candidate.get("artifact_refs") or dict(output_bundle or {}).get("artifact_refs")


def _materialization_artifact_roots(
    *,
    output_bundle: dict[str, Any] | None,
    policy: dict[str, Any],
) -> list[Path]:
    roots: list[Path] = []
    explicit_roots = [
        *list(policy.get("artifact_roots") or []),
        *list(policy.get("authorized_artifact_roots") or []),
    ]
    for value in explicit_roots:
        if str(value or "").strip():
            roots.append(Path(str(value).strip()))
    bundle = dict(output_bundle or {})
    artifact_materialization = dict(bundle.get("artifact_materialization") or {})
    workspace_root = str(
        bundle.get("workspace_root")
        or artifact_materialization.get("workspace_root")
        or dict(policy.get("artifact_context") or {}).get("workspace_root")
        or ""
    ).strip()
    task_result = dict(bundle.get("task_result") or {})
    task_result_diagnostics = dict(task_result.get("diagnostics") or {})
    task_final_outputs = dict(task_result.get("final_outputs") or {})
    for payload in (
        artifact_materialization,
        dict(task_result_diagnostics.get("artifact_materialization") or {}),
        dict(task_final_outputs.get("artifact_materialization") or {}),
    ):
        artifact_root = str(payload.get("artifact_root") or "").strip()
        if artifact_root:
            roots.extend(_root_variants(artifact_root, workspace_root=workspace_root))
        visible_root = str(payload.get("visible_artifact_root") or "").strip()
        if visible_root:
            roots.extend(_root_variants(visible_root, workspace_root=workspace_root))
    if workspace_root:
        roots.append(Path(workspace_root))
    return _dedupe_paths(roots)


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
            return {"found": True, "value": candidate.get(source_key), "source": f"formal_memory_candidates[{index}]"}
        if str(candidate.get("output_key") or "").strip() == source_key:
            return {"found": True, "value": candidate, "source": f"formal_memory_candidates[{index}]"}
        if source_key in payload:
            return {"found": True, "value": payload.get(source_key), "source": f"formal_memory_candidates[{index}].payload"}
        nested = _lookup_path(payload, source_key)
        if nested.get("found"):
            return {"found": True, "value": nested.get("value"), "source": f"formal_memory_candidates[{index}].payload.{source_key}"}
    return {"found": False}


def _lookup_path(payload: dict[str, Any], path: str) -> dict[str, Any]:
    if "." not in path:
        return {"found": False}
    current: Any = payload
    for part in [item for item in path.split(".") if item]:
        if not isinstance(current, dict) or part not in current:
            return {"found": False}
        current = current.get(part)
    return {"found": True, "value": current}


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _strings(values: Any) -> list[str]:
    if isinstance(values, str):
        return [values.strip()] if values.strip() else []
    return [str(item).strip() for item in list(values or []) if str(item).strip()]


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        result.append(resolved)
    return result


def _root_variants(root: str, *, workspace_root: str) -> list[Path]:
    path = Path(str(root or "").strip())
    if not workspace_root or path.is_absolute():
        return [path]
    return [Path(workspace_root) / path, path]


def _merge_content_requirements(
    *,
    trusted: list[dict[str, Any]],
    candidate: list[dict[str, Any]],
) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for payload in trusted:
        for key, value in dict(payload or {}).items():
            if str(key).strip():
                merged[str(key)] = value
    for key in ("canonical_text_required", "summary_required"):
        if any(bool(dict(payload or {}).get(key)) for payload in [*trusted, *candidate]):
            merged[key] = True
    for key in ("artifact_refs_allowed", "artifact_ref_only_allowed"):
        trusted_values = [
            dict(payload or {}).get(key)
            for payload in trusted
            if key in dict(payload or {})
        ]
        if any(value is False for value in trusted_values):
            merged[key] = False
        elif any(value is True for value in trusted_values):
            merged[key] = True
        else:
            candidate_values = [
                dict(payload or {}).get(key)
                for payload in candidate
                if key in dict(payload or {})
            ]
            if any(value is False for value in candidate_values):
                merged[key] = False
    return merged
