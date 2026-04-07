from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from RAG.reranker import RemoteApiReranker, build_reranker


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class FakeClient:
    calls: list[dict] = []

    def __init__(self, *args, **kwargs) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def post(self, url, headers=None, json=None):
        FakeClient.calls.append(
            {
                "url": url,
                "headers": headers,
                "json": json,
            }
        )
        return FakeResponse(
            {
                "output": {
                    "results": [
                        {"index": 1, "relevance_score": 0.91},
                        {"index": 0, "relevance_score": 0.62},
                        {"index": 2, "relevance_score": 0.17},
                    ]
                }
            }
        )


def main() -> None:
    import RAG.reranker as module

    original_client = module.httpx.Client
    module.httpx.Client = FakeClient
    try:
        reranker = RemoteApiReranker(
            provider="bailian",
            model_name="qwen3-rerank",
            api_key="sk-test",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            top_n=3,
        )
        results = [
            {"text": "alpha doc", "source": "a", "score": 0.12},
            {"text": "beta doc", "source": "b", "score": 0.11},
            {"text": "gamma doc", "source": "c", "score": 0.10},
            {"text": "delta doc", "source": "d", "score": 0.09},
        ]
        ranked = reranker.rerank_dict_results(query="best beta", results=results)

        assert FakeClient.calls
        assert FakeClient.calls[0]["url"] == "https://dashscope.aliyuncs.com/compatible-api/v1/reranks"
        assert FakeClient.calls[0]["headers"]["Authorization"] == "Bearer sk-test"
        assert FakeClient.calls[0]["json"]["model"] == "qwen3-rerank"
        assert FakeClient.calls[0]["json"]["top_n"] == 3
        assert FakeClient.calls[0]["json"]["documents"] == ["alpha doc", "beta doc", "gamma doc"]
        assert [item["text"] for item in ranked[:3]] == ["beta doc", "alpha doc", "gamma doc"]
        assert ranked[0]["rerank_backend"] == "bailian_api"
        assert ranked[0]["rerank_model"] == "qwen3-rerank"
        assert ranked[3]["rerank_backend"] == "tail_passthrough"

        settings = SimpleNamespace(
            rerank_enabled=True,
            rerank_provider="bailian",
            rerank_model="qwen3-rerank",
            rerank_api_key="sk-test",
            rerank_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            rerank_top_n=8,
            rerank_device=None,
        )
        built = build_reranker(settings)
        assert type(built).__name__ == "RemoteApiReranker"
    finally:
        module.httpx.Client = original_client

    print("ALL PASSED (remote rerank regression)")


if __name__ == "__main__":
    main()
