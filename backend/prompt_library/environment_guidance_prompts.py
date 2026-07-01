from __future__ import annotations

from pathlib import Path

from .models import PromptResource


ENVIRONMENT_GUIDANCE_PROMPT_SLOTS: tuple[str, ...] = (
    "context_intake",
    "request_judgment",
    "work_relation",
    "environment_capability_alignment",
    "plan_gate",
    "action_boundary",
    "active_work_control",
    "task_run_handoff",
    "user_steer_contract_revision",
    "tool_dispatch",
    "tool_observation_recovery",
    "subagent_delegation",
    "subagent_result_integration",
    "verification_gate",
    "memory_read_context",
    "memory_write_handoff",
    "compaction_handoff",
    "finalization",
)


_ENVIRONMENT_PROMPT_PREFIXES: dict[str, str] = {
    "env.coding.vibe_workspace": "coding",
    "env.office.file_search": "office",
    "env.general.workspace": "general",
}


ENVIRONMENT_GUIDANCE_PROMPT_DEFAULTS_BY_ENVIRONMENT: dict[str, dict[str, str]] = {
    environment_id: {
        slot: f"environment.{prefix}.guidance.{slot}"
        for slot in ENVIRONMENT_GUIDANCE_PROMPT_SLOTS
    }
    for environment_id, prefix in _ENVIRONMENT_PROMPT_PREFIXES.items()
}


ENVIRONMENT_GUIDANCE_PROMPT_IDS_BY_ENVIRONMENT: dict[str, tuple[str, ...]] = {
    environment_id: tuple(slot_refs[slot] for slot in ENVIRONMENT_GUIDANCE_PROMPT_SLOTS)
    for environment_id, slot_refs in ENVIRONMENT_GUIDANCE_PROMPT_DEFAULTS_BY_ENVIRONMENT.items()
}


ALL_ENVIRONMENT_GUIDANCE_PROMPT_IDS: tuple[str, ...] = tuple(
    prompt_ref
    for environment_id in (
        "env.coding.vibe_workspace",
        "env.office.file_search",
        "env.general.workspace",
    )
    for prompt_ref in ENVIRONMENT_GUIDANCE_PROMPT_IDS_BY_ENVIRONMENT[environment_id]
)


_ASSET_ROOT = Path(__file__).with_name("prompt_assets") / "environment_guidance"


def list_builtin_environment_guidance_prompt_resources() -> tuple[PromptResource, ...]:
    _assert_environment_guidance_assets_complete()
    resources: list[PromptResource] = []
    for environment_id, slot_refs in ENVIRONMENT_GUIDANCE_PROMPT_DEFAULTS_BY_ENVIRONMENT.items():
        prefix = _ENVIRONMENT_PROMPT_PREFIXES[environment_id]
        for slot in ENVIRONMENT_GUIDANCE_PROMPT_SLOTS:
            prompt_id = slot_refs[slot]
            title, content, asset_path = _load_environment_guidance_asset(prefix=prefix, slot=slot)
            resources.append(
                PromptResource(
                    prompt_id=prompt_id,
                    resource_id=prompt_id,
                    category="environment",
                    subtype=f"guidance_{slot}",
                    resource_type="environment_prompt",
                    title=title,
                    content=content,
                    owner_layer="environment",
                    owner_kind="environment",
                    owner_ref=environment_id,
                    allowed_invocation_kinds=("environment",),
                    allowed_environment_refs=(environment_id,),
                    cache_scope="static_environment",
                    model_visible=True,
                    source_ref=_asset_source_ref(asset_path),
                    version="2026-06-10",
                    enabled=True,
                    status="active",
                    metadata={
                        "managed_by": "prompt_library.environment_guidance_prompts",
                        "source_type": "environment_guidance_prompt",
                        "source_asset": _asset_source_ref(asset_path),
                        "environment_id": environment_id,
                        "environment_guidance_slot": slot,
                        "environment_guidance_prompt": True,
                    },
                )
            )
    return tuple(resources)


def _assert_environment_guidance_assets_complete() -> None:
    missing: list[str] = []
    for prefix in _ENVIRONMENT_PROMPT_PREFIXES.values():
        for slot in ENVIRONMENT_GUIDANCE_PROMPT_SLOTS:
            path = _asset_path(prefix=prefix, slot=slot)
            if not path.exists():
                missing.append(_asset_source_ref(path))
    if missing:
        raise RuntimeError("Missing environment guidance prompt asset(s): " + ", ".join(missing))


def _load_environment_guidance_asset(*, prefix: str, slot: str) -> tuple[str, str, Path]:
    path = _asset_path(prefix=prefix, slot=slot)
    text = path.read_text(encoding="utf-8")
    title, content = _parse_front_matter_prompt(text)
    if not title:
        title = f"{prefix.title()} {slot} guidance"
    if not content:
        raise RuntimeError(f"Environment guidance prompt asset is empty: {_asset_source_ref(path)}")
    return title, content, path


def _parse_front_matter_prompt(text: str) -> tuple[str, str]:
    payload = str(text or "").strip()
    if not payload.startswith("---"):
        return "", payload
    parts = payload.split("---", 2)
    if len(parts) < 3:
        return "", payload
    header = parts[1]
    body = parts[2].strip()
    title = ""
    for line in header.splitlines():
        key, separator, value = line.partition(":")
        if separator and key.strip() == "title":
            title = value.strip().strip('"').strip("'")
            break
    return title, body


def _asset_path(*, prefix: str, slot: str) -> Path:
    return _ASSET_ROOT / str(prefix or "").strip() / f"{str(slot or '').strip()}.md"


def _asset_source_ref(path: Path) -> str:
    try:
        return path.relative_to(Path(__file__).parent).as_posix()
    except ValueError:
        return path.as_posix()
