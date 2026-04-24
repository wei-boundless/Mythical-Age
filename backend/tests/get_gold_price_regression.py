from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "tools" / "get_gold_price_tool.py"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_module():
    callbacks_manager = types.ModuleType("langchain_core.callbacks.manager")
    callbacks_manager.AsyncCallbackManagerForToolRun = object
    callbacks_manager.CallbackManagerForToolRun = object

    tools_module = types.ModuleType("langchain_core.tools")

    class _BaseTool:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

    tools_module.BaseTool = _BaseTool

    sys.modules.setdefault("langchain_core", types.ModuleType("langchain_core"))
    sys.modules["langchain_core.callbacks"] = types.ModuleType("langchain_core.callbacks")
    sys.modules["langchain_core.callbacks.manager"] = callbacks_manager
    sys.modules["langchain_core.tools"] = tools_module

    spec = importlib.util.spec_from_file_location("get_gold_price_regression_module", TOOL_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load get_gold_price_tool.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(name="module")
def module_fixture():
    return _load_module()


def test_prefers_price_bearing_result(module) -> None:
    results = [
        {
            "title": "Gold Price Today - Live Chart & Historical Price (USD/oz)",
            "url": "https://goldsilver.ai/metal-prices/gold",
            "content": (
                "Current Gold Spot Price (USD per ounce). "
                "The gold price is universally quoted in USD per troy ounce."
            ),
        },
        {
            "title": "XAU/USD - 黄金现货 美元",
            "url": "https://cn.investing.com/currencies/xau-usd",
            "content": (
                "XAU/USD 的买入价为 4,675.35，卖出价为 4,677.21。"
                "XAU/USD 的 52 周波动区间为 2,956.60 至 5,595.46。"
            ),
        },
    ]

    best = module._pick_best_result(results)
    assert best is not None
    assert "investing.com" in best["url"]

    best_price = module._pick_best_price_result(results)
    assert best_price is not None
    assert "investing.com" in best_price["url"]

    extracted = module._extract_price_text(best_price)
    assert extracted in {"4675.35", "4677.21"}


def test_ignores_52_week_range_noise(module) -> None:
    noisy_result = {
        "title": "XAU/USD - Gold Spot",
        "url": "https://example.com/xauusd",
        "content": (
            "Prev. Close 4,758.57. 52 Week Range 2,956.60 - 5,595.46. "
            "XAU/USD bid price is 4,675.35 and ask price is 4,677.21."
        ),
    }

    extracted = module._extract_price_text(noisy_result)
    assert extracted in {"4675.35", "4677.21"}


def test_ignores_historical_above_2000_phrase(module) -> None:
    historical_result = {
        "title": "Gold Price Today - Live Gold Spot Price per Ounce | GoldPal",
        "url": "https://goldpal.io/gold-price-today",
        "content": (
            "Gold Price Today. per troy ounce (XAU/USD). Last updated: 8 minutes ago. "
            "Gold Price History. Gold has been a store of value for thousands of years. "
            "In modern history, gold was priced at $35 per ounce in 1971 when the US abandoned the gold standard. "
            "Since then, gold has reached all-time highs above $2,000 per ounce during periods of economic uncertainty."
        ),
    }

    extracted = module._extract_price_text(historical_result)
    assert extracted is None


def test_prefers_live_quote_page_over_news_article(module) -> None:
    article = {
        "title": "Pound, gold and oil prices in focus: commodity and currency check",
        "url": "https://uk.finance.yahoo.com/news/pound-gold-oil-prices-commodity-currency-093450753.html",
        "content": (
            "The spot price of gold rose by 0.1% to $2,855.82 per ounce, "
            "while gold futures dipped 0.6% to $2,876.10. On Wednesday, XAU/USD came within 20 points of the 2900 zone."
        ),
    }
    quote = {
        "title": "XAU/USD - Gold Spot US Dollar",
        "url": "https://cn.investing.com/currencies/xau-usd",
        "content": "XAU/USD bid price is 4,675.35 and ask price is 4,677.21. 52 Week Range 2,956.60 - 5,595.46.",
    }

    assert module._extract_price_text(article) in {"2855.82", "2876.10"}
    assert module._extract_price_text(quote) in {"4675.35", "4677.21"}
    assert module._score_result(quote) > module._score_result(article)
    best = module._pick_best_price_result([article, quote])
    assert best is not None
    assert "investing.com" in best["url"]


def test_search_fallback_can_recover_price(module) -> None:
    first_payload = {
        "ok": True,
        "results": [
            {
                "title": "Gold Price Today - Live Chart & Historical Price (USD/oz)",
                "url": "https://goldsilver.ai/metal-prices/gold",
                "content": "Current Gold Spot Price (USD per ounce). Live chart and market overview.",
            }
        ],
    }
    second_payload = {
        "ok": True,
        "results": [
            {
                "title": "XAU/USD - 黄金现货 美元",
                "url": "https://cn.investing.com/currencies/xau-usd",
                "content": "XAU/USD 的买入价为 4,675.35，卖出价为 4,677.21。",
            }
        ],
    }

    class _Tool(module.GetGoldPriceTool):
        def __init__(self):
            super().__init__(root_dir=ROOT)
            self.calls = []

        def _run_search(self, script_path, search_query, topic, time_range, max_results):
            self.calls.append((search_query, topic, time_range, max_results))
            if len(self.calls) == 1:
                return first_payload
            return second_payload

    tool = _Tool()
    response = tool._run("查询黄金价格")

    assert "4675.35" in response or "4677.21" in response
    assert any(search_query in response for search_query, *_ in tool.calls)
    assert len(tool.calls) >= 2


def main() -> None:
    module = _load_module()
    test_prefers_price_bearing_result(module)
    test_ignores_52_week_range_noise(module)
    test_ignores_historical_above_2000_phrase(module)
    test_prefers_live_quote_page_over_news_article(module)
    test_search_fallback_can_recover_price(module)
    print("ALL PASSED (gold price regression)")


if __name__ == "__main__":
    main()
