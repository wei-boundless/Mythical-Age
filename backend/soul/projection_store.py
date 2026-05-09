from __future__ import annotations

import json
import hashlib
import time
from pathlib import Path
from typing import Any

from .registry import read_text


def _store_path(base_dir: Path) -> Path:
    return base_dir / "soul" / "projections" / "catalog.json"


def _default_store() -> dict[str, Any]:
    return {"selected_projection_id": "", "cards": []}


def load_projection_store(base_dir: Path) -> dict[str, Any]:
    path = _store_path(base_dir)
    if not path.exists():
        return _default_store()
    try:
        payload = json.loads(path.read_text(encoding="utf-8") or "{}")
    except json.JSONDecodeError:
        return _default_store()
    cards = payload.get("cards")
    if not isinstance(cards, list):
        cards = []
    cards = [_normalize_card(item) for item in cards if isinstance(item, dict)]
    return {
        "selected_projection_id": str(payload.get("selected_projection_id") or ""),
        "cards": cards,
    }


def get_projection_card(base_dir: Path, projection_id: str) -> dict[str, Any] | None:
    target = str(projection_id or "").strip()
    if not target:
        return None
    store = load_projection_store(base_dir)
    return next((item for item in store["cards"] if str(item.get("projection_id") or "") == target), None)


def save_projection_store(base_dir: Path, payload: dict[str, Any]) -> None:
    path = _store_path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def list_projection_cards(
    base_dir: Path,
    *,
    soul_profiles: list[dict[str, Any]] | None = None,
    active_soul_id: str = "",
) -> dict[str, Any]:
    store = load_projection_store(base_dir)
    return reconcile_projection_store(
        base_dir,
        store=store,
        soul_profiles=soul_profiles or [],
        active_soul_id=active_soul_id,
        persist=True,
    )


def upsert_projection_card(
    base_dir: Path,
    *,
    request: dict[str, Any],
    soul_name: str,
    soul_profile: dict[str, Any] | None = None,
    selected: bool = False,
) -> dict[str, Any]:
    store = load_projection_store(base_dir)
    resolved_request = _apply_projection_defaults(
        base_dir,
        request=request,
        soul_name=soul_name,
        soul_profile=soul_profile,
    )
    projection_id = str(resolved_request.get("projection_id") or "").strip() or _projection_id(resolved_request)
    name = str(resolved_request.get("projection_name") or "").strip()
    title = name or f"{soul_name} / {resolved_request.get('role_type')}"
    now = time.time()
    runtime_preview = _runtime_preview(resolved_request)
    card = {
        "projection_id": projection_id,
        "title": title,
        "soul_id": resolved_request.get("soul_id"),
        "soul_name": soul_name,
        "projection_nodes": resolved_request.get("projection_nodes") if isinstance(resolved_request.get("projection_nodes"), list) else [],
        "identity_anchor": str(resolved_request.get("identity_anchor") or ""),
        "role_type": resolved_request.get("role_type"),
        "task_mode": resolved_request.get("task_mode"),
        "agent_profile_id": resolved_request.get("agent_profile_id"),
        "posture_tags": _list_of_str(resolved_request.get("posture_tags")),
        "expression_density": str(resolved_request.get("expression_density") or "normal"),
        "attention_focus": _list_of_str(resolved_request.get("attention_focus")),
        "risk_notes": _list_of_str(resolved_request.get("risk_notes")),
        "projection_prompt": str(resolved_request.get("projection_prompt") or ""),
        "usage_summary": resolved_request.get("usage_summary") or "",
        "skill_views": resolved_request.get("skill_views") or [],
        "tool_views": resolved_request.get("tool_views") or [],
        "memory_policy_summary": resolved_request.get("memory_policy_summary") or "",
        "output_contract_summary": resolved_request.get("output_contract_summary") or "",
        "runtime_preview": runtime_preview,
        "runtime_only_payload": True,
        "static_projection_card": True,
        "created_at": now,
        "updated_at": now,
        "is_primary": projection_id == _default_projection_id(str(resolved_request.get("soul_id") or "")),
        "is_system_default": projection_id == _default_projection_id(str(resolved_request.get("soul_id") or "")),
    }
    existing = store["cards"]
    for index, item in enumerate(existing):
        if item.get("projection_id") == projection_id:
            card["created_at"] = item.get("created_at") or card["created_at"]
            card["is_primary"] = bool(item.get("is_primary", card["is_primary"]))
            card["is_system_default"] = bool(item.get("is_system_default", card["is_system_default"]))
            existing[index] = card
            break
    else:
        existing.insert(0, card)
    if selected:
        store["selected_projection_id"] = projection_id
    save_projection_store(base_dir, store)
    return store


def select_projection_card(base_dir: Path, projection_id: str) -> dict[str, Any]:
    store = load_projection_store(base_dir)
    if projection_id and not any(item.get("projection_id") == projection_id for item in store["cards"]):
        raise KeyError(projection_id)
    store["selected_projection_id"] = projection_id
    save_projection_store(base_dir, store)
    return store


def delete_projection_card(base_dir: Path, projection_id: str) -> dict[str, Any]:
    store = load_projection_store(base_dir)
    before = len(store["cards"])
    store["cards"] = [item for item in store["cards"] if item.get("projection_id") != projection_id]
    if len(store["cards"]) == before:
        raise KeyError(projection_id)
    if store["selected_projection_id"] == projection_id:
        store["selected_projection_id"] = str(store["cards"][0].get("projection_id") or "") if store["cards"] else ""
    save_projection_store(base_dir, store)
    return store


def reconcile_projection_store(
    base_dir: Path,
    *,
    store: dict[str, Any] | None = None,
    soul_profiles: list[dict[str, Any]] | None = None,
    active_soul_id: str = "",
    persist: bool = False,
) -> dict[str, Any]:
    current = store or load_projection_store(base_dir)
    cards = [_normalize_card(item) for item in current.get("cards", []) if isinstance(item, dict)]
    by_id = {str(card.get("projection_id") or ""): card for card in cards}
    changed = False

    for profile in soul_profiles or []:
        soul_id = str(profile.get("soul_id") or "").strip().lower()
        if not soul_id:
            continue
        default_id = _default_projection_id(soul_id)
        existing = by_id.get(default_id)
        default_card = _default_projection_card(
            base_dir,
            profile,
            existing=existing,
        )
        next_card = _merge_primary_projection_card(existing, default_card)
        if existing != next_card:
            by_id[default_id] = next_card
            changed = True

    normalized_cards = list(by_id.values())
    selected_projection_id = str(current.get("selected_projection_id") or "")
    if selected_projection_id and selected_projection_id not in by_id:
        selected_projection_id = ""
        changed = True
    if not selected_projection_id:
        selected_projection_id = _default_projection_id(active_soul_id) if active_soul_id and _default_projection_id(active_soul_id) in by_id else ""
        if not selected_projection_id and normalized_cards:
            selected_projection_id = str(normalized_cards[0].get("projection_id") or "")
        if selected_projection_id:
            changed = True

    payload = {
        "selected_projection_id": selected_projection_id,
        "cards": normalized_cards,
    }
    if persist and changed:
        save_projection_store(base_dir, payload)
    return payload


def _projection_id(request: dict[str, Any]) -> str:
    raw = {
        "projection_name": request.get("projection_name") or "",
        "soul_id": request.get("soul_id") or "",
        "identity_anchor": str(request.get("identity_anchor") or ""),
        "role_type": request.get("role_type") or "",
        "task_mode": request.get("task_mode") or "",
        "agent_profile_id": request.get("agent_profile_id") or "",
        "posture_tags": _list_of_str(request.get("posture_tags")),
        "expression_density": request.get("expression_density") or "",
        "attention_focus": _list_of_str(request.get("attention_focus")),
        "risk_notes": _list_of_str(request.get("risk_notes")),
        "projection_prompt": str(request.get("projection_prompt") or ""),
        "usage_summary": request.get("usage_summary") or "",
        "memory_policy_summary": request.get("memory_policy_summary") or "",
        "output_contract_summary": request.get("output_contract_summary") or "",
    }
    encoded = json.dumps(raw, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(encoded.encode("utf-8")).hexdigest()[:16]


def _default_projection_id(soul_id: str) -> str:
    soul = str(soul_id or "").strip().lower()
    return f"{soul}__primary" if soul else ""


def _default_projection_card(
    base_dir: Path,
    profile: dict[str, Any],
    *,
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    soul_id = str(profile.get("soul_id") or "").strip().lower()
    soul_name = str(profile.get("display_name") or profile.get("name") or soul_id)
    preferred_role_types = profile.get("preferred_role_types") if isinstance(profile.get("preferred_role_types"), (list, tuple)) else []
    preferred_task_modes = profile.get("preferred_task_modes") if isinstance(profile.get("preferred_task_modes"), (list, tuple)) else []
    role_type = str(preferred_role_types[0] if preferred_role_types else "dialogue")
    task_mode = str(preferred_task_modes[0] if preferred_task_modes else "general_qa")
    defaults = _projection_defaults_from_soul(base_dir, profile)
    now = time.time()
    created_at = existing.get("created_at") if isinstance(existing, dict) and existing.get("created_at") else now
    updated_at = existing.get("updated_at") if isinstance(existing, dict) and existing.get("updated_at") else created_at
    return {
        "projection_id": _default_projection_id(soul_id),
        "title": f"{soul_name} / 原始投影",
        "soul_id": soul_id,
        "soul_name": soul_name,
        "projection_nodes": defaults["projection_nodes"],
        "identity_anchor": defaults["identity_anchor"],
        "role_type": role_type,
        "task_mode": task_mode,
        "agent_profile_id": "general_agent",
        "posture_tags": [],
        "expression_density": "normal",
        "attention_focus": [],
        "risk_notes": [],
        "projection_prompt": defaults["projection_prompt"],
        "usage_summary": "默认以当前灵魂设定为初始化模板，可在此基础上派生独立投影。",
        "skill_views": [],
        "tool_views": [],
        "memory_policy_summary": "原始投影沿用系统默认记忆策略。",
        "output_contract_summary": "原始投影沿用系统默认输出边界。",
        "runtime_preview": {
            "usage_summary": "",
            "skill_views": [],
            "tool_views": [],
            "memory_policy_summary": "原始投影沿用系统默认记忆策略。",
            "output_contract_summary": "原始投影沿用系统默认输出边界。",
        },
        "runtime_only_payload": True,
        "static_projection_card": True,
        "created_at": created_at,
        "updated_at": updated_at,
        "is_primary": True,
        "is_system_default": True,
    }


def _merge_primary_projection_card(existing: dict[str, Any] | None, default_card: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(existing, dict):
        return default_card
    if not bool(existing.get("is_primary")):
        return default_card
    merged = dict(default_card)
    for field in (
        "title",
        "projection_nodes",
        "identity_anchor",
        "projection_prompt",
        "role_type",
        "task_mode",
        "agent_profile_id",
        "posture_tags",
        "expression_density",
        "attention_focus",
        "risk_notes",
        "usage_summary",
        "skill_views",
        "tool_views",
        "memory_policy_summary",
        "output_contract_summary",
        "runtime_preview",
        "runtime_only_payload",
        "static_projection_card",
    ):
        if field in existing:
            merged[field] = existing[field]
    merged["created_at"] = existing.get("created_at") or default_card.get("created_at")
    merged["updated_at"] = existing.get("updated_at") or default_card.get("updated_at")
    merged["is_primary"] = True
    merged["is_system_default"] = True
    return merged


def _normalize_card(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "projection_id": str(item.get("projection_id") or ""),
        "title": str(item.get("title") or item.get("projection_id") or "未命名投影"),
        "soul_id": str(item.get("soul_id") or ""),
        "soul_name": str(item.get("soul_name") or item.get("soul_id") or ""),
        "projection_nodes": item.get("projection_nodes") if isinstance(item.get("projection_nodes"), list) else [],
        "identity_anchor": str(item.get("identity_anchor") or ""),
        "role_type": str(item.get("role_type") or "dialogue"),
        "task_mode": str(item.get("task_mode") or "general_qa"),
        "agent_profile_id": str(item.get("agent_profile_id") or "general_agent"),
        "posture_tags": _list_of_str(item.get("posture_tags")),
        "expression_density": str(item.get("expression_density") or "normal"),
        "attention_focus": _list_of_str(item.get("attention_focus")),
        "risk_notes": _list_of_str(item.get("risk_notes")),
        "projection_prompt": str(item.get("projection_prompt") or ""),
        "usage_summary": str(item.get("usage_summary") or ""),
        "skill_views": item.get("skill_views") if isinstance(item.get("skill_views"), list) else [],
        "tool_views": item.get("tool_views") if isinstance(item.get("tool_views"), list) else [],
        "memory_policy_summary": str(item.get("memory_policy_summary") or ""),
        "output_contract_summary": str(item.get("output_contract_summary") or ""),
        "runtime_preview": _normalize_runtime_preview(item),
        "runtime_only_payload": bool(item.get("runtime_only_payload", True)),
        "static_projection_card": bool(item.get("static_projection_card", True)),
        "created_at": item.get("created_at") or time.time(),
        "updated_at": item.get("updated_at") or time.time(),
        "is_primary": bool(item.get("is_primary", False)),
        "is_system_default": bool(item.get("is_system_default", False)),
    }


def _list_of_str(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item) for item in value if str(item or "").strip()]


def _runtime_preview(request: dict[str, Any]) -> dict[str, Any]:
    return {
        "identity_anchor": str(request.get("identity_anchor") or ""),
        "projection_prompt": str(request.get("projection_prompt") or ""),
        "usage_summary": request.get("usage_summary") or "",
        "skill_views": request.get("skill_views") if isinstance(request.get("skill_views"), list) else [],
        "tool_views": request.get("tool_views") if isinstance(request.get("tool_views"), list) else [],
        "memory_policy_summary": request.get("memory_policy_summary") or "",
        "output_contract_summary": request.get("output_contract_summary") or "",
    }


def _normalize_runtime_preview(item: dict[str, Any]) -> dict[str, Any]:
    preview = item.get("runtime_preview")
    if isinstance(preview, dict):
        return _runtime_preview(preview)
    return _runtime_preview(item)


def _apply_projection_defaults(
    base_dir: Path,
    *,
    request: dict[str, Any],
    soul_name: str,
    soul_profile: dict[str, Any] | None,
) -> dict[str, Any]:
    resolved = dict(request)
    profile = soul_profile or {
        "soul_id": request.get("soul_id"),
        "display_name": soul_name,
        "name": soul_name,
    }
    defaults = _projection_defaults_from_soul(base_dir, profile)
    has_explicit_nodes = isinstance(resolved.get("projection_nodes"), list) and bool(resolved.get("projection_nodes") or [])
    if not has_explicit_nodes:
        resolved["projection_nodes"] = defaults["projection_nodes"]
    if not str(resolved.get("identity_anchor") or "").strip():
        resolved["identity_anchor"] = defaults["identity_anchor"]
    if not has_explicit_nodes and not str(resolved.get("projection_prompt") or "").strip():
        resolved["projection_prompt"] = defaults["projection_prompt"]
    return resolved


def _projection_defaults_from_soul(base_dir: Path, profile: dict[str, Any]) -> dict[str, Any]:
    seed_path = str(profile.get("seed_path") or "").strip()
    if not seed_path:
        return {"identity_anchor": "", "projection_prompt": "", "projection_nodes": []}
    content = read_text(base_dir / seed_path)
    sections = _markdown_sections(content)
    identity_anchor = _section_text(sections, "身份锚点", "Identity Anchor")
    prompt_parts: list[str] = []
    projection_nodes: list[dict[str, str]] = []
    for index, (title, raw_section) in enumerate(sections.items()):
        section = _section_text({title: raw_section}, title)
        if not section:
            continue
        node_type = "identity_anchor" if title in {"身份锚点", "Identity Anchor"} else "template_section"
        projection_nodes.append(
            {
                "id": f"projection-node-{index}",
                "type": node_type,
                "title": title,
                "content": section,
            }
        )
        if node_type != "identity_anchor":
            prompt_parts.append(f"## {title}\n\n{section}")
    return {
        "identity_anchor": identity_anchor,
        "projection_prompt": "\n\n".join(prompt_parts).strip(),
        "projection_nodes": projection_nodes,
    }


def _markdown_sections(content: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current_title = ""
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            current_title = stripped[3:].strip()
            sections.setdefault(current_title, [])
            continue
        if current_title:
            sections[current_title].append(line)
    return {title: "\n".join(lines).strip() for title, lines in sections.items()}


def _section_text(sections: dict[str, str], *titles: str) -> str:
    for title in titles:
        raw = str(sections.get(title) or "").strip()
        if not raw:
            continue
        normalized_lines: list[str] = []
        for line in raw.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            normalized_lines.append(stripped.lstrip("-").strip())
        return "\n".join(normalized_lines).strip()
    return ""
