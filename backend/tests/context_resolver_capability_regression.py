from __future__ import annotations

from context_system.resolution.resolver import ContextResolver


def test_report_word_does_not_create_pdf_bundle_without_structured_material_signal() -> None:
    binding = ContextResolver().resolve(
        session_id="session:test",
        task_id="task:test",
        user_message="先输出审查报告，然后总结风险。",
        query_understanding={"confidence": 0.8},
    )

    assert binding.execution_mode == "single"
    assert binding.bundle_items == ()
    assert "explicit_pdf_path" not in binding.explicit_inputs


def test_structured_capability_signals_can_still_create_bundle_items() -> None:
    binding = ContextResolver().resolve(
        session_id="session:test",
        task_id="task:test",
        user_message="先处理文档，然后查最新信息。",
        query_understanding={
            "capability_needs": ["pdf_material", "latest_information"],
            "confidence": 0.9,
        },
    )

    assert binding.execution_mode == "bundle"
    assert [item.capability_kind for item in binding.bundle_items] == ["pdf", "realtime_network"]
