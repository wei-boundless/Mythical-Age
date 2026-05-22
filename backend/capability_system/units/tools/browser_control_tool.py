from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Type

from langchain_core.callbacks.manager import AsyncCallbackManagerForToolRun, CallbackManagerForToolRun
from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from project_layout import ProjectLayout


BrowserAction = Literal["open", "snapshot", "click", "type", "wait", "screenshot", "extract", "close"]


class BrowserControlInput(BaseModel):
    action: BrowserAction = Field(..., description="Browser action: open, snapshot, click, type, wait, screenshot, extract, close.")
    url: str = Field(default="", description="URL for action=open.")
    selector: str = Field(default="", description="CSS selector for click/type/extract. Prefer selectors from snapshot output.")
    text: str = Field(default="", description="Text to click, type, wait for, or extract when selector is not provided.")
    value: str = Field(default="", description="Input value for action=type.")
    timeout_ms: int = Field(default=8000, ge=500, le=60000, description="Maximum wait time in milliseconds.")
    screenshot_name: str = Field(default="", description="Optional screenshot filename stem for action=screenshot.")


@dataclass
class _BrowserSession:
    playwright: Any
    browser: Any
    context: Any
    page: Any


_SESSION: _BrowserSession | None = None


def _collapse(text: str, limit: int = 220) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    return value[:limit]


def _runtime_root(base_dir: Path) -> Path:
    return ProjectLayout.from_backend_dir(base_dir).runtime_state_dir


class BrowserControlTool(BaseTool):
    name: str = "browser_control"
    description: str = (
        "Operate a real local browser page using Playwright. "
        "Use open, snapshot, click, type, wait, screenshot, extract, and close. "
        "Always inspect with snapshot before interacting."
    )
    args_schema: Type[BaseModel] = BrowserControlInput
    model_config = ConfigDict(arbitrary_types_allowed=True)
    _root_dir: Path = PrivateAttr()

    def __init__(self, root_dir: Path, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._root_dir = root_dir

    def _run(
        self,
        action: BrowserAction,
        url: str = "",
        selector: str = "",
        text: str = "",
        value: str = "",
        timeout_ms: int = 8000,
        screenshot_name: str = "",
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> str:
        try:
            return json.dumps(
                self._execute(
                    action=action,
                    url=url,
                    selector=selector,
                    text=text,
                    value=value,
                    timeout_ms=timeout_ms,
                    screenshot_name=screenshot_name,
                ),
                ensure_ascii=False,
                sort_keys=True,
            )
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    async def _arun(
        self,
        action: BrowserAction,
        url: str = "",
        selector: str = "",
        text: str = "",
        value: str = "",
        timeout_ms: int = 8000,
        screenshot_name: str = "",
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> str:
        return await asyncio.to_thread(self._run, action, url, selector, text, value, timeout_ms, screenshot_name, None)

    def _execute(
        self,
        *,
        action: str,
        url: str,
        selector: str,
        text: str,
        value: str,
        timeout_ms: int,
        screenshot_name: str,
    ) -> dict[str, Any]:
        normalized = str(action or "").strip().lower()
        if normalized == "close":
            return self._close()
        page = self._page()
        page.set_default_timeout(int(timeout_ms or 8000))
        if normalized == "open":
            if not str(url or "").strip():
                return {"ok": False, "error": "url is required"}
            page.goto(str(url).strip(), wait_until="domcontentloaded", timeout=int(timeout_ms or 8000))
            return self._state(page)
        if normalized == "snapshot":
            return {**self._state(page), "snapshot": self._snapshot(page)}
        if normalized == "click":
            self._locator(page, selector=selector, text=text).click(timeout=int(timeout_ms or 8000))
            return self._state(page)
        if normalized == "type":
            target = self._locator(page, selector=selector, text=text)
            target.fill(str(value or ""), timeout=int(timeout_ms or 8000))
            return self._state(page)
        if normalized == "wait":
            if selector.strip():
                page.locator(selector.strip()).first.wait_for(timeout=int(timeout_ms or 8000))
            elif text.strip():
                page.get_by_text(text.strip(), exact=False).first.wait_for(timeout=int(timeout_ms or 8000))
            else:
                page.wait_for_timeout(min(max(int(timeout_ms or 1000), 500), 10000))
            return self._state(page)
        if normalized == "screenshot":
            return {**self._state(page), "screenshot": self._screenshot(page, screenshot_name)}
        if normalized == "extract":
            return {**self._state(page), "content": self._extract(page, selector=selector, text=text)}
        return {"ok": False, "error": f"unsupported browser action: {action}"}

    def _page(self):
        global _SESSION
        if _SESSION is not None:
            return _SESSION.page
        from playwright.sync_api import sync_playwright

        playwright = sync_playwright().start()
        try:
            browser = playwright.chromium.launch(channel="msedge", headless=False)
        except Exception:
            browser = playwright.chromium.launch(headless=False)
        context = browser.new_context(viewport={"width": 1365, "height": 900})
        page = context.new_page()
        _SESSION = _BrowserSession(playwright=playwright, browser=browser, context=context, page=page)
        return page

    def _close(self) -> dict[str, Any]:
        global _SESSION
        if _SESSION is None:
            return {"ok": True, "closed": False}
        try:
            _SESSION.context.close()
            _SESSION.browser.close()
            _SESSION.playwright.stop()
        finally:
            _SESSION = None
        return {"ok": True, "closed": True}

    def _locator(self, page: Any, *, selector: str, text: str):
        if str(selector or "").strip():
            return page.locator(selector.strip()).first
        if str(text or "").strip():
            return page.get_by_text(text.strip(), exact=False).first
        raise ValueError("selector or text is required")

    def _state(self, page: Any) -> dict[str, Any]:
        return {
            "ok": True,
            "url": page.url,
            "title": page.title(),
        }

    def _snapshot(self, page: Any) -> dict[str, Any]:
        elements: list[dict[str, str]] = []
        locator = page.locator("a,button,input,textarea,select,[role=button],[contenteditable=true]")
        count = min(locator.count(), 80)
        for index in range(count):
            item = locator.nth(index)
            try:
                if not item.is_visible():
                    continue
                tag = item.evaluate("el => el.tagName.toLowerCase()")
                label = _collapse(
                    item.get_attribute("aria-label")
                    or item.get_attribute("placeholder")
                    or item.inner_text(timeout=500)
                    or item.get_attribute("value")
                    or ""
                )
                selector = self._best_selector(item, index)
                elements.append({"tag": str(tag), "text": label, "selector": selector})
            except Exception:
                continue
        body_text = _collapse(page.locator("body").inner_text(timeout=2000), 1200)
        return {"text": body_text, "elements": elements}

    def _best_selector(self, item: Any, index: int) -> str:
        for attr in ("data-testid", "data-test", "aria-label", "name", "id"):
            value = item.get_attribute(attr)
            if value:
                if attr == "id":
                    return f"#{value}"
                escaped = str(value).replace('"', '\\"')
                return f'[{attr}="{escaped}"]'
        tag = item.evaluate("el => el.tagName.toLowerCase()")
        return f"{tag} >> nth={index}"

    def _screenshot(self, page: Any, screenshot_name: str) -> dict[str, Any]:
        out_dir = _runtime_root(self._root_dir) / "browser_screenshots"
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(screenshot_name or "").strip()).strip(".-")
        filename = f"{stem or 'browser'}-{int(time.time())}.png"
        path = out_dir / filename
        page.screenshot(path=str(path), full_page=True)
        return {"path": str(path), "bytes": path.stat().st_size}

    def _extract(self, page: Any, *, selector: str, text: str) -> str:
        if selector.strip():
            return page.locator(selector.strip()).first.inner_text(timeout=3000)[:5000]
        if text.strip():
            return page.get_by_text(text.strip(), exact=False).first.inner_text(timeout=3000)[:5000]
        return page.locator("body").inner_text(timeout=3000)[:5000]
