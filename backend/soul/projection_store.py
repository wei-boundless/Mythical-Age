from __future__ import annotations

import json
import hashlib
import time
from pathlib import Path
from typing import Any


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


def save_projection_store(base_dir: Path, payload: dict[str, Any]) -> None:
    path = _store_path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def list_projection_cards(
    base_dir: Path,
    *,
    soul_profiles: list[dict[str, Any]] | None = None,
    active_soul_id: str = "",
    soul_style_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    store = load_projection_store(base_dir)
    return reconcile_projection_store(
        base_dir,
        store=store,
        soul_profiles=soul_profiles or [],
        active_soul_id=active_soul_id,
        soul_style_map=soul_style_map or {},
        persist=True,
    )


def upsert_projection_card(
    base_dir: Path,
    *,
    request: dict[str, Any],
    soul_name: str,
    selected: bool = False,
) -> dict[str, Any]:
    store = load_projection_store(base_dir)
    projection_id = str(request.get("projection_id") or "").strip() or _projection_id(request)
    name = str(request.get("projection_name") or "").strip()
    title = name or f"{soul_name} / {request.get('role_type')}"
    now = time.time()
    card = {
        "projection_id": projection_id,
        "title": title,
        "soul_id": request.get("soul_id"),
        "soul_name": soul_name,
        "role_type": request.get("role_type"),
        "task_mode": request.get("task_mode"),
        "agent_profile_id": request.get("agent_profile_id"),
        "task_contract_summary": request.get("task_contract_summary"),
        "skill_views": request.get("skill_views") or [],
        "tool_views": request.get("tool_views") or [],
        "memory_policy_summary": request.get("memory_policy_summary") or "",
        "output_contract_summary": request.get("output_contract_summary") or "",
        "style_content": str(request.get("style_content") or ""),
        "created_at": now,
        "updated_at": now,
    }
    existing = store["cards"]
    for index, item in enumerate(existing):
        if item.get("projection_id") == projection_id:
            card["created_at"] = item.get("created_at") or card["created_at"]
            card["is_primary"] = bool(item.get("is_primary", False))
            card["is_system_default"] = bool(item.get("is_system_default", False))
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
    soul_style_map: dict[str, str] | None = None,
    persist: bool = False,
) -> dict[str, Any]:
    current = store or load_projection_store(base_dir)
    cards = [_normalize_card(item) for item in current.get("cards", []) if isinstance(item, dict)]
    by_id = {str(card.get("projection_id") or ""): card for card in cards}
    changed = False
    style_map = {str(key).strip().lower(): str(value) for key, value in (soul_style_map or {}).items() if str(key).strip()}

    for card in by_id.values():
        soul_id = str(card.get("soul_id") or "").strip().lower()
        if card.get("style_content") is None and soul_id in style_map:
            card["style_content"] = style_map[soul_id]
            changed = True

    for profile in soul_profiles or []:
        soul_id = str(profile.get("soul_id") or "").strip().lower()
        if not soul_id:
            continue
        default_id = _default_projection_id(soul_id)
        existing = by_id.get(default_id)
        default_card = _default_projection_card(
            profile,
            existing=existing,
            style_content=style_map.get(soul_id, ""),
        )
        if existing != default_card:
            by_id[default_id] = default_card
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
        "role_type": request.get("role_type") or "",
        "task_mode": request.get("task_mode") or "",
        "agent_profile_id": request.get("agent_profile_id") or "",
        "task_contract_summary": request.get("task_contract_summary") or "",
        "memory_policy_summary": request.get("memory_policy_summary") or "",
        "output_contract_summary": request.get("output_contract_summary") or "",
        "style_content": request.get("style_content") or "",
    }
    encoded = json.dumps(raw, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(encoded.encode("utf-8")).hexdigest()[:16]


def _default_projection_id(soul_id: str) -> str:
    soul = str(soul_id or "").strip().lower()
    return f"{soul}__primary" if soul else ""


def _default_projection_card(
    profile: dict[str, Any],
    *,
    existing: dict[str, Any] | None = None,
    style_content: str = "",
) -> dict[str, Any]:
    soul_id = str(profile.get("soul_id") or "").strip().lower()
    soul_name = str(profile.get("display_name") or profile.get("name") or soul_id)
    preferred_role_types = profile.get("preferred_role_types") if isinstance(profile.get("preferred_role_types"), (list, tuple)) else []
    preferred_task_modes = profile.get("preferred_task_modes") if isinstance(profile.get("preferred_task_modes"), (list, tuple)) else []
    role_type = str(preferred_role_types[0] if preferred_role_types else "dialogue")
    task_mode = str(preferred_task_modes[0] if preferred_task_modes else "general_qa")
    now = time.time()
    created_at = existing.get("created_at") if isinstance(existing, dict) and existing.get("created_at") else now
    current_style = existing.get("style_content") if isinstance(existing, dict) and "style_content" in existing else None
    return {
        "projection_id": _default_projection_id(soul_id),
        "title": f"{soul_name} / 原始投影",
        "soul_id": soul_id,
        "soul_name": soul_name,
        "role_type": role_type,
        "task_mode": task_mode,
        "agent_profile_id": "general_agent",
        "task_contract_summary": "",
        "skill_views": [],
        "tool_views": [],
        "memory_policy_summary": "原始投影沿用系统默认记忆策略。",
        "output_contract_summary": "原始投影沿用系统默认输出边界。",
        "style_content": current_style if current_style is not None else style_content,
        "created_at": created_at,
        "updated_at": created_at,
        "is_primary": True,
        "is_system_default": True,
    }


def _normalize_card(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "projection_id": str(item.get("projection_id") or ""),
        "title": str(item.get("title") or item.get("projection_id") or "未命名投影"),
        "soul_id": str(item.get("soul_id") or ""),
        "soul_name": str(item.get("soul_name") or item.get("soul_id") or ""),
        "role_type": str(item.get("role_type") or "dialogue"),
        "task_mode": str(item.get("task_mode") or "general_qa"),
        "agent_profile_id": str(item.get("agent_profile_id") or "general_agent"),
        "task_contract_summary": str(item.get("task_contract_summary") or ""),
        "skill_views": item.get("skill_views") if isinstance(item.get("skill_views"), list) else [],
        "tool_views": item.get("tool_views") if isinstance(item.get("tool_views"), list) else [],
        "memory_policy_summary": str(item.get("memory_policy_summary") or ""),
        "output_contract_summary": str(item.get("output_contract_summary") or ""),
        "style_content": item.get("style_content") if "style_content" in item else None,
        "created_at": item.get("created_at") or time.time(),
        "updated_at": item.get("updated_at") or time.time(),
        "is_primary": bool(item.get("is_primary", False)),
        "is_system_default": bool(item.get("is_system_default", False)),
    }
