from __future__ import annotations

from orchestration.coordination_recovery import _recovery_stage_business_acceptance
from runtime.coordination_runtime.review_gate_verdict import extract_explicit_review_verdict
from runtime.unit_runtime.quality_gates import _stage_business_acceptance


def _review_contract() -> dict[str, object]:
    return {"node_type": "review_gate", "review_gate_policy": {"is_review_gate": True}}


def test_chinese_review_conclusion_with_notes_accepts_runtime_and_breakpoint_recovery() -> None:
    content = """## 世界观审核报告
### 审核结论：通过，附条件建议
- 阻塞项：无
- 可进入下一节点：是
"""

    acceptance = _stage_business_acceptance(
        stage_id="world_review",
        contract=_review_contract(),
        explicit_inputs={},
        final_content=content,
        output_refs=["artifact:world_review"],
        terminal_status="completed",
        requires_file_artifact_refs=True,
    )
    recovery = _recovery_stage_business_acceptance(
        stage_id="world_review",
        contract=_review_contract(),
        explicit_inputs={},
        final_content=content,
        output_refs=["artifact:world_review"],
        terminal_status="completed",
    )

    assert extract_explicit_review_verdict(content) == "pass_with_notes"
    assert acceptance["accepted"] is True
    assert acceptance["business_accepted"] is True
    assert recovery["accepted"] is True


def test_chinese_review_rework_or_next_stage_no_rejects_runtime_and_breakpoint_recovery() -> None:
    content = """## 世界观审核报告
### 审核结果：返修
- 阻塞项：核心设定自相矛盾
- 可进入下一节点：否
"""

    acceptance = _stage_business_acceptance(
        stage_id="world_review",
        contract=_review_contract(),
        explicit_inputs={},
        final_content=content,
        output_refs=["artifact:world_review"],
        terminal_status="completed",
        requires_file_artifact_refs=True,
    )
    recovery = _recovery_stage_business_acceptance(
        stage_id="world_review",
        contract=_review_contract(),
        explicit_inputs={},
        final_content=content,
        output_refs=["artifact:world_review"],
        terminal_status="completed",
    )

    assert extract_explicit_review_verdict(content) == "revise"
    assert acceptance["accepted"] is False
    assert acceptance["business_accepted"] is False
    assert recovery["accepted"] is False


def test_conditional_pass_with_blockers_is_revise() -> None:
    content = """# 角色审核报告

审核结论：有条件通过。需完成指定修改后方可进入剧情大纲节点。

## 二、阻塞问题（必须修改，否则不能进入下一阶段）

### 阻塞-1：角色动机与世界观冲突

修改要求：完成阻塞问题后，角色设定候选可进入记忆提交节点冻结。
"""

    acceptance = _stage_business_acceptance(
        stage_id="character_review",
        contract=_review_contract(),
        explicit_inputs={},
        final_content=content,
        output_refs=["artifact:character_review"],
        terminal_status="completed",
        requires_file_artifact_refs=True,
    )
    recovery = _recovery_stage_business_acceptance(
        stage_id="character_review",
        contract=_review_contract(),
        explicit_inputs={},
        final_content=content,
        output_refs=["artifact:character_review"],
        terminal_status="completed",
    )

    assert extract_explicit_review_verdict(content) == "revise"
    assert acceptance["accepted"] is False
    assert acceptance["business_accepted"] is False
    assert recovery["accepted"] is False


def test_review_table_header_does_not_turn_passed_review_into_revise() -> None:
    content = """# 世界观审核报告（第二轮）

审核结论：✅ 通过

## 一、阻塞问题检查

| 阻塞项 | 状态 |
|---|---|
| 五域被写成世界中心 | ✅ 已修正 |

阻塞问题：零。

## 五、审核结论

裁决：通过，允许进入下一阶段。
"""

    acceptance = _stage_business_acceptance(
        stage_id="world_review",
        contract=_review_contract(),
        explicit_inputs={},
        final_content=content,
        output_refs=["artifact:world_review"],
        terminal_status="completed",
        requires_file_artifact_refs=True,
    )
    recovery = _recovery_stage_business_acceptance(
        stage_id="world_review",
        contract=_review_contract(),
        explicit_inputs={},
        final_content=content,
        output_refs=["artifact:world_review"],
        terminal_status="completed",
    )

    assert extract_explicit_review_verdict(content) == "pass"
    assert acceptance["accepted"] is True
    assert acceptance["business_accepted"] is True
    assert recovery["accepted"] is True
