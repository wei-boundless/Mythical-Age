from __future__ import annotations

import sys
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from capability_system.tools.native_tool_runtime import ToolRuntime


def main() -> None:
    runtime = ToolRuntime(ROOT)

    list_dir = runtime.get_instance("list_dir")
    assert list_dir is not None
    list_result = list_dir.invoke({"path": "docs", "max_entries": 5})
    assert "系统规划" in list_result or "设计原则" in list_result

    stat_path = runtime.get_instance("stat_path")
    assert stat_path is not None
    stat_result = stat_path.invoke({"path": "requirements.txt"})
    assert "exists: true" in stat_result
    assert "type: file" in stat_result

    path_exists = runtime.get_instance("path_exists")
    assert path_exists is not None
    assert path_exists.invoke({"path": "requirements.txt"}) == "true"
    assert path_exists.invoke({"path": "definitely_missing.file"}) == "false"

    glob_paths = runtime.get_instance("glob_paths")
    assert glob_paths is not None
    glob_result = glob_paths.invoke({"pattern": "docs/**/*.md", "max_results": 10})
    assert ".md" in glob_result

    structured_reader = runtime.get_instance("read_structured_file")
    assert structured_reader is not None
    structured_result = structured_reader.invoke({"path": "knowledge/E-commerce Data/faq.json"})
    assert "root_type: dict" in structured_result or "root_type: list" in structured_result

    text_metric = runtime.get_instance("text_metric")
    assert text_metric is not None
    metric_payload = json.loads(text_metric.invoke({"text": "天地玄黄 alpha beta", "measurement_mode": "text_units"}))
    assert metric_payload["text_units"] == 6
    assert metric_payload["cjk_chars"] == 4
    assert metric_payload["latin_words"] == 2

    git_status = runtime.get_instance("git_status")
    assert git_status is not None
    status_result = git_status.invoke({})
    assert status_result

    git_log = runtime.get_instance("git_log")
    assert git_log is not None
    log_result = git_log.invoke({"max_count": 3})
    assert log_result

    print("ALL PASSED (base toolset)")


if __name__ == "__main__":
    main()


