from __future__ import annotations

import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from capability_system.tools.tool_units.python_ast_tools import (  # noqa: E402
    PythonCodeOutlineTool,
    PythonParseCheckTool,
    PythonSymbolSearchTool,
)


def test_python_ast_tools_outline_parse_and_symbol_search() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        package = root / "pkg"
        package.mkdir()
        source = package / "sample.py"
        source.write_text(
            "\n".join(
                [
                    "import os",
                    "VALUE = 1",
                    "",
                    "class Greeter:",
                    "    def hello(self, name: str) -> str:",
                    "        return f'hello {name}'",
                    "",
                    "async def build_message() -> str:",
                    "    return 'ready'",
                ]
            ),
            encoding="utf-8",
        )
        broken = package / "broken.py"
        broken.write_text("def broken(:\n    pass\n", encoding="utf-8")

        outline = PythonCodeOutlineTool(root_dir=root)._run("pkg/sample.py")
        assert "Python outline: pkg/sample.py" in str(outline)
        symbols = outline["structured_payload"]["tool_result"]["symbols"]
        qualnames = {item["qualname"] for item in symbols}
        assert {"Greeter", "Greeter.hello", "build_message", "VALUE"}.issubset(qualnames)

        parse_ok = PythonParseCheckTool(root_dir=root)._run("pkg/sample.py")
        assert parse_ok["structured_payload"]["tool_result"]["valid"] is True

        parse_bad = PythonParseCheckTool(root_dir=root)._run("pkg/broken.py")
        assert parse_bad["structured_payload"]["tool_result"]["ok"] is False
        assert "Python syntax error" in str(parse_bad)

        search = PythonSymbolSearchTool(root_dir=root)._run("hello", roots=["pkg"])
        assert "Greeter.hello" in str(search)
        assert search["structured_payload"]["tool_result"]["result_count"] == 1


if __name__ == "__main__":
    test_python_ast_tools_outline_parse_and_symbol_search()
