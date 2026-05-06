from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from capability_system.units.tools.web_search_tool import _format_search_summary


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
