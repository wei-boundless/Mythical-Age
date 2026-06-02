from __future__ import annotations

from runtime_objects.tool_result_storage import PERSISTED_OUTPUT_TAG, ToolResultStore


def test_tool_result_store_does_not_persist_small_fields_when_payload_is_over_budget(tmp_path) -> None:
    store = ToolResultStore(tmp_path, run_id="small-fields")
    payload = {
        "web_payload": {
            "deepsearch": {"stop_reason": "distilled_evidence_gap"},
            "results": [
                {
                    "title": "Codex CLI - OpenAI Developers",
                    "url": "https://developers.openai.com/codex/cli",
                    "content": "short source summary",
                }
                for _index in range(20)
            ],
        }
    }

    budgeted, replacements = store.apply_budget(
        payload,
        field_limit_bytes=6000,
        preview_size_bytes=2000,
        payload_budget_bytes=100,
    )

    assert replacements == ()
    assert budgeted["web_payload"]["deepsearch"]["stop_reason"] == "distilled_evidence_gap"
    assert budgeted["web_payload"]["results"][0]["title"] == "Codex CLI - OpenAI Developers"
    assert budgeted["web_payload"]["results"][0]["url"] == "https://developers.openai.com/codex/cli"


def test_tool_result_store_persists_large_content_without_replacing_source_metadata(tmp_path) -> None:
    store = ToolResultStore(tmp_path, run_id="large-content")
    payload = {
        "web_payload": {
            "deepsearch": {"stop_reason": "distilled_evidence_gap"},
            "results": [
                {
                    "title": "Codex CLI - OpenAI Developers",
                    "url": "https://developers.openai.com/codex/cli",
                    "content": "official source evidence\n" + ("x" * 9000),
                }
            ],
        }
    }

    budgeted, replacements = store.apply_budget(
        payload,
        field_limit_bytes=6000,
        preview_size_bytes=500,
        payload_budget_bytes=4000,
    )

    assert len(replacements) == 1
    assert replacements[0].json_path == "$.web_payload.results[0].content"
    assert budgeted["web_payload"]["results"][0]["title"] == "Codex CLI - OpenAI Developers"
    assert budgeted["web_payload"]["results"][0]["url"] == "https://developers.openai.com/codex/cli"
    assert budgeted["web_payload"]["deepsearch"]["stop_reason"] == "distilled_evidence_gap"
    assert PERSISTED_OUTPUT_TAG in budgeted["web_payload"]["results"][0]["content"]
