from __future__ import annotations

import hashlib
from typing import Mapping

from soul.contracts import AgentPromptBundle, SoulPromptManifest, SoulRuntimeView


def build_agent_prompt_bundle(
    *,
    agent_id: str,
    agent_profile_id: str,
    task_id: str,
    task_run_id: str = "",
    projection_id: str,
    runtime_view: SoulRuntimeView,
    prompt_manifest: SoulPromptManifest,
    refs: Mapping[str, str] | None = None,
) -> AgentPromptBundle:
    bundle_id = _bundle_id(
        agent_id=agent_id,
        task_id=task_id,
        task_run_id=task_run_id,
        projection_id=projection_id,
        prompt_hash=prompt_manifest.prompt_hash,
    )
    cache_plan = {section.section_id: section.cache_scope for section in runtime_view.sections}
    return AgentPromptBundle(
        bundle_id=bundle_id,
        agent_id=agent_id,
        agent_profile_id=agent_profile_id,
        task_id=task_id,
        task_run_id=task_run_id,
        soul_id=runtime_view.soul_id,
        projection_id=projection_id,
        sections=runtime_view.sections,
        prompt_manifest=prompt_manifest,
        cache_plan=cache_plan,
        refs=dict(refs or {}),
    )


def _bundle_id(
    *,
    agent_id: str,
    task_id: str,
    task_run_id: str,
    projection_id: str,
    prompt_hash: str,
) -> str:
    raw = f"{agent_id}:{task_id}:{task_run_id}:{projection_id}:{prompt_hash}"
    return f"agent-prompt-{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:16]}"
