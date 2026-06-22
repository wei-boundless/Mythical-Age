from __future__ import annotations

import hashlib
from types import SimpleNamespace

from prompting import builder
from prompting.long_term_context import LongTermContextBundle
from prompting.manifest import prompt_section_content_hash
from prompting.prompt_cache import stable_text_hash


def test_prompt_manifest_records_final_truncated_section_text(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        builder,
        "get_settings",
        lambda: SimpleNamespace(component_char_limit=10, backend_dir=tmp_path),
    )
    bundle = LongTermContextBundle(
        static_sections=[("Long Policy", "# Long Policy\n" + ("A" * 40))],
        memory_block="",
    )

    prompt, manifest = builder.build_system_prompt_with_manifest(
        tmp_path,
        rag_mode=False,
        persistent_memory="D" * 40,
        session_memory="S" * 40,
        session_id="session-a",
        turn_id="turn-b",
        long_term_context_bundle=bundle,
    )

    digest = hashlib.sha256(prompt.encode("utf-8", errors="ignore")).hexdigest()[:20]
    assert manifest.prompt_id == f"session-a:turn-b:{digest}"

    sections = {section.id: section for section in manifest.sections}
    expected_static = "A" * 10 + "\n...[truncated]"
    expected_session = "S" * 10 + "\n...[truncated]"
    expected_turn = "D" * 10 + "\n...[truncated]"

    assert sections["static_context_1"].truncated is True
    assert sections["static_context_1"].original_chars == 40
    assert sections["static_context_1"].injected_chars == len(expected_static)
    assert sections["static_context_1"].content_hash == prompt_section_content_hash(expected_static)

    assert sections["session_context"].truncated is True
    assert sections["session_context"].original_chars == 40
    assert sections["session_context"].injected_chars == len(expected_session)
    assert sections["session_context"].content_hash == prompt_section_content_hash(expected_session)
    assert sections["session_context"].cache["content_hash"] == stable_text_hash(expected_session)

    assert sections["turn_relevant_memory"].truncated is True
    assert sections["turn_relevant_memory"].original_chars == 40
    assert sections["turn_relevant_memory"].injected_chars == len(expected_turn)
    assert sections["turn_relevant_memory"].content_hash == prompt_section_content_hash(expected_turn)
    assert sections["turn_relevant_memory"].cache["content_hash"] == stable_text_hash(expected_turn)

    assert expected_static in prompt
    assert expected_session in prompt
    assert expected_turn in prompt
