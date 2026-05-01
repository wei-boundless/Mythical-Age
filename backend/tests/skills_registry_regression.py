from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCANNER_PATH = ROOT / "tools" / "skills_scanner.py"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from skill_system import SkillRegistry


def load_scanner_module():
    spec = importlib.util.spec_from_file_location("skills_scanner_test", SCANNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load skills_scanner.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    scanner = load_scanner_module()
    scanner.refresh_snapshot(ROOT)

    skills = scanner.scan_skills(ROOT)
    by_name = {skill.name: skill for skill in skills}

    assert "get-weather" not in by_name

    assert "structured-data-analysis" in by_name
    structured = by_name["structured-data-analysis"]
    assert structured.title == "结构化数据分析"
    assert structured.preferred_route == "tool"
    assert structured.allowed_tools == ["structured_data_analysis"]
    assert "dataset_filter" in structured.supported_task_kinds
    assert "dataset" in structured.supported_source_kinds
    assert structured.context_mode == "isolated"
    assert structured.route_authority == "candidate_only"
    assert any(path.endswith("references/excel_reading.md") for path in structured.reference_paths)

    assert "pdf-analysis" in by_name
    pdf = by_name["pdf-analysis"]
    assert "document_page" in pdf.supported_task_kinds
    assert "document_read" in pdf.supported_task_kinds
    assert pdf.context_mode == "isolated"
    assert pdf.activation_policy == "model_visible"
    assert any(path.endswith("references/pdf_reading.md") for path in pdf.reference_paths)

    assert "rag-skill" in by_name
    rag = by_name["rag-skill"]
    assert rag.title == "知识库问答"
    assert rag.preferred_route == "rag"
    assert rag.allowed_tools == ["search_knowledge"]
    assert "faq_explanation" in rag.supported_task_kinds

    assert "gold-price" not in by_name

    registry = json.loads((ROOT / "SKILLS_REGISTRY.json").read_text(encoding="utf-8"))
    assert registry["version"] == 3
    assert registry["skill_count"] == len(skills)
    assert all(item["schema_version"] == 3 for item in registry["skills"])
    assert all("runtime" in item and "prompt" in item for item in registry["skills"])
    assert all(item["validation_errors"] == [] for item in registry["skills"])

    skill_registry = SkillRegistry(ROOT)
    assert skill_registry.get_by_name("get-weather") is None
    assert skill_registry.get_by_name("gold-price") is None

    snapshot_text = (ROOT / "SKILLS_SNAPSHOT.md").read_text(encoding="utf-8")
    assert "Skill registry snapshot for admin display" in snapshot_text
    assert "Available local capabilities" not in snapshot_text
    assert "<use_when>" in snapshot_text
    assert "<output_rule>" in snapshot_text
    assert "<allowed_tools>" not in snapshot_text
    assert "<preferred_route>" not in snapshot_text
    assert "<route_authority>" not in snapshot_text
    assert 'path="' not in snapshot_text

    print(f"ALL PASSED ({len(skills)} skills)")


if __name__ == "__main__":
    main()
