from __future__ import annotations

import io
import json
import sys
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
            "text": "Page one summary.",
            "title": "Overview",
        },
        {
            "page_idx": 1,
            "type": "table",
            "text": "Quarter | Revenue\nQ1 | 120",
            "title": "Revenue Table",
        },
    ]

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("auto/report.md", "# Report\n\nStructured markdown output")
        archive.writestr(
            "auto/content_list.json",
            json.dumps(payload, ensure_ascii=False, indent=2),
        )
    return buffer.getvalue()


def main() -> None:
    client = MinerUApiClient(
        MinerUApiConfig(
            enabled=True,
            base_url="http://127.0.0.1:8000",
            parse_path="/file_parse",
            api_key=None,
            timeout_seconds=30,
        )
    )
    result = client._parse_zip_bundle(_build_sample_zip())

    assert result.markdown.startswith("# Report")
    assert result.pages[0][0] == 1
    assert "Page one summary." in result.pages[0][1]
    assert [block.page for block in result.blocks[:2]] == [1, 2]
    assert any(block.kind == "table" and block.page == 2 for block in result.blocks)
    assert any("Quarter | Revenue" in block.text for block in result.blocks)

    print("ALL PASSED (mineru zip parser regression)")


if __name__ == "__main__":
    main()
