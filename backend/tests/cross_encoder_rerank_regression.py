from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from RAG.reranker import CrossEncoderReranker, HeuristicReranker, build_reranker


class FakeCrossEncoder:
    init_calls: list[dict] = []
    predict_calls: list[dict] = []

    def __init__(self, model_name: str, **kwargs) -> None:
        self.model_name = model_name
        self.kwargs = dict(kwargs)
        FakeCrossEncoder.init_calls.append({"model_name": model_name, "kwargs": dict(kwargs)})

    def predict(self, pairs, batch_size: int = 32, show_progress_bar: bool | None = None):
        FakeCrossEncoder.predict_calls.append(
            {
                "pairs": list(pairs),
                "batch_size": batch_size,
                "show_progress_bar": show_progress_bar,
            }
        )
        return [0.5, 0.5, 0.1]


def main() -> None:
    fake_module = ModuleType("sentence_transformers")
    fake_module.CrossEncoder = FakeCrossEncoder
    original_module = sys.modules.get("sentence_transformers")
    sys.modules["sentence_transformers"] = fake_module
    try:
        reranker = CrossEncoderReranker(
            model_name="fake-cross-encoder",
            top_n=2,
            batch_size=4,
            max_length=256,
            device="cpu",
        )
        results = [
            {"text": "alpha document", "score": 0.42, "retrieval_score": 0.42},
            {"text": "beta document", "score": 0.84, "retrieval_score": 0.84},
            {"text": "gamma document", "score": 0.10, "retrieval_score": 0.10},
        ]
        ranked = reranker.rerank_dict_results(query="beta query", results=results)

        assert FakeCrossEncoder.init_calls
        assert FakeCrossEncoder.init_calls[0]["model_name"] == "fake-cross-encoder"
        assert FakeCrossEncoder.init_calls[0]["kwargs"]["device"] == "cpu"
        assert FakeCrossEncoder.init_calls[0]["kwargs"]["max_length"] == 256
        assert FakeCrossEncoder.predict_calls
        assert FakeCrossEncoder.predict_calls[0]["batch_size"] == 4
        assert FakeCrossEncoder.predict_calls[0]["show_progress_bar"] is False
        assert [item["text"] for item in ranked[:2]] == ["beta document", "alpha document"]
        assert ranked[0]["rerank_backend"] == "cross_encoder"
        assert ranked[0]["rerank_model"] == "fake-cross-encoder"
        assert ranked[0]["rerank_applied"] is True
        assert ranked[2]["rerank_backend"] == "tail_passthrough"
        assert ranked[2]["rerank_applied"] is False

        settings = SimpleNamespace(
            rerank_enabled=True,
            rerank_provider="cross_encoder",
            rerank_model="fake-cross-encoder",
            rerank_api_key=None,
            rerank_base_url=None,
            rerank_top_n=6,
            rerank_candidate_pool=20,
            rerank_batch_size=3,
            rerank_max_length=384,
            rerank_device="cpu",
        )
        built = build_reranker(settings)
        assert isinstance(built, CrossEncoderReranker)
        assert built.batch_size == 3
        assert built.max_length == 384
    finally:
        if original_module is None:
            sys.modules.pop("sentence_transformers", None)
        else:
            sys.modules["sentence_transformers"] = original_module

    broken_module = ModuleType("sentence_transformers")

    class BrokenCrossEncoder:
        def __init__(self, *args, **kwargs) -> None:
            raise RuntimeError("boom")

    broken_module.CrossEncoder = BrokenCrossEncoder
    original_module = sys.modules.get("sentence_transformers")
    sys.modules["sentence_transformers"] = broken_module
    try:
        fallback = build_reranker(
            SimpleNamespace(
                rerank_enabled=True,
                rerank_provider="cross_encoder",
                rerank_model="broken-model",
                rerank_api_key=None,
                rerank_base_url=None,
                rerank_top_n=6,
                rerank_candidate_pool=20,
                rerank_batch_size=3,
                rerank_max_length=384,
                rerank_device="cpu",
            )
        )
        assert isinstance(fallback, HeuristicReranker)
    finally:
        if original_module is None:
            sys.modules.pop("sentence_transformers", None)
        else:
            sys.modules["sentence_transformers"] = original_module

    print("ALL PASSED (cross encoder rerank regression)")


if __name__ == "__main__":
    main()
