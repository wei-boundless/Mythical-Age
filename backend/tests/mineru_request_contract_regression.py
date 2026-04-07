from __future__ import annotations

import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pdf_analysis.mineru_client import MinerUApiClient, MinerUApiConfig


class FakeResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {
            "markdown": "ok",
            "content_list": [
                {
                    "page_idx": 0,
                    "type": "text",
                    "text": "hello",
                }
            ],
        }


class FakeClient:
    last_files = None
    last_headers = None
    last_url = None

    def __init__(self, *args, **kwargs) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def post(self, url, headers=None, files=None):
        FakeClient.last_url = url
        FakeClient.last_headers = headers
        FakeClient.last_files = files
        return FakeResponse()


def main() -> None:
    import pdf_analysis.mineru_client as module

    original_client = module.httpx.Client
    module.httpx.Client = FakeClient
    try:
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "sample.pdf"
            pdf.write_bytes(b"%PDF-1.4\n")
            client = MinerUApiClient(
                MinerUApiConfig(
                    enabled=True,
                    base_url="http://127.0.0.1:8000",
                    parse_path="/file_parse",
                    api_key="token",
                    timeout_seconds=30,
                )
            )
            result = client.parse_pdf(pdf)

        assert result.pages == [(1, "hello")]
        assert isinstance(FakeClient.last_files, list)
        assert FakeClient.last_files[0][0] == "files"
        assert FakeClient.last_headers["Authorization"].startswith("Bearer ")
    finally:
        module.httpx.Client = original_client

    print("ALL PASSED (mineru request contract regression)")


if __name__ == "__main__":
    main()
