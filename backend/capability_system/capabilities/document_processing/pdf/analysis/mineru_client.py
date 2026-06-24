from __future__ import annotations

import hashlib
import io
import json
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from core.config import Settings, get_settings


@dataclass(frozen=True)
class MinerUApiConfig:
    enabled: bool
    base_url: str | None
    parse_path: str
    api_key: str | None
    timeout_seconds: int
    mode: str = "local_sync"

    @property
    def service_root(self) -> str:
        if not self.base_url:
            return ""
        if self.base_url.startswith("http://") or self.base_url.startswith("https://"):
            parsed = urlparse(self.base_url)
            if parsed.scheme and parsed.netloc:
                return f"{parsed.scheme}://{parsed.netloc}"
        return self.base_url.rstrip("/")

    @property
    def parse_url(self) -> str:
        if not self.base_url:
            return ""
        if self.parse_path.startswith("http://") or self.parse_path.startswith("https://"):
            return self.parse_path
        return urljoin(self.service_root.rstrip("/") + "/", self.parse_path.lstrip("/"))

    @property
    def batch_result_path_template(self) -> str:
        return "/api/v4/extract-results/batch/{batch_id}"


@dataclass(slots=True)
class MinerUBlock:
    text: str
    page: int | None = None
    kind: str = "text"
    section: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MinerUParseResult:
    markdown: str = ""
    pages: list[tuple[int, str]] = field(default_factory=list)
    blocks: list[MinerUBlock] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class MinerUApiClient:
    def __init__(self, config: MinerUApiConfig) -> None:
        self.config = config

    def available(self) -> bool:
        return self.config.enabled and bool(self.config.parse_url)

    def parse_pdf(self, file_path: Path) -> MinerUParseResult:
        if not self.available():
            raise RuntimeError("MinerU API is not enabled.")
        if self.config.mode == "cloud_v4_batch":
            return self._parse_pdf_cloud_v4_batch(file_path)
        return self._parse_pdf_local_sync(file_path)

    def _parse_pdf_local_sync(self, file_path: Path) -> MinerUParseResult:
        headers = self._build_auth_headers()
        with httpx.Client(
            follow_redirects=True,
            timeout=self.config.timeout_seconds,
        ) as client:
            with file_path.open("rb") as handle:
                response = client.post(
                    self.config.parse_url,
                    headers=headers,
                    files=[("files", (file_path.name, handle, "application/pdf"))],
                )
            response.raise_for_status()

            payload = self._decode_response_payload(response)
            result = self._result_from_payload(payload, client, headers)
            if result.pages or result.blocks or result.markdown.strip():
                return result

        raise RuntimeError("MinerU returned no usable PDF content.")

    def _parse_pdf_cloud_v4_batch(self, file_path: Path) -> MinerUParseResult:
        headers = self._build_auth_headers()
        with httpx.Client(
            follow_redirects=True,
            timeout=self.config.timeout_seconds,
        ) as client:
            batch_payload = self._create_cloud_batch(client, headers, file_path)
            upload_url = self._extract_upload_url(batch_payload)
            batch_id = self._extract_batch_id(batch_payload)
            if not upload_url:
                raise RuntimeError("MinerU cloud batch creation returned no upload URL.")
            if not batch_id:
                raise RuntimeError("MinerU cloud batch creation returned no batch id.")

            self._upload_file_to_signed_url(client, upload_url, file_path)
            result_payload = self._poll_cloud_batch_result(client, headers, batch_id)
            result = self._result_from_payload(result_payload, client, headers)
            if result.pages or result.blocks or result.markdown.strip():
                return result
        raise RuntimeError("MinerU cloud batch finished without usable PDF content.")

    def _create_cloud_batch(
        self,
        client: httpx.Client,
        headers: dict[str, str],
        file_path: Path,
    ) -> dict[str, Any]:
        payload = {
            "files": [
                {
                    "name": file_path.name,
                    "is_ocr": False,
                    "data_id": self._build_data_id(file_path),
                }
            ],
            "enable_formula": True,
            "enable_table": True,
            "language": "ch",
        }
        response = client.post(self.config.parse_url, headers=headers, json=payload)
        response.raise_for_status()
        decoded = self._decode_response_payload(response)
        self._raise_api_error_if_present(decoded, fallback="MinerU cloud batch creation failed.")
        return decoded

    def _upload_file_to_signed_url(
        self,
        client: httpx.Client,
        upload_url: str,
        file_path: Path,
    ) -> None:
        with file_path.open("rb") as handle:
            response = client.put(
                upload_url,
                content=handle.read(),
            )
        response.raise_for_status()

    def _poll_cloud_batch_result(
        self,
        client: httpx.Client,
        headers: dict[str, str],
        batch_id: str,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + self.config.timeout_seconds
        result_url = urljoin(
            self.config.service_root.rstrip("/") + "/",
            self.config.batch_result_path_template.format(batch_id=batch_id).lstrip("/"),
        )
        last_payload: dict[str, Any] = {}

        while time.monotonic() < deadline:
            response = client.get(result_url, headers=headers)
            response.raise_for_status()
            payload = self._decode_response_payload(response)
            last_payload = payload
            self._raise_api_error_if_present(payload)

            state = self._extract_batch_state(payload)
            if state == "success":
                return payload
            if state == "failed":
                detail = self._find_first_string(
                    payload,
                    {"error", "message", "msg", "reason"},
                ) or "MinerU cloud batch failed."
                raise RuntimeError(detail)
            time.sleep(2)

        if last_payload:
            detail = self._find_first_string(last_payload, {"message", "msg", "error"})
            raise RuntimeError(detail or "MinerU cloud batch timed out while waiting for results.")
        raise RuntimeError("MinerU cloud batch timed out before any result payload was returned.")

    def _extract_batch_state(self, payload: dict[str, Any]) -> str:
        normalized = self._unwrap_payload(payload)
        files = normalized.get("files")
        if isinstance(files, list) and files:
            states: list[str] = []
            for item in files:
                if not isinstance(item, dict):
                    continue
                state = str(item.get("state", "") or item.get("status", "")).strip().lower()
                if state:
                    states.append(state)
                if self._find_first_string(item, {"full_zip_url", "zip_url", "result_zip_url", "download_url"}):
                    return "success"
            if states and all(state in {"file_success", "success", "completed", "done"} for state in states):
                return "success"
            if states and any(state in {"file_failed", "failed", "error"} for state in states):
                return "failed"
            return "pending"

        extract_result = normalized.get("extract_result")
        if isinstance(extract_result, list) and extract_result:
            states: list[str] = []
            for item in extract_result:
                if not isinstance(item, dict):
                    continue
                state = str(item.get("state", "")).strip().lower()
                if state:
                    states.append(state)
                if self._find_first_string(item, {"full_zip_url", "zip_url", "result_zip_url", "download_url"}):
                    return "success"
            if states and all(state in {"done", "success", "completed", "file_success"} for state in states):
                return "success"
            if states and any(state in {"failed", "error", "file_failed"} for state in states):
                return "failed"
            return "pending"

        status = str(normalized.get("status", "")).strip().lower()
        if status in {"success", "completed", "done"}:
            return "success"
        if status in {"failed", "error"}:
            return "failed"
        return "pending"

    def _extract_upload_url(self, payload: dict[str, Any]) -> str:
        direct = self._find_first_string(
            payload,
            {"file_url", "upload_url", "signed_url", "url"},
        )
        if direct:
            return direct
        for item in self._iter_structures(payload):
            if not isinstance(item, dict):
                continue
            values = item.get("file_urls")
            if isinstance(values, list):
                for value in values:
                    if isinstance(value, str) and value.strip():
                        return value.strip()
        return ""

    def _extract_batch_id(self, payload: dict[str, Any]) -> str:
        return self._find_first_string(
            payload,
            {"batch_id", "batchId"},
        )

    def _raise_api_error_if_present(self, payload: dict[str, Any], fallback: str | None = None) -> None:
        normalized = self._unwrap_payload(payload)
        status = str(normalized.get("status", "")).strip().lower()
        code = normalized.get("code")
        if status in {"failed", "error"}:
            detail = self._find_first_string(normalized, {"error", "message", "msg", "reason"})
            raise RuntimeError(detail or fallback or "MinerU API reported a failure.")
        if isinstance(code, int) and code not in {0, 200}:
            detail = self._find_first_string(normalized, {"error", "message", "msg", "reason"})
            raise RuntimeError(detail or fallback or f"MinerU API returned error code {code}.")

    def _build_auth_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers

    def _build_data_id(self, file_path: Path) -> str:
        digest = hashlib.md5(str(file_path.resolve()).encode("utf-8", errors="ignore")).hexdigest()
        return f"{file_path.stem[:32]}-{digest[:12]}"

    def _decode_response_payload(self, response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError:
            text = response.text.strip()
            return {"text": text} if text else {}
        if isinstance(payload, dict):
            return payload
        return {"data": payload}

    def _result_from_payload(
        self,
        payload: dict[str, Any],
        client: httpx.Client,
        headers: dict[str, str],
    ) -> MinerUParseResult:
        normalized = self._unwrap_payload(payload)
        direct = self._build_result_from_mapping(normalized)
        if direct.pages or direct.blocks or direct.markdown.strip():
            return direct

        zip_url = self._find_first_string(
            normalized,
            {
                "full_zip_url",
                "zip_url",
                "result_zip_url",
                "download_url",
                "zipDownloadUrl",
            },
        )
        if zip_url:
            return self._result_from_zip_url(zip_url, client, headers)
        return direct

    def _result_from_zip_url(
        self,
        zip_url: str,
        client: httpx.Client,
        headers: dict[str, str],
    ) -> MinerUParseResult:
        resolved_url = urljoin(self.config.service_root.rstrip("/") + "/", zip_url) if self.config.service_root else zip_url
        target_host = urlparse(resolved_url).netloc
        service_host = urlparse(self.config.service_root).netloc
        request_headers = headers if target_host == service_host else {}
        response = client.get(resolved_url, headers=request_headers)
        response.raise_for_status()
        return self._parse_zip_bundle(response.content)

    def _parse_zip_bundle(self, content: bytes) -> MinerUParseResult:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = sorted(archive.namelist())
            markdown = self._read_first_matching_text(archive, names, suffix=".md")
            content_payload = self._read_first_matching_json(
                archive,
                names,
                suffixes=("content_list.json", "layout_content.json", "middle.json"),
            )

        blocks = self._extract_blocks(content_payload)
        pages = self._group_blocks_to_pages(blocks)
        return MinerUParseResult(
            markdown=markdown,
            pages=pages,
            blocks=blocks,
            metadata={"source": "mineru_zip"},
        )

    def _build_result_from_mapping(self, payload: dict[str, Any]) -> MinerUParseResult:
        markdown = self._find_first_string(
            payload,
            {"md_content", "markdown", "text", "content"},
        )
        blocks = self._extract_blocks(payload)
        pages = self._extract_pages(payload)
        if not pages and blocks:
            pages = self._group_blocks_to_pages(blocks)
        return MinerUParseResult(
            markdown=markdown,
            pages=pages,
            blocks=blocks,
            metadata={"source": "mineru_api"},
        )

    def _extract_pages(self, payload: Any) -> list[tuple[int, str]]:
        candidates: list[tuple[int, str]] = []
        for item in self._iter_structures(payload):
            if not isinstance(item, dict):
                continue
            page = self._extract_page_number(item)
            if page is None:
                continue
            text = self._extract_text(item)
            if not text:
                continue
            candidates.append((page, text))

        deduped: dict[int, str] = {}
        for page, text in candidates:
            if page not in deduped or len(text) > len(deduped[page]):
                deduped[page] = text
        return sorted(deduped.items(), key=lambda item: item[0])

    def _extract_blocks(self, payload: Any) -> list[MinerUBlock]:
        blocks: list[MinerUBlock] = []
        seen: set[tuple[int | None, str, str]] = set()
        for item in self._iter_structures(payload):
            if not isinstance(item, dict):
                continue
            text = self._extract_text(item)
            if not text:
                continue
            page = self._extract_page_number(item)
            kind = self._extract_kind(item)
            section = self._extract_section(item)
            key = (page, kind, text[:240])
            if key in seen:
                continue
            seen.add(key)
            blocks.append(
                MinerUBlock(
                    text=text,
                    page=page,
                    kind=kind,
                    section=section,
                    metadata={
                        "parser": "mineru_api",
                        "block_type": kind,
                    },
                )
            )
        return blocks

    def _iter_structures(self, value: Any) -> list[Any]:
        items: list[Any] = []
        stack = [value]
        while stack:
            current = stack.pop()
            items.append(current)
            if isinstance(current, dict):
                stack.extend(reversed(list(current.values())))
            elif isinstance(current, list):
                stack.extend(reversed(current))
        return items

    def _unwrap_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        current: Any = payload
        while isinstance(current, dict):
            next_value = None
            for key in ("data", "result", "output", "payload"):
                candidate = current.get(key)
                if isinstance(candidate, dict):
                    next_value = candidate
                    break
            if next_value is None:
                return current
            current = next_value
        return payload

    def _find_first_string(self, payload: Any, target_keys: set[str]) -> str:
        for item in self._iter_structures(payload):
            if not isinstance(item, dict):
                continue
            for key, value in item.items():
                if key not in target_keys:
                    continue
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return ""

    def _extract_page_number(self, item: dict[str, Any]) -> int | None:
        for key in ("page_idx", "page_index", "page_id", "page_no", "page_num", "page"):
            value = item.get(key)
            if isinstance(value, int) and value >= 0:
                if key in {"page_idx", "page_index"}:
                    return value + 1
                return value if value > 0 else value + 1
            if isinstance(value, str) and value.strip().isdigit():
                page = int(value.strip())
                if key in {"page_idx", "page_index"}:
                    return page + 1
                return page if page > 0 else page + 1
        return None

    def _extract_kind(self, item: dict[str, Any]) -> str:
        for key in ("type", "category", "label", "block_type"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip().lower()
        return "text"

    def _extract_section(self, item: dict[str, Any]) -> str | None:
        for key in ("section", "title", "heading", "subtitle"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    def _extract_text(self, item: dict[str, Any]) -> str:
        parts: list[str] = []
        for key in ("text", "content", "markdown", "md", "caption", "latex", "html"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
        if not parts:
            for key in ("texts", "text_list", "lines"):
                value = item.get(key)
                if isinstance(value, list):
                    parts.extend(str(entry).strip() for entry in value if str(entry).strip())
        joined = "\n".join(part for part in parts if part)
        return joined.strip()

    def _group_blocks_to_pages(self, blocks: list[MinerUBlock]) -> list[tuple[int, str]]:
        grouped: dict[int, list[str]] = {}
        for block in blocks:
            if block.page is None:
                continue
            grouped.setdefault(block.page, []).append(block.text)
        pages = []
        for page, values in grouped.items():
            merged = "\n\n".join(value for value in values if value.strip()).strip()
            if merged:
                pages.append((page, merged))
        return sorted(pages, key=lambda item: item[0])

    def _read_first_matching_text(
        self,
        archive: zipfile.ZipFile,
        names: list[str],
        *,
        suffix: str,
    ) -> str:
        for name in names:
            if not name.lower().endswith(suffix.lower()):
                continue
            try:
                return archive.read(name).decode("utf-8", errors="replace").strip()
            except Exception:
                continue
        return ""

    def _read_first_matching_json(
        self,
        archive: zipfile.ZipFile,
        names: list[str],
        *,
        suffixes: tuple[str, ...],
    ) -> Any:
        normalized = tuple(item.lower() for item in suffixes)
        for name in names:
            lowered = name.lower()
            if not any(lowered.endswith(suffix) for suffix in normalized):
                continue
            try:
                return json.loads(archive.read(name).decode("utf-8", errors="replace"))
            except Exception:
                continue
        return {}


def build_default_mineru_client(settings: Settings | None = None) -> MinerUApiClient:
    active_settings = settings or get_settings()
    return MinerUApiClient(
        MinerUApiConfig(
            enabled=active_settings.mineru_api_enabled,
            mode=active_settings.mineru_api_mode,
            base_url=active_settings.mineru_api_base_url,
            parse_path=active_settings.mineru_api_parse_path,
            api_key=active_settings.mineru_api_key,
            timeout_seconds=active_settings.mineru_api_timeout_seconds,
        )
    )



