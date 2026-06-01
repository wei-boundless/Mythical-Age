from __future__ import annotations

import json
from typing import Type

import html2text
import httpx
from langchain_core.callbacks.manager import AsyncCallbackManagerForToolRun, CallbackManagerForToolRun
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


class FetchURLInput(BaseModel):
    url: str = Field(..., description="HTTP or HTTPS URL to fetch")


class FetchURLToolError(RuntimeError):
    def __init__(self, message: str, *, code: str, retryable: bool, status_code: int | None = None) -> None:
        super().__init__(message)
        self.structured_error = {
            "code": code,
            "message": message,
            "retryable": retryable,
            "origin": "tool_provider",
            **({"status_code": status_code} if status_code is not None else {}),
        }


class FetchURLTool(BaseTool):
    name: str = "fetch_url"
    description: str = "Fetch a URL. JSON stays JSON; HTML is converted into markdown-like plain text."
    args_schema: Type[BaseModel] = FetchURLInput

    def _format_response(self, response: httpx.Response) -> str:
        content_type = response.headers.get("content-type", "")
        if "json" in content_type:
            return json.dumps(response.json(), ensure_ascii=False, indent=2)[:5000]
        if "html" in content_type:
            parser = html2text.HTML2Text()
            parser.ignore_links = False
            parser.ignore_images = True
            return parser.handle(response.text)[:5000]
        return response.text[:5000]

    def _run(
        self,
        url: str,
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> str:
        try:
            with httpx.Client(follow_redirects=True, timeout=15) as client:
                response = client.get(url)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            raise FetchURLToolError(
                f"Fetch failed for {url}: HTTP {status_code}",
                code="http_status_error",
                retryable=status_code in {408, 429} or status_code >= 500,
                status_code=status_code,
            ) from exc
        except httpx.RequestError as exc:
            raise FetchURLToolError(
                f"Fetch failed for {url}: {exc}",
                code="network_error",
                retryable=True,
            ) from exc
        except Exception as exc:
            raise FetchURLToolError(
                f"Fetch failed for {url}: {exc}",
                code="fetch_url_error",
                retryable=True,
            ) from exc
        return self._format_response(response)

    async def _arun(
        self,
        url: str,
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> str:
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
                response = await client.get(url)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            raise FetchURLToolError(
                f"Fetch failed for {url}: HTTP {status_code}",
                code="http_status_error",
                retryable=status_code in {408, 429} or status_code >= 500,
                status_code=status_code,
            ) from exc
        except httpx.RequestError as exc:
            raise FetchURLToolError(
                f"Fetch failed for {url}: {exc}",
                code="network_error",
                retryable=True,
            ) from exc
        except Exception as exc:
            raise FetchURLToolError(
                f"Fetch failed for {url}: {exc}",
                code="fetch_url_error",
                retryable=True,
            ) from exc
        return self._format_response(response)


