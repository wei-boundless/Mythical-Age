from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCANNER_PATH = ROOT / "capability_system" / "skill_scanner.py"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from capability_system.paths import CapabilitySystemPaths
from capability_system.skill_contracts import SkillPromptContract
from capability_system.skill_registry import SkillRegistry


def load_scanner_module():
    spec = importlib.util.spec_from_file_location("skills_scanner_test", SCANNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load skills_scanner.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    capability_paths = CapabilitySystemPaths.from_base_dir(ROOT)
    scanner = load_scanner_module()
    scanner.refresh_snapshot(ROOT)

    skills = scanner.scan_skills(ROOT)
    by_name = {skill.name: skill for skill in skills}

    assert "structured-data-analysis" in by_name
    structured = by_name["structured-data-analysis"]
    assert structured.title == "结构化数据分析"
    assert structured.preferred_route == "structured_data"
    assert "dataset_analysis" in structured.capability_tags
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
    assert "knowledge_lookup" in rag.capability_tags
    assert "faq_explanation" in rag.supported_task_kinds

    assert "skill-creator" in by_name
    creator = by_name["skill-creator"]
    assert creator.title == "Skill 创建顾问"
    assert creator.preferred_route == "capability_authoring"
    assert creator.requires_operations == ["op.read_file", "op.write_file", "op.edit_file"]
    assert creator.requires_capabilities == ["tool:read_file", "tool:write_file", "tool:edit_file"]
    assert "skill-authoring" in creator.capability_tags
    assert "skill_create" in creator.supported_task_kinds
    assert "skill_update" in creator.supported_task_kinds
    assert "capability_system" in creator.supported_source_kinds

    registry = json.loads(capability_paths.skills_registry_path.read_text(encoding="utf-8"))
    assert registry["version"] == 3
    assert registry["skill_count"] == len(skills)
    assert all(item["schema_version"] == 3 for item in registry["skills"])
    assert all("runtime" in item and "prompt" in item for item in registry["skills"])
    assert all(item["validation_errors"] == [] for item in registry["skills"])

    prompt = SkillPromptContract(
        name="rag-skill",
        title="知识库问答",
        capability="面向本地知识库",
        use_when="Use for local knowledge-base lookup.",
        delegation_protocol="delegate evidence_lookup with scope.",
        return_protocol="return summary and evidence refs.",
    )
    rendered = prompt.render_block()
    assert "Delegation Protocol:" in rendered
    assert "Return Protocol:" in rendered

    skill_registry = SkillRegistry(ROOT)
    assert skill_registry.get_by_name("skill-creator") is not None

    snapshot_text = capability_paths.skills_snapshot_path.read_text(encoding="utf-8")
    assert "Skill registry snapshot for admin display" in snapshot_text
    assert "Available local capabilities" not in snapshot_text
    assert "When the main agent delegates" not in snapshot_text
    assert "When the main agent delegates, ask for evidence_lookup" not in snapshot_text
    assert "delegation_kind=evidence_lookup" in snapshot_text
    assert "<use_when>" in snapshot_text
    assert "<delegation_protocol>" in snapshot_text
    assert "<return_protocol>" in snapshot_text
    assert "<output_rule>" in snapshot_text
    assert "<allowed_tools>" not in snapshot_text
    assert "<preferred_route>" not in snapshot_text
    assert "<route_authority>" not in snapshot_text
    assert 'path="' not in snapshot_text

    print(f"ALL PASSED ({len(skills)} skills)")


if __name__ == "__main__":
    main()
