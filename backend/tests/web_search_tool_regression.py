from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from capability_system.tools.tool_units import web_search_tool
from capability_system.tools.tool_units.web_search_tool import WebSearchTool, _format_search_summary


class _FakeTavilyResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return {
            "query": "南京现在天气",
            "topic": "general",
            "results": [
                {
                    "title": "南京天气",
                    "url": "https://weather.example/nanjing",
                    "content": "南京当前多云，气温 24°C，东南风 3 级。",
                    "score": 0.98,
                }
            ],
        }


def test_format_search_summary_for_gold_query_is_human_readable() -> None:
    text = _format_search_summary(
        {
            "ok": True,
            "query": "黄金价格 今日 2026",
            "topic": "finance",
            "results": [
                {
                    "title": "Gold and silver prices today",
                    "url": "https://finance.yahoo.com/example",
                    "content": "Gold opened at $4569.30 this morning and rose to $4711.90 as of 6:17 a.m. ET.",
                },
                {
                    "title": "黃金大漲逾3%",
                    "url": "https://hk.finance.yahoo.com/example",
                    "content": "現貨黃金上漲3.1%，報每盎司4,698.24美元，黃金期貨報每盎司4,705.06美元。",
                },
            ],
        },
        query="黄金价格 今日 2026",
        topic="finance",
    )

    assert "查询：黄金价格 今日 2026" in text
    assert "主题：finance" in text
    assert "关键信息：" in text
    assert "$4711.90" in text
    assert "來源" not in text
    assert "来源：" in text
    assert "finance.yahoo.com" in text


def test_web_search_tool_executes_tavily_branch_for_current_weather(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    def fake_post(*args: Any, **kwargs: Any) -> _FakeTavilyResponse:
        calls.append({"args": args, "kwargs": kwargs})
        return _FakeTavilyResponse()

    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    monkeypatch.setattr(web_search_tool.httpx, "post", fake_post)

    text = WebSearchTool(root_dir=BACKEND_DIR)._run(query="南京现在天气")

    assert "查询：南京现在天气" in text
    assert "南京当前多云" in text
    assert calls
    assert calls[0]["kwargs"]["json"]["query"] == "南京现在天气"
    assert "time_range" not in calls[0]["kwargs"]["json"]


