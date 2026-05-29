from __future__ import annotations

from task_system.runtime_semantics.quality_gates import stage_business_acceptance
from task_system.runtime_semantics.review_gate_verdict import extract_explicit_review_verdict


def _review_contract() -> dict[str, object]:
    return {"node_type": "review_gate", "review_gate_policy": {"is_review_gate": True}}


def test_chinese_review_conclusion_with_notes_accepts_runtime_and_breakpoint_recovery() -> None:
    content = """## 世界观审核报告
### 审核结论：通过，附条件建议
- 阻塞项：无
- 可进入下一节点：是
"""

    acceptance = stage_business_acceptance(
        stage_id="world_review",
        contract=_review_contract(),
        explicit_inputs={},
        final_content=content,
        output_refs=["artifact:world_review"],
        terminal_status="completed",
        requires_file_artifact_refs=True,
    )
    assert extract_explicit_review_verdict(content) == "pass_with_notes"
    assert acceptance["accepted"] is True
    assert acceptance["business_accepted"] is True


def test_chinese_review_rework_or_next_stage_no_rejects_runtime_and_breakpoint_recovery() -> None:
    content = """## 世界观审核报告
### 审核结果：返修
- 阻塞项：核心设定自相矛盾
- 可进入下一节点：否
"""

    acceptance = stage_business_acceptance(
        stage_id="world_review",
        contract=_review_contract(),
        explicit_inputs={},
        final_content=content,
        output_refs=["artifact:world_review"],
        terminal_status="completed",
        requires_file_artifact_refs=True,
    )
    assert extract_explicit_review_verdict(content) == "revise"
    assert acceptance["accepted"] is False
    assert acceptance["business_accepted"] is False


def test_conditional_pass_with_blockers_is_revise() -> None:
    content = """# 角色审核报告

审核结论：有条件通过。需完成指定修改后方可进入剧情大纲节点。

## 二、阻塞问题（必须修改，否则不能进入下一阶段）

### 阻塞-1：角色动机与世界观冲突

修改要求：完成阻塞问题后，角色设定候选可进入记忆提交节点冻结。
"""

    acceptance = stage_business_acceptance(
        stage_id="character_review",
        contract=_review_contract(),
        explicit_inputs={},
        final_content=content,
        output_refs=["artifact:character_review"],
        terminal_status="completed",
        requires_file_artifact_refs=True,
    )
    assert extract_explicit_review_verdict(content) == "revise"
    assert acceptance["accepted"] is False
    assert acceptance["business_accepted"] is False


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

    acceptance = stage_business_acceptance(
        stage_id="world_review",
        contract=_review_contract(),
        explicit_inputs={},
        final_content=content,
        output_refs=["artifact:world_review"],
        terminal_status="completed",
        requires_file_artifact_refs=True,
    )
    assert extract_explicit_review_verdict(content) == "pass"
    assert acceptance["accepted"] is True
    assert acceptance["business_accepted"] is True


def test_passed_second_round_review_with_resolved_blockers_is_not_revised() -> None:
    content = """# 洪荒时代·世界观审核报告（第2轮）

## 审核结论

裁决：通过，可进入角色设计节点。

## 二、阻塞问题复核

### 阻塞-1：新修炼法机制（已解决）

第3.5节完整给出了旧修炼法与新修炼法的对比框架。

### 阻塞-2：大泽地理定位（已解决）

L1节“大泽：主角出身地”子节已完整锁定。

## 五、审核元信息

- 上一轮阻塞问题：3个，已全部解决
- 产物状态：通过，可冻结为正式世界观设定
"""

    acceptance = stage_business_acceptance(
        stage_id="world_review",
        contract=_review_contract(),
        explicit_inputs={},
        final_content=content,
        output_refs=["artifact:world_review"],
        terminal_status="completed",
        requires_file_artifact_refs=True,
    )
    assert extract_explicit_review_verdict(content) == "pass"
    assert acceptance["accepted"] is True
    assert acceptance["business_accepted"] is True


def test_passed_review_that_mentions_completed_rework_does_not_revise() -> None:
    content = """# 洪荒时代 · 世界观审核报告（第二轮）

## 审核结论

裁决：通过。 本轮返修产物已达到冻结标准，允许进入角色节点和剧情节点。

## 二、第一轮审核意见处理复核

| 审核意见编号 | 等级 | 处理状态 | 复核结论 |
|---|---|---|---|
| 阻塞-1 | 阻塞 | 已解决 | 主角起点锁定为“刚入筑基境”，明确可用 |
| 高优-1 | 高优先级 | 已解决 | 境界表新增“战力参照”列 |

## 三、本轮新发现问题

本轮未发现新的阻塞问题或高优先级问题。

## 四、产物状态

- 产物状态：审核通过，可进入记忆提交流程
"""

    acceptance = stage_business_acceptance(
        stage_id="world_review",
        contract=_review_contract(),
        explicit_inputs={},
        final_content=content,
        output_refs=["artifact:world_review"],
        terminal_status="completed",
        requires_file_artifact_refs=True,
    )
    assert extract_explicit_review_verdict(content) == "pass"
    assert acceptance["accepted"] is True
    assert acceptance["business_accepted"] is True


