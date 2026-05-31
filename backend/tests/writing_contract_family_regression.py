from __future__ import annotations

import asyncio
from pathlib import Path

from api import task_system as tasks_api
from task_system import TaskContractRegistry, list_writing_contract_families, resolve_writing_contract
from tests.support.runtime_stubs import RuntimeBaseDirStub


def test_writing_contract_families_are_small_reusable_catalog() -> None:
    families = list_writing_contract_families()
    family_ids = {item.family_id for item in families}

    assert family_ids == {
        "writing.draft_artifact",
        "writing.review_verdict",
        "writing.revision_request",
        "writing.commit_receipt",
        "writing.memory_update",
    }
    assert all(item.configurable_fields for item in families)
    assert "writing.draft_to_review" in next(item for item in families if item.family_id == "writing.draft_artifact").relation_ids


def test_writing_draft_contract_shape_is_reused_by_artifact_type() -> None:
    chapter = resolve_writing_contract(
        "writing.draft_artifact",
        {"artifact_type": "chapter_draft", "writing_stage": "章节"},
    )
    world = resolve_writing_contract(
        "writing.draft_artifact",
        {"artifact_type": "world_setting", "writing_stage": "世界观"},
    )

    assert chapter.contract_id == "contract.writing.draft_artifact.chapter_draft"
    assert world.contract_id == "contract.writing.draft_artifact.world_setting"
    assert [field.field_id for field in chapter.output_fields] == [field.field_id for field in world.output_fields]
    assert chapter.metadata["contract_family_id"] == "writing.draft_artifact"
    assert world.metadata["generated_from_family"] is True
    assert chapter.artifact_requirements[0].artifact_type == "chapter_draft"
    assert world.artifact_requirements[0].artifact_type == "world_setting"


def test_writing_review_and_memory_contracts_encode_verdict_and_commit_protocol() -> None:
    review = resolve_writing_contract(
        "writing.review_verdict",
        {"artifact_type": "chapter_draft", "writing_stage": "章节", "verdict_key": "review_verdict"},
    )
    memory = resolve_writing_contract(
        "writing.memory_update",
        {"artifact_type": "world_memory", "writing_stage": "世界观"},
    )

    assert review.contract_kind == "acceptance"
    assert any(field.field_id == "review_verdict" and field.required for field in review.output_fields)
    assert any(field.field_id == "revision_request" for field in review.output_fields)
    assert review.metadata["verdict_key"] == "review_verdict"
    assert memory.metadata["contract_family_id"] == "writing.memory_update"
    assert any(field.field_id == "memory_candidate_ref" for field in memory.output_fields)
    assert any(rule.rule_id == "memory_candidate_present" for rule in memory.acceptance_rules)


def test_contract_management_catalog_exposes_writing_contract_families(tmp_path: Path) -> None:
    catalog = TaskContractRegistry(tmp_path).build_catalog()

    assert catalog["contract_families"]
    assert catalog["contract_family_catalog"]["authority"] == "task_system.writing_contract_families"
    assert catalog["summary"]["writing_contract_family_count"] == 5


def test_task_system_overview_exposes_contract_families(tmp_path: Path) -> None:
    original = tasks_api.require_runtime
    tasks_api.require_runtime = lambda: RuntimeBaseDirStub(tmp_path)  # type: ignore[assignment]
    try:
        payload = asyncio.run(tasks_api.task_system_overview())
    finally:
        tasks_api.require_runtime = original  # type: ignore[assignment]

    contract_management = payload["contract_management"]

    assert contract_management["summary"]["writing_contract_family_count"] == 5
    assert any(item["family_id"] == "writing.review_verdict" for item in contract_management["contract_families"])
