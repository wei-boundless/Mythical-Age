from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from harness.graph.model_overrides import (
    merge_effective_runtime_overrides,
    sanitize_runtime_overrides,
    work_order_with_model_overrides,
)
from harness.graph.models import GraphHarnessConfig, GraphNodeWorkOrder


def _config() -> GraphHarnessConfig:
    return GraphHarnessConfig(
        config_id="ghcfg:test",
        graph_id="graph.test.model_overrides",
        graph_title="Model Overrides",
        publish_version="test",
        content_hash="hash:test",
        nodes=(
            {
                "node_id": "module.chapter::chapter_draft",
                "node_type": "agent",
                "task_id": "task.test.chapter_draft",
                "agent_id": "agent:writer",
            },
            {
                "node_id": "module.chapter::chapter_review",
                "node_type": "review_gate",
                "task_id": "task.test.chapter_review",
                "agent_id": "agent:reviewer",
            },
        ),
    )


def _work_order(node_id: str, *, agent_id: str = "agent:writer") -> GraphNodeWorkOrder:
    return GraphNodeWorkOrder(
        work_order_id=f"wo:{node_id}",
        work_kind="agent",
        graph_run_id="grun:test",
        task_run_id="gtask:test",
        node_id=node_id,
        config_id="ghcfg:test",
        config_hash="hash:test",
        task_ref="task.test.chapter_draft",
        agent_id=agent_id,
        graph_slot={
            "authority": "harness.graph.node_execution_slot",
            "node_contract": {
                "model_requirement": {
                    "provider": "deepseek",
                    "model": "deepseek-v4-flash",
                    "credential_ref": "env:DEEPSEEK_WRITING_API_KEY",
                }
            },
        },
    )


def test_model_override_matches_bare_node_id_and_beats_role_group() -> None:
    order, diagnostics = work_order_with_model_overrides(
        graph_config=_config(),
        work_order=_work_order("module.chapter::chapter_draft"),
        runtime_overrides={
            "model_overrides": {
                "role_groups": {
                    "writing": {"provider": "deepseek", "model": "deepseek-v4-flash"}
                },
                "nodes": {
                    "chapter_draft": {
                        "provider": "deepseek",
                        "model": "deepseek-v4-pro",
                        "credential_ref": "env:DEEPSEEK_WRITING_API_KEY",
                    }
                },
            }
        },
    )

    requirement = order.graph_slot["node_contract"]["model_requirement"]
    assert requirement["model"] == "deepseek-v4-pro"
    assert order.input_package["runtime_profile"]["model_requirement"]["model"] == "deepseek-v4-pro"
    assert diagnostics["matched_scope"] == "node_id"
    assert diagnostics["matched_key"] == "chapter_draft"


def test_writing_role_group_does_not_override_review_node() -> None:
    order, diagnostics = work_order_with_model_overrides(
        graph_config=_config(),
        work_order=_work_order("module.chapter::chapter_review", agent_id="agent:reviewer"),
        runtime_overrides={
            "model_overrides": {
                "role_groups": {
                    "writing": {"provider": "deepseek", "model": "deepseek-v4-pro"}
                }
            }
        },
    )

    assert order.graph_slot["node_contract"]["model_requirement"]["model"] == "deepseek-v4-flash"
    assert diagnostics == {}


def test_runtime_overrides_reject_raw_secret_keys() -> None:
    with pytest.raises(ValueError, match="credential_ref"):
        sanitize_runtime_overrides(
            {
                "model_overrides": {
                    "role_groups": {
                        "writing": {
                            "provider": "deepseek",
                            "model": "deepseek-v4-pro",
                            "api_key": "sk-raw-secret",
                        }
                    }
                }
            }
        )


def test_runtime_overrides_allow_output_token_limits() -> None:
    payload = sanitize_runtime_overrides(
        {
            "model_overrides": {
                "role_groups": {
                    "writing": {
                        "provider": "deepseek",
                        "model": "deepseek-v4-pro",
                        "credential_ref": "env:DEEPSEEK_WRITING_API_KEY",
                        "preferred_output_tokens": 65536,
                        "max_output_tokens": 65536,
                    }
                }
            }
        }
    )

    assert payload["model_overrides"]["role_groups"]["writing"]["max_output_tokens"] == 65536
    assert payload["model_overrides"]["role_groups"]["writing"]["preferred_output_tokens"] == 65536


def test_temporary_runtime_override_beats_persistent_runtime_settings() -> None:
    effective = merge_effective_runtime_overrides(
        persistent={
            "model_overrides": {
                "role_groups": {
                    "writing": {"provider": "deepseek", "model": "deepseek-v4-flash"}
                }
            }
        },
        temporary={
            "model_overrides": {
                "role_groups": {
                    "writing": {"provider": "deepseek", "model": "deepseek-v4-pro"}
                }
            }
        },
    )

    assert effective["model_overrides"]["role_groups"]["writing"]["model"] == "deepseek-v4-pro"
