from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Type
from urllib.parse import urlparse

from langchain_core.callbacks.manager import AsyncCallbackManagerForToolRun, CallbackManagerForToolRun
from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from runtime_encoding import utf8_subprocess_text_kwargs


PRICE_PATTERN = re.compile(r"(?<!\w)(\$?\d{1,3}(?:,\d{3})*(?:\.\d+)?|\$?\d+\.\d+)")
STOCK_TICKER_PATTERN = re.compile(r"\bxau\.[a-z]{1,4}\b", re.IGNORECASE)
LABELED_PRICE_PATTERNS = (
    re.compile(r"current(?: gold)?(?: spot)? price(?: is|:)?\s*\$?(\d{1,3}(?:,\d{3})*(?:\.\d+)?)", re.IGNORECASE),
    re.compile(r"spot(?: gold)? price(?: is|:)?\s*\$?(\d{1,3}(?:,\d{3})*(?:\.\d+)?)", re.IGNORECASE),
    re.compile(r"xau/?usd[^0-9]{0,24}(\d{1,3}(?:,\d{3})*(?:\.\d+)?)", re.IGNORECASE),
    re.compile(r"buy(?:ing)?(?: price)?(?: is|:)?\s*\$?(\d{1,3}(?:,\d{3})*(?:\.\d+)?)", re.IGNORECASE),
    re.compile(r"sell(?:ing)?(?: price)?(?: is|:)?\s*\$?(\d{1,3}(?:,\d{3})*(?:\.\d+)?)", re.IGNORECASE),
    re.compile(r"bid(?: price)?(?: is|:)?\s*\$?(\d{1,3}(?:,\d{3})*(?:\.\d+)?)", re.IGNORECASE),
    re.compile(r"ask(?: price)?(?: is|:)?\s*\$?(\d{1,3}(?:,\d{3})*(?:\.\d+)?)", re.IGNORECASE),
)
HISTORICAL_PRICE_MARKERS = (
    "history",
    "historical",
    "in modern history",
    "gold price history",
    "all-time high",
    "all-time highs",
    "since then",
    "abandoned the gold standard",
    "1971",
)
NEWS_ARTICLE_MARKERS = (
    "/news/",
    "yahoo.com/news",
    "finance.yahoo.com/news",
    "analysis",
    "commodity and currency check",
    "market wrap",
    "outlook",
)

SEARCH_PLANS: tuple[dict[str, Any], ...] = (
    {
        "query": "spot gold price XAU/USD today USD per troy ounce",
        "topic": "finance",
        "time_range": "day",
        "max_results": 8,
    },
    {
        "query": "gold price today live XAU/USD per ounce",
        "topic": "finance",
        "time_range": None,
        "max_results": 8,
    },
    {
        "query": "XAU USD spot price",
        "topic": "finance",
        "time_range": None,
        "max_results": 8,
    },
    {
        "query": "gold spot price xau usd",
        "topic": "general",
        "time_range": None,
        "max_results": 6,
    },
)


class GetGoldPriceInput(BaseModel):
    query: str = Field(..., description="User request asking for the latest gold price or XAU/USD spot price.")


def _looks_garbled(text: str) -> bool:
    value = str(text or "")
    if not value:
        return False
    markers = (
        "\ufffd",
        "锟",
        "閿",
        "浔板叆浠",
        "榛勯噾",
        "cl?ture",
        "Mise ? jour",
    )
    return any(marker in value for marker in markers)


def _fallback_title(url: str) -> str:
    host = urlparse(url or "").netloc.strip()
    return host or "source"


def _clean_visible_text(text: str, fallback: str = "") -> str:
    value = str(text or "").strip()
    if not value:
        return fallback
    if _looks_garbled(value):
        return fallback
    return value


def _joined_text(item: dict[str, Any]) -> str:
    title = str(item.get("title", "") or "")
    url = str(item.get("url", "") or "")
    content = str(item.get("content", "") or "")
    return f"{title}\n{url}\n{content}".lower()


def _normalize_price(raw_value: str) -> str:
    return raw_value.replace("$", "").replace(",", "").strip()


def _is_price_in_range(raw_value: str) -> bool:
    try:
        numeric = float(_normalize_price(raw_value))
    except ValueError:
        return False
    return 500.0 <= numeric <= 10000.0


def _is_bad_gold_result(item: dict[str, Any]) -> bool:
    joined = _joined_text(item)
    bad_markers = (
        "xau.to",
        "goldmoney inc",
        "currency-converter",
        "convert gold ounce",
        "xau to idr",
        "aud to ngn",
        "syrian pound",
        "instagram.com",
        "app store",
        "google play",
    )
    if any(marker in joined for marker in bad_markers):
        return True
    if STOCK_TICKER_PATTERN.search(joined):
        return True
    if "etf" in joined and "spot gold" not in joined and "gold spot price" not in joined:
        return True
    if "stock" in joined and "spot gold" not in joined and "gold spot price" not in joined:
        return True
    return False


def _is_news_article_result(item: dict[str, Any]) -> bool:
    joined = _joined_text(item)
    url = str(item.get("url", "") or "").lower()
    return any(marker in url or marker in joined for marker in NEWS_ARTICLE_MARKERS)


def _extract_price_text(item: dict[str, Any]) -> str | None:
    joined = f"{item.get('title', '')}\n{item.get('content', '')}"

    for pattern in LABELED_PRICE_PATTERNS:
        match = pattern.search(joined)
        if not match:
            continue
        cleaned = _normalize_price(match.group(1))
        if _is_price_in_range(cleaned):
            return cleaned

    candidates: list[tuple[float, str]] = []
    for match in PRICE_PATTERN.finditer(joined):
        raw_value = match.group(1).strip()
        cleaned = _normalize_price(raw_value)
        if not _is_price_in_range(cleaned):
            continue

        start = max(0, match.start() - 100)
        end = min(len(joined), match.end() + 100)
        window = joined[start:end].lower()
        local_start = max(0, match.start() - 28)
        local_end = min(len(joined), match.end() + 28)
        local_window = joined[local_start:local_end].lower()

        score = 0.0
        numeric = float(cleaned)
        if 1000.0 <= numeric <= 8000.0:
            score += 4.0
        if "$" in raw_value:
            score += 2.0
        if any(marker in window for marker in ("xau/usd", "xau usd", "xauusd", "spot gold", "gold spot price")):
            score += 4.0
        if any(marker in window for marker in ("current price", "current spot", "spot price", "per ounce", "troy ounce", "usd/oz")):
            score += 5.0
        if any(marker in window for marker in ("today", "live", "latest", "updated")):
            score += 2.0
        if any(marker in local_window for marker in ("buy", "sell", "bid", "ask")):
            score += 1.0
        if "futures" in local_window or "gold futures" in window:
            score -= 8.0
        if any(marker in window for marker in ("forecast", "target", "targets", "end-2026", "1-3 months", "12 months")):
            score -= 5.0
        if any(marker in local_window for marker in ("52 week", "52-week", "range", "high", "low", "prev. close", "open")):
            score -= 6.0
        if any(marker in window for marker in ("gram", "grams", "kilo", "kg", "31.10", "32.15")):
            score -= 5.0
        if any(marker in window for marker in HISTORICAL_PRICE_MARKERS):
            score -= 8.0
        if any(marker in local_window for marker in ("above", "below", "around", "about")) and any(
            marker in window for marker in HISTORICAL_PRICE_MARKERS
        ):
            score -= 6.0

        candidates.append((score, cleaned))

    if not candidates:
        return None

    best_score, best_value = max(candidates, key=lambda item: (item[0], float(item[1])))
    if best_score < 4.0:
        return None
    return best_value


def _score_result(item: dict[str, Any]) -> float:
    if _is_bad_gold_result(item):
        return -100.0

    joined = _joined_text(item)
    url = str(item.get("url", "") or "").lower()

    score = 0.0
    if any(marker in joined for marker in ("xau/usd", "xau usd", "xauusd")):
        score += 7.0
    if any(marker in joined for marker in ("spot gold", "gold spot price", "spot price")):
        score += 5.0
    if any(marker in joined for marker in ("usd/oz", "usd per ounce", "per ounce", "troy ounce")):
        score += 4.0
    if any(marker in joined for marker in ("current price", "current gold spot price", "today", "live", "updated")):
        score += 2.0
    if any(marker in joined for marker in ("bid price", "ask price", "buying price", "selling price", "buy price", "sell price")):
        score += 4.0
    if any(domain in url for domain in ("metalcharts.org", "showgoldprice.com", "goldpal.io", "goldsilver.ai", "investing.com", "gold.org")):
        score += 2.5
    if "finance.yahoo" in url:
        score -= 4.0
    if _is_news_article_result(item):
        score -= 6.0
    if _looks_garbled(str(item.get("content", "") or "")):
        score -= 1.5
    if _extract_price_text(item):
        score += 5.0
    return score


def _pick_best_result(results: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = [item for item in results if not _is_bad_gold_result(item)]
    if not candidates:
        return None
    ranked = sorted(candidates, key=_score_result, reverse=True)
    best = ranked[0]
    if _score_result(best) < 4.0:
        return None
    return best


def _pick_best_price_result(results: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = [item for item in results if _extract_price_text(item)]
    if not candidates:
        return None
    return max(candidates, key=_score_result)


def _clean_summary(text: str) -> str:
    summary = str(text or "").strip()
    if not summary or _looks_garbled(summary):
        return ""
    return summary


def _dedupe_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for item in results:
        url = str(item.get("url", "") or "").strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        deduped.append(item)
    return deduped


class GetGoldPriceTool(BaseTool):
    name: str = "get_gold_price"
    description: str = (
        "Get the latest spot gold price using Tavily-backed search and return a concise Chinese answer with sources."
    )
    args_schema: Type[BaseModel] = GetGoldPriceInput
    model_config = ConfigDict(arbitrary_types_allowed=True)
    _root_dir: Path = PrivateAttr()

    def __init__(self, root_dir: Path, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._root_dir = root_dir

    def _run(
        self,
        query: str,
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> str:
        script_path = self._root_dir / "skills" / "web-search" / "scripts" / "tavily_search.py"
        if not script_path.exists():
            return "黄金价格查询失败：未找到 Tavily 搜索脚本。"

        payload_errors: list[str] = []
        aggregated_results: list[dict[str, Any]] = []
        selected_query = SEARCH_PLANS[0]["query"]

        for plan in SEARCH_PLANS:
            selected_query = str(plan["query"])
            payload = self._run_search(
                script_path=script_path,
                search_query=selected_query,
                topic=str(plan.get("topic") or "general"),
                time_range=plan.get("time_range"),
                max_results=int(plan.get("max_results") or 8),
            )
            if isinstance(payload, str):
                payload_errors.append(payload)
                continue
            aggregated_results.extend(payload.get("results") or [])
            if _pick_best_price_result(payload.get("results") or []):
                break

        results = _dedupe_results(aggregated_results)
        if not results:
            return payload_errors[-1] if payload_errors else "黄金价格查询失败：本次 Tavily 搜索证据不足。"

        best = _pick_best_price_result(results) or _pick_best_result(results)
        if best is None:
            return "黄金价格查询失败：未找到可靠的 XAU/USD 现货黄金来源。"

        title = _clean_visible_text(
            str(best.get("title", "") or ""),
            _fallback_title(str(best.get("url", "") or "")),
        )
        url = str(best.get("url", "") or "").strip()
        summary = _clean_summary(best.get("content", ""))
        published = str(best.get("published_date", "") or "").strip()
        price_text = _extract_price_text(best)

        filtered_sources: list[str] = []
        for item in sorted(results, key=_score_result, reverse=True):
            if _is_bad_gold_result(item):
                continue
            if _score_result(item) < 1.0:
                continue
            item_title = _clean_visible_text(
                str(item.get("title", "") or ""),
                _fallback_title(str(item.get("url", "") or "")),
            )
            item_url = str(item.get("url", "") or "").strip()
            if not item_url:
                continue
            filtered_sources.append(f"- {item_title}: {item_url}")
            if len(filtered_sources) >= 3:
                break

        query_date = datetime.now().strftime("%Y-%m-%d")
        lines = ["结论：", ""]
        if price_text:
            lines.append(f"- 当前现货黄金 XAU/USD 参考价约为 {price_text} 美元/盎司。")
        else:
            lines.append("- 已检索到现货黄金 XAU/USD 相关来源，但未能稳定抽取单一价格数字，请以来源页为准。")
        lines.append(f"- 本次优先采用的来源是：{title}。")
        lines.append(f"- 使用查询词：{selected_query}")
        if summary:
            lines.append(f"- 摘要：{summary}")
        if url:
            lines.append(f"- 首条来源：{url}")

        lines.extend(["", "来源："])
        if filtered_sources:
            lines.extend(filtered_sources)
        else:
            lines.append("- 本次无可展示来源链接。")

        lines.extend(
            [
                "",
                "时间说明：",
                f"- 查询时间：{query_date}",
                f"- 来源发布日期：{published or '未提供'}",
            ]
        )
        return "\n".join(lines)

    def _run_search(
        self,
        script_path: Path,
        search_query: str,
        topic: str,
        time_range: str | None,
        max_results: int,
    ) -> dict[str, Any] | str:
        command = [
            sys.executable,
            str(script_path),
            "--query",
            search_query,
            "--topic",
            topic,
            "--max-results",
            str(max_results),
        ]
        if time_range:
            command.extend(["--time-range", time_range])

        try:
            completed = subprocess.run(
                command,
                cwd=self._root_dir,
                capture_output=True,
                timeout=25,
                check=False,
                **utf8_subprocess_text_kwargs(),
            )
        except subprocess.TimeoutExpired:
            return "黄金价格查询失败：Tavily 查询超时。"

        raw = (completed.stdout or completed.stderr or "").strip()
        if not raw:
            return "黄金价格查询失败：联网搜索未返回任何结果。"

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return f"黄金价格查询失败：无法解析搜索结果。\n原始输出：{raw[:1200]}"

        if not payload.get("ok"):
            status_code = payload.get("status_code")
            body = str(payload.get("body", "") or payload.get("error", "") or "").strip()
            if status_code in {401, 403}:
                return "黄金价格查询失败：Tavily 鉴权失败，请检查 TAVILY_API_KEY 是否有效。"
            if status_code == 429:
                return "黄金价格查询失败：Tavily 达到限流或额度限制。"
            if status_code and int(status_code) >= 500:
                return "黄金价格查询失败：Tavily 服务端异常。"
            return f"黄金价格查询失败：{body or 'Tavily 返回错误。'}"

        return payload

    async def _arun(
        self,
        query: str,
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> str:
        return await asyncio.to_thread(self._run, query, None)
