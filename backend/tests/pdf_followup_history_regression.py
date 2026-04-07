from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from understanding.query_understanding import QueryUnderstanding


def _stub_module(name: str, **attrs) -> None:
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module


def _load_agent_module():
    _stub_module("langchain", __path__=[])
    _stub_module("langchain.agents", create_agent=lambda *args, **kwargs: None)
    _stub_module("langchain_openai", ChatOpenAI=type("ChatOpenAI", (), {}))
    _stub_module(
        "config",
        get_settings=lambda: types.SimpleNamespace(),
        runtime_config=types.SimpleNamespace(get_rag_mode=lambda: False),
    )
    _stub_module("RAG", __path__=[])
    _stub_module("RAG.router", RAGQueryRouter=type("RAGQueryRouter", (), {}))
    _stub_module("graph", __path__=[])
    _stub_module("graph.memory_bridge", GraphMemoryBridge=type("GraphMemoryBridge", (), {}))
    _stub_module("graph.memory_indexer", memory_indexer=types.SimpleNamespace(rebuild_index=lambda: None))
    _stub_module("graph.prompt_builder", build_system_prompt=lambda *args, **kwargs: "")
    _stub_module("graph.session_manager", SessionManager=type("SessionManager", (), {}))
    _stub_module(
        "pdf_analysis",
        PdfAnalysisCatalog=type(
            "PdfAnalysisCatalog",
            (),
            {
                "resolve_pdf_path_from_history": staticmethod(
                    lambda root_dir, history: root_dir / "knowledge" / "reports" / "AI治理报告.pdf"
                ),
                "relative_path": staticmethod(lambda root_dir, path: str(path.relative_to(root_dir)).replace("\\", "/")),
            },
        ),
    )
    _stub_module("skill_system", SkillDefinition=type("SkillDefinition", (), {}), SkillRegistry=type("SkillRegistry", (), {}))
    _stub_module(
        "structured_memory",
        ConsolidationConfig=type("ConsolidationConfig", (), {}),
        ConsolidationReport=type("ConsolidationReport", (), {}),
        ConsolidationScheduler=type("ConsolidationScheduler", (), {}),
    )
    _stub_module("tools", get_all_tools=lambda base_dir: [])
    _stub_module("tools.skills_scanner", refresh_snapshot=lambda base_dir: None)
    _stub_module("tools.tool_registry", ToolRegistry=type("ToolRegistry", (), {}), refresh_tool_registry=lambda base_dir: None)

    spec = importlib.util.spec_from_file_location("agent_pdf_followup_regression", ROOT / "graph" / "agent.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load graph/agent.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    agent_module = _load_agent_module()
    manager = agent_module.AgentManager()
    manager.base_dir = ROOT

    history = [
        {"role": "user", "content": "请帮我详细解读 AI治理报告.pdf"},
        {"role": "assistant", "content": "已分析文件：knowledge/reports/AI治理报告.pdf"},
    ]

    original = QueryUnderstanding(
        intent="knowledge_lookup_query",
        route="rag",
        modality="general",
        should_skip_rag=False,
    )
    promoted = manager._promote_contextual_pdf_query("第三页讲了什么？", history, original)

    assert promoted.route == "tool"
    assert promoted.intent == "pdf_page_followup_query"
    assert promoted.modality == "pdf"
    assert promoted.tool_name == "pdf_analysis"
    assert promoted.tool_input["mode"] == "page_read"
    assert promoted.tool_input["path"].endswith("AI治理报告.pdf")
    assert promoted.should_skip_rag is True

    print("ALL PASSED (pdf follow-up history regression)")


if __name__ == "__main__":
    main()
