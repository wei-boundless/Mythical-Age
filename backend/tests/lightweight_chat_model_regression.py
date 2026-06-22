from __future__ import annotations

import asyncio
import json

import httpx

from runtime.model_gateway.lightweight_chat_model import LightweightChatModel


def test_lightweight_chat_model_serializes_tools_and_parses_response() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        captured["body"] = body
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-test",
                "model": "deepseek-v4-flash",
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "reasoning_content": "checked",
                            "tool_calls": [
                                {
                                    "id": "call_read",
                                    "type": "function",
                                    "function": {"name": "read_file", "arguments": "{\"path\":\"README.md\"}"},
                                }
                            ],
                        },
                    }
                ],
                "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
            },
        )

    async def run() -> object:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        model = LightweightChatModel(
            provider="deepseek",
            model="deepseek-v4-flash",
            api_key="test-key",
            base_url="https://api.deepseek.com",
            timeout_seconds=1.0,
            max_output_tokens=128,
            output_token_parameter="max_tokens",
            extra_body={"thinking": {"type": "disabled"}},
            http_async_client=client,
            owns_client=True,
        )
        try:
            bound = model.bind_tools(
                [
                    {
                        "name": "read_file",
                        "description": "Read a file.",
                        "input_schema": {
                            "type": "object",
                            "properties": {"path": {"type": "string"}},
                            "required": ["path"],
                        },
                    }
                ],
                parallel_tool_calls=False,
            )
            return await bound.ainvoke([{"role": "user", "content": "read"}])
        finally:
            await model.close()

    response = asyncio.run(run())
    body = captured["body"]

    assert body["model"] == "deepseek-v4-flash"
    assert body["max_tokens"] == 128
    assert body["thinking"] == {"type": "disabled"}
    assert body["tools"][0]["function"]["name"] == "read_file"
    assert body["parallel_tool_calls"] is False
    assert response.tool_calls == [{"id": "call_read", "name": "read_file", "args": {"path": "README.md"}, "type": "tool_call"}]
    assert response.additional_kwargs["reasoning_content"] == "checked"
    assert response.usage_metadata["prompt_tokens"] == 5


def test_lightweight_chat_model_sends_reasoning_content_in_request_body() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        captured["body"] = body
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-test",
                "model": "deepseek-v4-flash",
                "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "ok"}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
            },
        )

    async def run() -> object:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        model = LightweightChatModel(
            provider="deepseek",
            model="deepseek-v4-flash",
            api_key="test-key",
            base_url="https://api.deepseek.com",
            timeout_seconds=1.0,
            max_output_tokens=128,
            output_token_parameter="max_tokens",
            http_async_client=client,
            owns_client=True,
        )
        try:
            return await model.ainvoke(
                [
                    {
                        "role": "assistant",
                        "content": "",
                        "reasoning_content": "must be replayed for DeepSeek",
                        "tool_calls": [{"id": "call_read", "name": "read_file", "args": {"path": "README.md"}}],
                    },
                    {"role": "tool", "tool_call_id": "call_read", "content": "done"},
                    {"role": "user", "content": "continue"},
                ]
            )
        finally:
            await model.close()

    asyncio.run(run())
    body = captured["body"]

    assert "must be replayed for DeepSeek" in json.dumps(body, ensure_ascii=False)
    assert body["messages"][0]["reasoning_content"] == "must be replayed for DeepSeek"
    assert body["messages"][0]["tool_calls"][0]["function"]["name"] == "read_file"


def test_lightweight_chat_model_stream_aggregates_tool_call_chunks_and_usage() -> None:
    stream_payload = "\n\n".join(
        [
            'data: {"id":"chatcmpl-test","model":"deepseek-v4-flash","choices":[{"delta":{"content":"he"},"finish_reason":null}]}',
            'data: {"id":"chatcmpl-test","model":"deepseek-v4-flash","choices":[{"delta":{"content":"llo","tool_calls":[{"index":0,"id":"call_read","type":"function","function":{"name":"read_file","arguments":"{\\"path\\""}}]},"finish_reason":null}]}',
            'data: {"id":"chatcmpl-test","model":"deepseek-v4-flash","choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":":\\"README.md\\"}"}}]},"finish_reason":"tool_calls"}],"usage":{"prompt_tokens":5,"completion_tokens":3,"total_tokens":8}}',
            "data: [DONE]",
        ]
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=stream_payload.encode("utf-8"))

    async def run() -> object:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        model = LightweightChatModel(
            provider="deepseek",
            model="deepseek-v4-flash",
            api_key="test-key",
            base_url="https://api.deepseek.com",
            timeout_seconds=1.0,
            max_output_tokens=128,
            output_token_parameter="max_tokens",
            http_async_client=client,
            owns_client=True,
        )
        try:
            aggregate = None
            async for chunk in model.astream([{"role": "user", "content": "read"}]):
                aggregate = chunk if aggregate is None else aggregate + chunk
            return aggregate
        finally:
            await model.close()

    aggregate = asyncio.run(run())

    assert aggregate.content == "hello"
    assert aggregate.tool_calls == [{"id": "call_read", "name": "read_file", "args": {"path": "README.md"}, "type": "tool_call"}]
    assert aggregate.usage_metadata["total_tokens"] == 8
