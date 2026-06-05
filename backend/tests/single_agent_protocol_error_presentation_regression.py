from __future__ import annotations

from pathlib import Path
import sys


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from harness.loop.single_agent_turn import _single_agent_protocol_error_user_text


def test_single_agent_protocol_errors_do_not_expose_model_protocol_terms() -> None:
    for code in [
        "single_agent_turn_multiple_native_actions",
        "single_agent_turn_multiple_action_sources",
        "single_agent_turn_json_action_required",
        "single_agent_turn_invalid_json_action",
        "single_agent_turn_invalid_native_action",
        "single_agent_turn_model_protocol_error",
        "single_agent_turn_protocol_repair_failed",
        "unknown_protocol_error",
    ]:
        text = _single_agent_protocol_error_user_text(code)

        assert text
        assert "模型" not in text
        assert "JSON" not in text
        assert "系统动作" not in text
        assert "native" not in text
        assert "协议" not in text
        assert "停住" in text
