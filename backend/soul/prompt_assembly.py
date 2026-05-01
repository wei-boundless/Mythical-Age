from __future__ import annotations

import hashlib

from soul.contracts import PromptSectionManifest, SoulPromptManifest, SoulRuntimeView


def build_prompt_manifest(task_id: str, projection_id: str, runtime_view: SoulRuntimeView) -> SoulPromptManifest:
    joined = "\n\n".join(section.content for section in runtime_view.sections)
    prompt_hash = hashlib.sha256(joined.encode("utf-8")).hexdigest()
    sections = tuple(
        PromptSectionManifest(
            section_id=section.section_id,
            source_type=section.source_type,
            source_id=section.source_id,
            owner_layer=section.owner_layer,
            cache_scope=section.cache_scope,
            visible_to_model=section.visible_to_model,
            chars=len(section.content),
            source_refs=section.source_refs,
            candidate_refs=section.candidate_refs,
        )
        for section in runtime_view.sections
    )
    return SoulPromptManifest(
        manifest_id=f"manifest-{projection_id}",
        task_id=task_id,
        soul_id=runtime_view.soul_id,
        projection_id=projection_id,
        sections=sections,
        prompt_hash=prompt_hash,
    )

