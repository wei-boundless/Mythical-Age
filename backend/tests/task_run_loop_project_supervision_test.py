from runtime.unit_runtime.loop import TaskRunLoop


def test_coordination_active_node_id_prefers_stage_id() -> None:
    assert TaskRunLoop._coordination_active_node_id({"active_stage_id": "world_design"}) == "world_design"


def test_coordination_active_node_id_falls_back_to_node_id() -> None:
    assert TaskRunLoop._coordination_active_node_id({"active_node_id": "world_review"}) == "world_review"
