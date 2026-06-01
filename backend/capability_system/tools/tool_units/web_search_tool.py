from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Type
from urllib.parse import urlparse

from langchain_core.callbacks.manager import AsyncCallbackManagerForToolRun, CallbackManagerForToolRun
from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from runtime_encoding import utf8_subprocess_text_kwargs


class WebSearchInput(BaseModel):
    query: str = Field(..., description="The search query to run on the web.")
    topic: str = Field(
        default="general",
        description="Search topic: general, news, or finance.",
    )
    time_range: str | None = Field(
        default=None,
        description="Optional time range: day, week, month, or year.",
    )
    max_results: int = Field(default=5, description="Maximum number of results to return, up to 10.")


def _looks_garbled(text: str) -> bool:
    sample = str(text or "")
    mojibake_markers = (
        "\ufffd",
        "锟",
        "閿",
        "鈩",
        "鏂",
        "姹囩巼",
        "榛勯噾",
        "鏈€鏂",
        "鑱旂綉鎼滅储",
    )
    return any(marker in sample for marker in mojibake_markers)


def _fallback_title(url: str) -> str:
    host = urlparse(url or "").netloc.strip()
    return host or "source"


def _collapse_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _truncate(text: str, limit: int) -> str:
    normalized = _collapse_whitespace(text)
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip(" ,，。.;；:：") + "..."


def _result_host(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    return parsed.netloc.strip() or "source"


def _format_search_summary(payload: dict[str, Any], *, query: str, topic: str) -> str:
    results = [dict(item) for item in list(payload.get("results") or []) if isinstance(item, dict)]
    declared_topic = _collapse_whitespace(payload.get("topic") or topic or "general") or "general"
    lines = [
        f"查询：{_collapse_whitespace(query)}",
        f"主题：{declared_topic}",
        f"结果：命中 {len(results)} 条来源",
    ]

    highlights: list[str] = []
    answer = _truncate(payload.get("answer") or "", 220)
    if answer:
        highlights.append(answer)
    for item in results:
        title = _truncate(item.get("title") or "", 70) or _fallback_title(str(item.get("url") or ""))
        content = _truncate(item.get("content") or "", 220)
        if not content:
            continue
        highlight = f"{title}：{content}"
        if highlight not in highlights:
            highlights.append(highlight)
        if len(highlights) >= 2:
            break

    if highlights:
        lines.append("")
        lines.append("关键信息：")
        lines.extend(f"- {item}" for item in highlights[:2])

    if results:
        lines.append("")
        lines.append("来源：")
        for index, item in enumerate(results[:3], start=1):
            title = _truncate(item.get("title") or "", 80) or _fallback_title(str(item.get("url") or ""))
            host = _result_host(str(item.get("url") or ""))
            lines.append(f"{index}. {title}（{host}）")

    return "\n".join(lines).strip()


def _sanitize_search_payload(payload: dict[str, Any], query: str) -> dict[str, Any]:
    cleaned = dict(payload)
    payload_query = str(payload.get("query", "") or "")
    cleaned["query"] = query if _looks_garbled(payload_query) or not payload_query else payload_query

    cleaned_results: list[dict[str, Any]] = []
    for item in payload.get("results", []) or []:
        if not isinstance(item, dict):
            continue
        copied = dict(item)
        url = str(copied.get("url", "") or "")
        title = str(copied.get("title", "") or "")
        content = str(copied.get("content", "") or "")
        raw_content = str(copied.get("raw_content", "") or "")

        if _looks_garbled(title):
            copied["title"] = _fallback_title(url)
        if _looks_garbled(content):
            copied["content"] = "[source text unavailable due to encoding issues]"
        if raw_content and _looks_garbled(raw_content):
            copied["raw_content"] = ""
        cleaned_results.append(copied)

    cleaned["results"] = cleaned_results
    return cleaned


def _infer_topic(query: str, requested_topic: str | None) -> str:
    topic = (requested_topic or "").strip().lower()
    if topic in {"general", "news", "finance"}:
        return topic

    lowered = query.lower()
    finance_markers = (
        "gold",
        "xau",
        "stock",
        "price",
        "btc",
        "eth",
        "usd",
        "eur",
        "汇率",
        "金价",
        "黄金",
        "股价",
        "股票",
        "财报",
    )
    news_markers = (
        "news",
        "latest",
        "today",
        "recent",
        "最新",
        "新闻",
        "动态",
        "今日",
        "刚刚",
    )
    if any(marker in lowered for marker in finance_markers):
        return "finance"
    if any(marker in lowered for marker in news_markers):
        return "news"
    return "general"


def _infer_time_range(query: str, topic: str, requested: str | None) -> str | None:
    if requested in {"day", "week", "month", "year"}:
        return requested
    lowered = query.lower()
    if any(marker in lowered for marker in ("今天", "今日", "today", "current", "当前", "实时")):
        return "day"
    if topic == "news" and any(marker in lowered for marker in ("最新", "latest", "recent", "近期")):
        return "month"
    return None


class WebSearchTool(BaseTool):
    name: str = "web_search"
    description: str = (
        "Search the web for current information using Tavily. "
        "Use this for latest facts, news, official docs, links, and real-time external information."
    )
    args_schema: Type[BaseModel] = WebSearchInput
    model_config = ConfigDict(arbitrary_types_allowed=True)
    _root_dir: Path = PrivateAttr()

    def __init__(self, root_dir: Path, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._root_dir = root_dir

    def _run(
        self,
        query: str,
        topic: str = "general",
        time_range: str | None = None,
        max_results: int = 5,
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> str:
        script_path = self._root_dir / "capability_system" / "units" / "tools" / "tavily_search.py"
        if not script_path.exists():
            return "联网搜索失败：未找到 Tavily 搜索脚本。"

        resolved_topic = _infer_topic(query, topic)
        resolved_time_range = _infer_time_range(query, resolved_topic, time_range)

        command = [
            sys.executable,
            str(script_path),
            "--query",
            query,
            "--topic",
            resolved_topic,
            "--max-results",
            str(max(1, min(int(max_results), 10))),
        ]
        if resolved_time_range:
            command.extend(["--time-range", resolved_time_range])

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
            return "联网搜索失败：Tavily 查询超时。"

        raw = (completed.stdout or completed.stderr or "").strip()
        if not raw:
            return "联网搜索失败：未返回任何结果。"

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return f"联网搜索失败：无法解析 Tavily 返回内容。\n原始输出：{raw[:1500]}"

        payload = _sanitize_search_payload(payload, query)
        if not bool(payload.get("ok", True)):
            error_text = _collapse_whitespace(payload.get("error") or "联网搜索失败。")
            details = _truncate(payload.get("body") or payload.get("details") or "", 240)
            if details:
                return f"{error_text}\n详情：{details}"
            return error_text

        return _format_search_summary(
            payload,
            query=str(payload.get("query") or query),
            topic=resolved_topic,
        )

    async def _arun(
        self,
        query: str,
        topic: str = "general",
        time_range: str | None = None,
        max_results: int = 5,
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> str:
        return await asyncio.to_thread(
            self._run,
            query,
            topic,
            time_range,
            max_results,
            None,
        )


