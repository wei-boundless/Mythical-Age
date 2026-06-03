from __future__ import annotations

from task_system.storage import TaskSystemStorage

from tests.support.writing_fixtures import load_writing_modular_config_module


def test_writing_config_publish_cleanup_preserves_historical_config_snapshots(tmp_path) -> None:
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    storage = TaskSystemStorage(backend_dir)
    module = load_writing_modular_config_module()

    old_writing_config_id = "ghcfg:graph_writing_modular_novel_master:old"
    other_config_id = "ghcfg:graph.other:stable"
    storage.write_object(
        "graph_harness_configs.json",
        {
            "configs": [
                {
                    "config_id": old_writing_config_id,
                    "graph_id": module.MASTER_GRAPH_ID,
                    "metadata": {"managed_by": module.MANAGED_BY},
                },
                {
                    "config_id": other_config_id,
                    "graph_id": "graph.other",
                    "metadata": {"managed_by": "external"},
                },
            ],
            "published_bindings": {
                module.MASTER_GRAPH_ID: old_writing_config_id,
                "graph.other": other_config_id,
            },
        },
    )

    module._delete_managed_graph_runtime_records(backend_dir)

    payload = storage.read_object("graph_harness_configs.json", {"configs": [], "published_bindings": {}})
    config_ids = {str(item.get("config_id") or "") for item in payload["configs"]}
    assert old_writing_config_id in config_ids
    assert other_config_id in config_ids
    assert module.MASTER_GRAPH_ID not in payload["published_bindings"]
    assert payload["published_bindings"]["graph.other"] == other_config_id
