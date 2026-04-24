from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from query.tool_input_resolver import ToolInputResolver
from tools.definitions import get_tool_definition_map


def main() -> None:
    definitions = get_tool_definition_map()
    assert definitions["read_file"].resolution_contract.path_kind == "workspace"
    assert definitions["structured_data_analysis"].resolution_contract.path_kind == "dataset"
    assert definitions["pdf_analysis"].resolution_contract.path_kind == "pdf"

    resolver = ToolInputResolver(base_dir=ROOT)
    plan = SimpleNamespace(
        message="打开 backend/understanding/task_understanding.py 给我看看源码",
        query_understanding=SimpleNamespace(
            tool_name="read_file",
            tool_input={"path": "backend/understanding/task_understanding.py"},
        ),
        structured_binding=None,
    )
    resolved = resolver.resolve(plan=plan, history=[])
    assert resolved["path"] == "understanding/task_understanding.py"

    source = (ROOT / "query" / "tool_input_resolver.py").read_text(encoding="utf-8")
    assert 'understanding.tool_name == "pdf_analysis"' not in source
    assert 'understanding.tool_name == "structured_data_analysis"' not in source
    assert 'understanding.tool_name == "read_file"' not in source

    print("ALL PASSED (tool resolution contract)")


if __name__ == "__main__":
    main()
