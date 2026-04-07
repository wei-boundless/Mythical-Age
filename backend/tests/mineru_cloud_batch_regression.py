from __future__ import annotations

import io
import json
import sys
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pdf_analysis.mineru_client import MinerUApiClient, MinerUApiConfig


def _build_sample_zip() -> bytes:
    payload = [
        {
            "page_idx": 0,
            "type": "text",
            "text": "Page one summary from the official cloud flow.",
            "title": "Overview",
        }
    ]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("result/report.md", "# Report\n\nCloud markdown output")
        archive.writestr(
            "result/content_list.json",
            json.dumps(payload, ensure_ascii=False, indent=2),
        )
    return buffer.getvalue()


class FakeResponse:
    def __init__(self, *, payload=None, content: bytes = b"") -> None:
        self._payload = payload
        self.content = content

    def raise_for_status(self) -> None:
        return None

    def json(self):
        if self._payload is None:
            raise ValueError("no json payload")
        return self._payload


class FakeClient:
    calls: list[tuple[str, str, object]] = []
    poll_count = 0

    def __init__(self, *args, **kwargs) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def post(self, url, headers=None, json=None, files=None):
        FakeClient.calls.append(("POST", url, json if json is not None else files))
        return FakeResponse(
            payload={
                "batch_id": "batch-123",
                "file_urls": ["https://upload.example.com/sample.pdf"],
            }
        )

    def put(self, url, headers=None, content=None):
        FakeClient.calls.append(("PUT", url, headers))
        return FakeResponse(payload={})

    def get(self, url, headers=None):
        FakeClient.calls.append(("GET", url, headers))
        if "extract-results" in url:
            FakeClient.poll_count += 1
            if FakeClient.poll_count == 1:
                return FakeResponse(
                    payload={
                        "batch_id": "batch-123",
                        "extract_result": [{"state": "waiting-file"}],
                    }
                )
            return FakeResponse(
                payload={
                    "batch_id": "batch-123",
                    "extract_result": [
                        {
                            "state": "done",
                            "full_zip_url": "https://download.example.com/result.zip",
                        }
                    ],
                }
            )
        return FakeResponse(content=_build_sample_zip())


def main() -> None:
    import pdf_analysis.mineru_client as module

    original_client = module.httpx.Client
    original_sleep = module.time.sleep
    module.httpx.Client = FakeClient
    module.time.sleep = lambda seconds: None
    try:
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "sample.pdf"
            pdf.write_bytes(b"%PDF-1.4\n")
            client = MinerUApiClient(
                MinerUApiConfig(
                    enabled=True,
                    mode="cloud_v4_batch",
                    base_url="https://mineru.net",
                    parse_path="/api/v4/file-urls/batch",
                    api_key="token",
                    timeout_seconds=30,
                )
            )
            result = client.parse_pdf(pdf)

        assert result.markdown.startswith("# Report")
        assert result.pages == [(1, "Page one summary from the official cloud flow.")]
        assert FakeClient.calls[0][0] == "POST"
        assert FakeClient.calls[0][1] == "https://mineru.net/api/v4/file-urls/batch"
        assert FakeClient.calls[1][0] == "PUT"
        assert FakeClient.calls[1][1] == "https://upload.example.com/sample.pdf"
        assert FakeClient.calls[1][2] in (None, {})
        assert any(
            method == "GET" and "extract-results/batch/batch-123" in url
            for method, url, _ in FakeClient.calls
        )
        assert any(
            method == "GET" and "download.example.com/result.zip" in url
            for method, url, _ in FakeClient.calls
        )
    finally:
        module.httpx.Client = original_client
        module.time.sleep = original_sleep

    print("ALL PASSED (mineru cloud batch regression)")


if __name__ == "__main__":
    main()
