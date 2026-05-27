from __future__ import annotations

import re
from typing import Any

from request_intent.frame_access import target_domain_hints, turn_signals

from .models import ContinuationCandidate
from .profile_registry import ContinuationDomainProfile, default_continuation_profiles, profile_by_domain


def collect_continuation_candidates(
    *,
    message: str,
    memory_runtime_view: dict[str, Any] | None,
    request_intent: Any,
) -> tuple[ContinuationCandidate, ...]:
    if not _needs_continuation(message=message, request_intent=request_intent):
        return ()
    memory_view = dict(memory_runtime_view or {})
    candidates: list[ContinuationCandidate] = []
    candidates.extend(_state_slot_candidates(memory_view=memory_view))
    candidates.extend(_restore_candidates(memory_view=memory_view))
    candidates.extend(_bundle_candidates(memory_view=memory_view))
    candidates.extend(_task_summary_candidates(memory_view=memory_view))
    candidates.extend(_conversation_candidates(memory_view=memory_view))
    scored = [
        _score_candidate(candidate, message=message, request_intent=request_intent)
        for candidate in candidates
    ]
    return tuple(_dedupe_candidates(scored))


def _state_slot_candidates(*, memory_view: dict[str, Any]) -> list[ContinuationCandidate]:
    state_snapshot = dict(memory_view.get("state_snapshot") or {})
    context_slots = dict(state_snapshot.get("context_slots") or {})
    active_handles = dict(state_snapshot.get("active_handles") or {})
    active_constraints = dict(context_slots.get("active_constraints") or state_snapshot.get("active_constraints") or {})
    profiles = profile_by_domain()
    candidates: list[ContinuationCandidate] = []
    for profile in default_continuation_profiles():
        for slot in profile.state_slots:
            path = str(context_slots.get(slot) or "").strip()
            if not path:
                continue
            is_active = slot.startswith("active_")
            recall_payload = {
                "path": path,
                _binding_key(profile): path,
                "slot_name": slot,
                "source_kind": profile.source_kind,
                **(
                    {
                        "active_object_handle_id": str(active_handles.get("active_object_handle_id") or context_slots.get("active_object_handle_id") or ""),
                        "active_result_handle_id": str(active_handles.get("active_result_handle_id") or context_slots.get("active_result_handle_id") or ""),
                        "active_subset_handle_id": str(active_handles.get("active_subset_handle_id") or context_slots.get("active_subset_handle_id") or ""),
                    }
                    if is_active
                    else {}
                ),
                **(
                    {
                        "active_constraints": active_constraints,
                    }
                    if is_active and _constraints_match_profile(active_constraints, profile)
                    else {}
                ),
            }
            candidates.append(
                ContinuationCandidate(
                    candidate_id=f"continuation:state:{slot}:{_slug(path)}",
                    target_kind="source_object",
                    source_kind=profile.source_kind,
                    file_kind=profile.file_kind,
                    identity=_identity(path),
                    source="state_snapshot",
                    score=70.0 if is_active else 54.0,
                    recall_payload=_compact_dict(recall_payload),
                    metadata={"slot_name": slot, "profile_id": profile.domain_id},
                )
            )
    return candidates


def _restore_candidates(*, memory_view: dict[str, Any]) -> list[ContinuationCandidate]:
    profiles = profile_by_domain()
    results: list[ContinuationCandidate] = []
    for raw in list(memory_view.get("restore_candidates") or []):
        if not isinstance(raw, dict):
            continue
        restore_kind = str(raw.get("restore_kind") or "").strip()
        value = raw.get("value")
        metadata = dict(raw.get("metadata") or {})
        slot_name = str(metadata.get("slot_name") or "").strip()
        profile = _profile_for_slot(slot_name, profiles)
        if restore_kind != "context_slot" or profile is None:
            continue
        path = str(value or "").strip()
        if not path:
            continue
        results.append(
            ContinuationCandidate(
                candidate_id=f"continuation:restore:{slot_name}:{_slug(path)}",
                target_kind="source_object",
                source_kind=profile.source_kind,
                file_kind=profile.file_kind,
                identity=_identity(path),
                source="restore_candidate",
                score=float(raw.get("confidence") or 0.0) * 70,
                recall_payload={
                    "path": path,
                    _binding_key(profile): path,
                    "slot_name": slot_name,
                    "source_kind": profile.source_kind,
                },
                metadata={"restore_candidate_id": str(raw.get("candidate_id") or ""), "profile_id": profile.domain_id},
            )
        )
    return results


def _bundle_candidates(*, memory_view: dict[str, Any]) -> list[ContinuationCandidate]:
    state_snapshot = dict(memory_view.get("state_snapshot") or {})
    raw_refs = [
        dict(item)
        for item in list(state_snapshot.get("bundle_result_refs") or [])
        if isinstance(item, dict)
    ]
    for raw in list(memory_view.get("restore_candidates") or []):
        if not isinstance(raw, dict) or str(raw.get("restore_kind") or "") != "bundle_ref":
            continue
        value = raw.get("value")
        if isinstance(value, dict):
            raw_refs.append(dict(value))
    results: list[ContinuationCandidate] = []
    for item in raw_refs:
        ordinal = _safe_int(item.get("ordinal"))
        task_id = str(item.get("task_id") or "").strip()
        if ordinal <= 0 or not task_id:
            continue
        task_kind = str(item.get("task_kind") or item.get("capability_kind") or "").strip()
        profile = _profile_for_task_kind(task_kind) or profile_by_domain().get("task_bundle")
        source_kind = str(getattr(profile, "source_kind", "") or "bundle_result")
        results.append(
            ContinuationCandidate(
                candidate_id=f"continuation:bundle:{ordinal}:{_slug(task_id)}",
                target_kind="task_result",
                source_kind=source_kind,
                file_kind=str(getattr(profile, "file_kind", "") or ""),
                identity=task_id,
                source="state_snapshot.bundle_result_refs",
                score=82.0,
                recall_payload={"result_handle_id": task_id, "ordinal": ordinal, "source_kind": source_kind},
                metadata={**item, "profile_id": str(getattr(profile, "domain_id", "") or "task_bundle")},
            )
        )
    return results


def _task_summary_candidates(*, memory_view: dict[str, Any]) -> list[ContinuationCandidate]:
    raw_summaries: list[dict[str, Any]] = []
    state_snapshot = dict(memory_view.get("state_snapshot") or {})
    for key in ("task_summary_refs", "recent_task_summary_refs"):
        raw_summaries.extend(
            dict(item)
            for item in list(state_snapshot.get(key) or [])
            if isinstance(item, dict)
        )
    for key in ("key_results", "current_result_refs", "historical_result_refs"):
        for value in list(state_snapshot.get(key) or []):
            text = str(value or "").strip()
            if text:
                raw_summaries.append({"summary": text, "key_points": []})
    for candidate in list(memory_view.get("restore_candidates") or []):
        if not isinstance(candidate, dict):
            continue
        value = candidate.get("value")
        if str(candidate.get("restore_kind") or "") in {"task_ref", "result_handle"} and isinstance(value, dict):
            raw_summaries.append(dict(value))

    results: list[ContinuationCandidate] = []
    for item in raw_summaries:
        task_kind = str(item.get("task_kind") or item.get("capability_kind") or "").strip()
        profile = _profile_for_task_kind(task_kind)
        if profile is None:
            profile = _profile_from_key_points(list(item.get("key_points") or []))
        if profile is None:
            continue
        path = _path_from_summary(item, profile)
        if not path:
            continue
        result_handle_id = str(item.get("task_id") or item.get("result_handle_id") or "").strip()
        active_result_handle_id = str(item.get("active_result_handle_id") or result_handle_id).strip()
        active_object_handle_id = str(item.get("active_object_handle_id") or "").strip()
        active_subset_handle_id = str(item.get("active_subset_handle_id") or item.get("subset_handle_id") or "").strip()
        recall_payload = {
            "path": path,
            _binding_key(profile): path,
            "source_kind": profile.source_kind,
            "active_result_handle_id": active_result_handle_id,
            "active_object_handle_id": active_object_handle_id,
            "active_subset_handle_id": active_subset_handle_id,
            "active_binding_owner_task_id": result_handle_id,
        }
        subset = _subset_constraints_from_summary(item)
        if subset:
            recall_payload["active_constraints"] = {
                "source_kind": profile.source_kind,
                _binding_key(profile): path,
                **subset,
            }
        results.append(
            ContinuationCandidate(
                candidate_id=f"continuation:task-summary:{profile.source_kind}:{_slug(result_handle_id or path)}",
                target_kind="result_subset" if subset else "source_object",
                source_kind=profile.source_kind,
                file_kind=profile.file_kind,
                identity=_identity(path),
                source="state_snapshot.task_summary_refs",
                score=76.0 if subset else 64.0,
                recall_payload=_compact_dict(recall_payload),
                metadata={
                    "profile_id": profile.domain_id,
                    "task_id": result_handle_id,
                    "task_kind": task_kind,
                    "summary": str(item.get("summary") or item.get("answer") or "")[:240],
                },
            )
        )
    return results


def _conversation_candidates(*, memory_view: dict[str, Any]) -> list[ContinuationCandidate]:
    texts: list[tuple[str, str]] = []
    snapshot = dict(memory_view.get("conversation_snapshot") or {})
    for key in ("key_results", "hot_truth_window", "worklog", "recent_dialogue_refs"):
        for value in list(snapshot.get(key) or []):
            item = str(value or "").strip()
            if item:
                texts.append((f"conversation_snapshot.{key}", item))
    for candidate in list(memory_view.get("context_candidates") or []):
        if not isinstance(candidate, dict):
            continue
        preview = str(candidate.get("rendered_preview") or "").strip()
        if preview:
            texts.append((str(candidate.get("source") or "context_candidate"), preview))

    results: list[ContinuationCandidate] = []
    for source, text in texts:
        for profile in default_continuation_profiles():
            for path in _paths_for_profile(text, profile):
                results.append(_text_file_candidate(path=path, source=source, profile=profile))
    return results


def _text_file_candidate(*, path: str, source: str, profile: ContinuationDomainProfile) -> ContinuationCandidate:
    binding_key = _binding_key(profile)
    return ContinuationCandidate(
        candidate_id=f"continuation:conversation:{profile.source_kind}:{_slug(path)}",
        target_kind="source_object",
        source_kind=profile.source_kind,
        file_kind=profile.file_kind,
        identity=_identity(path),
        source=source,
        score=46.0,
        recall_payload={"path": path, binding_key: path, "source_kind": profile.source_kind},
        metadata={"profile_id": profile.domain_id},
    )


def _score_candidate(
    candidate: ContinuationCandidate,
    *,
    message: str,
    request_intent: Any,
) -> ContinuationCandidate:
    profile = profile_by_domain().get(str(candidate.metadata.get("profile_id") or candidate.source_kind))
    lowered = str(message or "").lower()
    score = float(candidate.score or 0.0)
    conflicts: list[str] = []
    if profile is not None:
        score += 8.0 * _marker_hits(lowered, profile.compatible_markers)
        if _marker_hits(lowered, profile.subset_markers):
            score += 12.0
        if _marker_hits(lowered, profile.conflict_markers):
            conflicts.append("domain_language_conflict")
            score -= 45.0
    target_domains = target_domain_hints(request_intent)
    matched_domain = next((item for item in target_domains if item in _profile_domain_ids()), "")
    if matched_domain and candidate.source_kind != matched_domain:
        conflicts.append("intent_domain_mismatch")
        score -= 80.0
    if profile is not None and _marker_hits(lowered, profile.subset_markers):
        score += 10.0
    compatible = score >= 45.0 and not conflicts
    return ContinuationCandidate(
        candidate_id=candidate.candidate_id,
        target_kind=_target_kind(candidate, message=message, profile=profile),
        source_kind=candidate.source_kind,
        file_kind=candidate.file_kind,
        identity=candidate.identity,
        source=candidate.source,
        score=score,
        compatible=compatible,
        conflict_reasons=tuple(_dedupe(conflicts)),
        recall_payload=dict(candidate.recall_payload),
        metadata={**dict(candidate.metadata), "scored_by": "continuation.candidate_collector"},
    )


def _target_kind(
    candidate: ContinuationCandidate,
    *,
    message: str,
    profile: ContinuationDomainProfile | None,
) -> str:
    if candidate.target_kind != "source_object":
        return candidate.target_kind
    lowered = str(message or "").lower()
    if profile is not None and _marker_hits(lowered, profile.subset_markers):
        payload = dict(candidate.recall_payload or {})
        if not str(payload.get("active_subset_handle_id") or payload.get("subset_handle_id") or "").strip():
            return "source_object"
        return "result_subset"
    return "source_object"


def _needs_continuation(*, message: str, request_intent: Any) -> bool:
    signals = turn_signals(request_intent)
    if signals.get("followup_markers"):
        return True
    lowered = str(message or "").lower()
    return any(
        marker in lowered
        for marker in (
            "继续",
            "接着",
            "刚才",
            "这个",
            "这份",
            "这些",
            "再",
            "只基于",
            "上面",
            "前五",
        )
    )


def _profile_for_slot(slot_name: str, profiles: dict[str, ContinuationDomainProfile]) -> ContinuationDomainProfile | None:
    for profile in profiles.values():
        if slot_name in profile.state_slots:
            return profile
    return None


def _binding_key(profile: ContinuationDomainProfile) -> str:
    return profile.binding_key or f"active_{profile.source_kind}"


def _constraints_match_profile(active_constraints: dict[str, Any], profile: ContinuationDomainProfile) -> bool:
    source_kind = str(active_constraints.get("source_kind") or "").strip()
    if source_kind and source_kind != profile.source_kind:
        return False
    key = _binding_key(profile)
    return bool(str(active_constraints.get(key) or "").strip()) or not source_kind


def _paths_for_profile(text: str, profile: ContinuationDomainProfile) -> list[str]:
    extensions = tuple(str(item or "").strip().lstrip(".").lower() for item in profile.path_extensions if str(item or "").strip())
    if not extensions:
        return []
    pattern = re.compile(r"([^\s,，;；:：\"'“”‘’]+?\.(?:" + "|".join(re.escape(item) for item in extensions) + r"))", re.I)
    return _dedupe([match.group(1).strip() for match in pattern.finditer(str(text or ""))])


def _profile_for_task_kind(task_kind: str) -> ContinuationDomainProfile | None:
    normalized = str(task_kind or "").strip()
    if not normalized:
        return None
    for profile in default_continuation_profiles():
        if normalized in set(profile.task_kinds) or normalized in set(profile.capability_kinds):
            return profile
    return None


def _profile_from_key_points(key_points: list[Any]) -> ContinuationDomainProfile | None:
    joined = "\n".join(str(item or "") for item in key_points)
    for profile in default_continuation_profiles():
        if _path_from_key_points(key_points, profile) or any(
            str(prefix or "").strip() and str(prefix or "").strip() in joined
            for prefix in tuple(profile.handle_prefixes or ())
        ):
            return profile
    return None


def _path_from_summary(item: dict[str, Any], profile: ContinuationDomainProfile) -> str:
    for key in ("path", "source_path", "file_path", _binding_key(profile)):
        value = str(item.get(key) or "").strip()
        if value:
            return value
    return _path_from_key_points(list(item.get("key_points") or []), profile)


def _path_from_key_points(key_points: list[Any], profile: ContinuationDomainProfile) -> str:
    prefixes = [f"{profile.file_kind}=", f"{profile.source_kind}=", f"{_binding_key(profile)}="]
    for point in key_points:
        text = str(point or "").strip()
        for prefix in prefixes:
            if prefix and text.startswith(prefix):
                return text[len(prefix):].strip()
    return ""


def _subset_constraints_from_summary(item: dict[str, Any]) -> dict[str, Any]:
    subset_handle_id = str(item.get("active_subset_handle_id") or item.get("subset_handle_id") or "").strip()
    if not subset_handle_id:
        return {}
    labels = [
        str(value or "").strip()
        for value in list(item.get("subset_labels") or [])
        if str(value or "").strip()
    ]
    filter_column = str(item.get("subset_filter_column") or "").strip()
    result: dict[str, Any] = {}
    if labels:
        result["subset_labels"] = labels
    if filter_column:
        result["subset_filter_column"] = filter_column
    return result


def _profile_domain_ids() -> set[str]:
    return {
        str(profile.source_kind or "").strip()
        for profile in default_continuation_profiles()
        if str(profile.source_kind or "").strip()
    }


def _marker_hits(text: str, markers: tuple[str, ...]) -> int:
    return sum(1 for marker in markers if marker and marker in text)


def _dedupe_candidates(candidates: list[ContinuationCandidate]) -> list[ContinuationCandidate]:
    result: list[ContinuationCandidate] = []
    seen: set[tuple[str, str, str]] = set()
    for item in sorted(candidates, key=lambda candidate: (-candidate.score, candidate.source_kind, candidate.identity)):
        key = (item.source_kind, item.file_kind, item.identity or item.candidate_id)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _compact_dict(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {})}


def _identity(value: str) -> str:
    return str(value or "").replace("\\", "/").strip().lower()


def _slug(value: str) -> str:
    compact = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", str(value or "").lower()).strip("-")
    return compact[:64] or "main"


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


