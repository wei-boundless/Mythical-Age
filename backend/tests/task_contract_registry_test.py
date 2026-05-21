from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import HTTPException

from api import task_system as tasks_api
from task_system import ContractSpec, TaskContractRegistry
from tests.support.runtime_stubs import RuntimeBaseDirStub


_RuntimeStub = RuntimeBaseDirStub


def test_contract_registry_loads_generic_default_specs_with_chinese_titles(tmp_path: Path) -> None:
    registry = TaskContractRegistry(tmp_path)

    specs = registry.list_contract_specs()
    spec_ids = {item.contract_id for item in specs}

    assert "contract.user_request.basic" in spec_ids
    assert "contract.agent_output.markdown" in spec_ids
    assert all(item.title_zh for item in specs)
    assert all("Novel" not in item.contract_id for item in specs)
    assert all("LightWebGame" not in item.contract_id for item in specs)
    assert registry.validate_all() == []


def test_contract_registry_upsert_persists_contract_spec(tmp_path: Path) -> None:
    registry = TaskContractRegistry(tmp_path)

    registry.upsert_contract_spec(
        {
            "contract_id": "contract.test.research_brief",
            "title_zh": "研究简报",
            "title_en": "Research Brief",
            "contract_kind": "workflow",
            "description": "用于测试的研究简报契约。",
            "output_fields": [
                {
                    "field_id": "brief_markdown",
                    "title_zh": "简报正文",
                    "field_type": "string",
                    "required": True,
                    "source_hint": "upstream_output",
                    "visibility": "model_visible",
                }
            ],
            "acceptance_rules": [
                {
                    "rule_id": "brief_present",
                    "title_zh": "简报必须存在",
                    "rule_type": "required_field_present",
                    "severity": "error",
                    "target_field": "brief_markdown",
                    "criteria": "简报正文不能为空。",
                }
            ],
        }
    )

    persisted = TaskContractRegistry(tmp_path).get_contract_spec("contract.test.research_brief")

    assert isinstance(persisted, ContractSpec)
    assert persisted.title_zh == "研究简报"
    assert persisted.output_fields[0].field_id == "brief_markdown"
    assert persisted.acceptance_rules[0].rule_id == "brief_present"


def test_contract_registry_rejects_invalid_contract_kind_and_missing_chinese_title(tmp_path: Path) -> None:
    registry = TaskContractRegistry(tmp_path)

    with pytest.raises(ValueError) as exc:
        registry.upsert_contract_spec(
            {
                "contract_id": "contract.test.invalid",
                "title_zh": "",
                "contract_kind": "obsolete_specific_contract",
            }
        )

    message = str(exc.value)
    assert "中文名称" in message
    assert "允许范围" in message


def test_task_system_overview_exposes_contract_management_catalog(tmp_path: Path) -> None:
    original = tasks_api.require_runtime
    tasks_api.require_runtime = lambda: _RuntimeStub(tmp_path)  # type: ignore[assignment]
    try:
        payload = asyncio.run(tasks_api.task_system_overview())
    finally:
        tasks_api.require_runtime = original  # type: ignore[assignment]

    contract_management = payload["contract_management"]

    assert payload["summary"]["contract_spec_count"] >= 5
    assert contract_management["authority"] == "task_system.contract_management"
    assert contract_management["contract_specs"]
    assert "workflow" in contract_management["contract_kind_options"]
    assert "string" in contract_management["field_type_options"]
    assert contract_management["validation_issues"] == []


def test_task_system_contract_upsert_and_delete_use_editable_storage(tmp_path: Path) -> None:
    original = tasks_api.require_runtime
    tasks_api.require_runtime = lambda: _RuntimeStub(tmp_path)  # type: ignore[assignment]
    try:
        upserted = asyncio.run(
            tasks_api.upsert_task_system_contract(
                "contract.test.node_result",
                tasks_api.ContractSpecUpsertRequest(
                    contract_id="contract.test.node_result",
                    title_zh="节点结果",
                    title_en="Node Result",
                    contract_kind="node_execution",
                    output_fields=[
                        {
                            "field_id": "node_result",
                            "title_zh": "节点结果",
                            "field_type": "object",
                            "required": True,
                            "source_hint": "upstream_output",
                            "visibility": "model_visible",
                        }
                    ],
                ),
            )
        )
        deleted = asyncio.run(tasks_api.delete_task_system_contract("contract.test.node_result"))
    finally:
        tasks_api.require_runtime = original  # type: ignore[assignment]

    assert any(
        item["contract_id"] == "contract.test.node_result"
        for item in upserted["contract_management"]["contract_specs"]
    )
    assert deleted["last_deletion"] == {"contract_id": "contract.test.node_result", "deleted": True}
    assert all(
        item["contract_id"] != "contract.test.node_result"
        for item in deleted["contract_management"]["contract_specs"]
    )


def test_task_system_contract_upsert_returns_http_400_for_invalid_spec(tmp_path: Path) -> None:
    original = tasks_api.require_runtime
    tasks_api.require_runtime = lambda: _RuntimeStub(tmp_path)  # type: ignore[assignment]
    try:
        with pytest.raises(HTTPException) as exc:
            asyncio.run(
                tasks_api.upsert_task_system_contract(
                    "contract.test.invalid",
                    tasks_api.ContractSpecUpsertRequest(
                        contract_id="contract.test.invalid",
                        title_zh="无效契约",
                        contract_kind="obsolete_specific_contract",
                    ),
                )
            )
    finally:
        tasks_api.require_runtime = original  # type: ignore[assignment]

    assert exc.value.status_code == 400
