from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from structured_data.catalog import StructuredDataCatalog
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
    _stub_module("config", get_settings=lambda: types.SimpleNamespace(), runtime_config=types.SimpleNamespace(get_rag_mode=lambda: False))
    _stub_module("RAG", __path__=[])
    _stub_module("RAG.router", RAGQueryRouter=type("RAGQueryRouter", (), {}))
    _stub_module("graph", __path__=[])
    _stub_module("graph.memory_bridge", GraphMemoryBridge=type("GraphMemoryBridge", (), {}))
    _stub_module("graph.memory_indexer", memory_indexer=types.SimpleNamespace(rebuild_index=lambda: None))
    _stub_module("graph.prompt_builder", build_system_prompt=lambda *args, **kwargs: "")
    _stub_module("graph.session_manager", SessionManager=type("SessionManager", (), {}))
    _stub_module("pdf_analysis", PdfAnalysisCatalog=type("PdfAnalysisCatalog", (), {
        "resolve_pdf_path_from_history": staticmethod(lambda *args, **kwargs: None),
        "relative_path": staticmethod(lambda root, path: str(path)),
    }))
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

    spec = importlib.util.spec_from_file_location("agent_history_regression", ROOT / "graph" / "agent.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load graph/agent.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    assert StructuredDataCatalog.default_path_for_query("为我查找，谁是薪水最高的销售人员").endswith("employees.xlsx")

    agent_module = _load_agent_module()
    manager = agent_module.AgentManager()
    manager.base_dir = ROOT

    history = [
        {"role": "user", "content": "在数据库中为我查找缺货信息"},
        {"role": "assistant", "content": "数据源：knowledge/E-commerce Data/inventory.xlsx"},
    ]

    explicit_new_query = QueryUnderstanding(
        intent="structured_dataset_extreme_record",
        target_object="employee",
        tool_name="structured_data_analysis",
        tool_input={"query": "为我查找，谁是薪水最高的销售人员"},
    )
    explicit_input = manager._resolve_tool_input_from_history(
        explicit_new_query,
        "为我查找，谁是薪水最高的销售人员",
        history,
    )
    assert "path" not in explicit_input

    followup_query = QueryUnderstanding(
        intent="structured_followup_query",
        target_object=None,
        tool_name="structured_data_analysis",
        tool_input={"query": "谁最高"},
    )
    followup_input = manager._resolve_tool_input_from_history(
        followup_query,
        "谁最高",
        history,
    )
    assert followup_input.get("path", "").endswith("inventory.xlsx")

    print("ALL PASSED (structured follow-up history regression)")


if __name__ == "__main__":
    main()
