from __future__ import annotations

import json

from harness.runtime.compiler import RuntimeCompiler


def test_single_turn_attachment_context_index_is_not_user_message_text() -> None:
    result = RuntimeCompiler().compile_single_agent_turn_packet(
        session_id="session:attachment-index",
        turn_id="turn:attachment-index",
        agent_invocation_id="aginvoke:attachment-index",
        user_message="请识别图片里的文字",
        history=[],
        session_context={
            "turn_input_attachments": [
                {
                    "attachment_id": "att:image:1",
                    "filename": "screen.png",
                    "mime_type": "image/png",
                    "path": "storage/chat_attachments/session:attachment-index/screen.png",
                    "size_bytes": 1200,
                    "content_sha256": "sha256:abc123",
                    "width": 640,
                    "height": 480,
                    "authority": "api.chat_attachments",
                }
            ]
        },
        runtime_assembly={
            "profile": {"profile_ref": "main_interactive_agent"},
            "task_environment": {"environment_id": "env.general.workspace"},
            "available_tools": [
                {"tool_name": "attachment_extract_text", "operation_id": "op.mcp_image_ocr", "owner_scope": "none"}
            ],
            "operation_authorization": {"allowed_operations": ["op.model_response", "op.mcp_image_ocr"]},
            "control_capabilities": {"may_call_tools": True},
        },
    )

    kinds = [segment["kind"] for segment in result.packet.segment_plan["segments"]]
    attachment_segment = _segment_by_kind(result.packet, "attachment_context_index")
    attachment_payload = _payload_with_title(result.packet, "Single agent turn attachment context index")
    current_request_payload = _payload_with_title(result.packet, "Single agent turn current request")
    current_request_text = json.dumps(current_request_payload, ensure_ascii=False)

    assert kinds.index("attachment_context_index") < kinds.index("volatile_user")
    assert attachment_segment["metadata"]["prompt_assembly_layer"] == "attachment_context_index"
    assert attachment_payload["attachment_context_index"][0]["attachment_id"] == "att:image:1"
    assert attachment_payload["attachment_context_index"][0]["content_sha256"] == "sha256:abc123"
    assert attachment_payload["attachment_context_index"][0]["rehydration_action"] == "attachment_extract_text"
    assert current_request_payload["user_message"] == "请识别图片里的文字"
    assert "storage/chat_attachments" not in current_request_text
    assert "如果用户要求识别" not in current_request_text


def _segment_by_kind(packet, kind: str) -> dict[str, object]:
    for segment in packet.segment_plan["segments"]:
        if segment["kind"] == kind:
            return dict(segment)
    raise AssertionError(f"missing segment kind: {kind}")


def _payload_with_title(packet, title: str) -> dict[str, object]:
    for message in packet.model_messages:
        content = str(dict(message).get("content") or "")
        if content.startswith(title + "\n"):
            return json.loads(content.split("\n", 1)[1])
    raise AssertionError(f"missing model message title: {title}")
