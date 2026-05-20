from __future__ import annotations

from context_management import ContextResolver


def test_context_resolver_builds_bundle_items_for_compound_request() -> None:
    resolver = ContextResolver()
    context = resolver.resolve(
        session_id="session-1",
        task_id="task-1",
        user_message="先总结 PDF 第三页，再给我 inventory.xlsx 最缺货的前三个仓库，最后补一句北京天气。",
        memory_runtime_view={
            "state_snapshot": {
                "context_slots": {
                    "active_pdf": "knowledge/AI Knowledge/report.pdf",
                    "active_dataset": "knowledge/E-commerce Data/inventory.xlsx",
                }
            }
        },
        query_understanding={
            "intent": "multi_capability_request",
            "confidence": 0.9,
            "structural_signals": {
                "explicit_dataset_path": "knowledge/E-commerce Data/inventory.xlsx",
            },
        },
    )

    assert context.execution_mode == "bundle"
    assert context.bundle_item_count == 3
    assert context.bundle_id == "bundle:task-1"
    assert [item.required_tool for item in context.bundle_items] == [
        "",
        "",
        "web_search",
    ]
    assert context.bundle_items[0].recipe_id == ""
    assert context.bundle_items[0].item_id == "bundle:task-1:item:1"
    assert context.bundle_items[1].recipe_id == ""


def test_context_resolver_prefers_explicit_input_over_state_binding() -> None:
    resolver = ContextResolver()
    context = resolver.resolve(
        session_id="session-2",
        task_id="task-2",
        user_message="看 employees.xlsx 的薪资前五。",
        memory_runtime_view={
            "state_snapshot": {
                "context_slots": {
                    "active_dataset": "knowledge/E-commerce Data/inventory.xlsx",
                }
            }
        },
        query_understanding={
            "intent": "structured_dataset_query",
            "confidence": 0.92,
            "structural_signals": {
                "explicit_dataset_path": "knowledge/E-commerce Data/employees.xlsx",
            },
        },
    )

    assert context.resolved_bindings
    assert context.resolved_bindings[0].metadata["path"] == "knowledge/E-commerce Data/employees.xlsx"
    assert context.resolved_bindings[0].source == "explicit_user_input"


def test_context_resolver_does_not_split_priority_word_as_sequence_marker() -> None:
    resolver = ContextResolver()
    message = "再回到 inventory.xlsx。告诉我当前最该优先处理的是哪个仓库，并说清你依据的是缺口、SKU 还是别的口径。"
    context = resolver.resolve(
        session_id="session-priority",
        task_id="task-priority",
        user_message=message,
        memory_runtime_view={
            "state_snapshot": {
                "context_slots": {
                    "active_dataset": "knowledge/E-commerce Data/employees.xlsx",
                }
            }
        },
        query_understanding={
            "intent": "general_query",
            "confidence": 0.9,
            "capability_requests": ["dataset_analysis"],
            "structural_signals": {
                "explicit_dataset_path": "inventory.xlsx",
            },
            "tool_input": {
                "query": message,
                "path": "inventory.xlsx",
            },
        },
    )

    assert context.execution_mode == "single"
    assert context.bundle_items == ()
    assert context.explicit_inputs["explicit_dataset_path"] == "inventory.xlsx"
    assert context.explicit_inputs["explicit_dataset_path"] == "inventory.xlsx"


def test_context_resolver_keeps_state_pdf_as_recall_candidate_not_binding() -> None:
    resolver = ContextResolver()
    context = resolver.resolve(
        session_id="session-2b",
        task_id="task-2b",
        user_message="先总结 PDF 第三页，再看 employees.xlsx 的薪资前五。",
        memory_runtime_view={
            "state_snapshot": {
                "context_slots": {
                    "active_pdf": "knowledge/AI Knowledge/report.pdf",
                    "active_dataset": "knowledge/E-commerce Data/inventory.xlsx",
                }
            }
        },
        query_understanding={
            "intent": "multi_capability_request",
            "confidence": 0.93,
            "structural_signals": {
                    "explicit_dataset_path": "knowledge/E-commerce Data/employees.xlsx",
                    "document_reference": True,
                    "page_reference": True,
                    "mixed_direct_capabilities": True,
            },
        },
    )

    paths = {
        (binding.file_kind, binding.metadata.get("path"))
        for binding in context.resolved_bindings
    }
    assert "explicit_pdf_path" not in context.explicit_inputs
    assert ("dataset", "knowledge/E-commerce Data/employees.xlsx") in paths
    assert ("pdf", "knowledge/AI Knowledge/report.pdf") not in paths
    assert context.context_recall_candidates == ()


def test_context_resolver_binds_ordinal_followup_to_previous_bundle_item() -> None:
    resolver = ContextResolver()
    context = resolver.resolve(
        session_id="session-3",
        task_id="task-3",
        user_message="只展开第二个子任务。",
        memory_runtime_view={
            "state_snapshot": {
                "context_slots": {
                    "active_dataset": "knowledge/E-commerce Data/inventory.xlsx",
                },
                "bundle_result_refs": [
                    {
                        "ordinal": 1,
                        "task_id": "result:pdf:a",
                        "task_kind": "pdf",
                        "capability_kind": "pdf",
                        "query": "总结 PDF 第三页",
                        "summary": "第三页摘要",
                    },
                    {
                        "ordinal": 2,
                        "task_id": "bundle:2:inventory",
                        "task_kind": "structured_data",
                        "capability_kind": "structured_data",
                        "required_tool": "",
                        "query": "inventory.xlsx 最缺货的前三个仓库",
                        "summary": "深圳仓、广州仓、成都仓缺货最突出。",
                    },
                ],
            }
        },
        query_understanding={
            "intent": "structured_dataset_query",
            "confidence": 0.91,
            "structural_signals": {
            },
        },
    )

    assert context.intent == "bundle_followup"
    assert context.explicit_inputs["ordinal_followup"] == [2]
    assert context.resolved_bindings[0].binding_kind == "task_ref"
    assert context.resolved_bindings[0].metadata["ordinal"] == 2
    assert context.resolved_bindings[0].metadata["task_kind"] == "structured_data"
    assert context.bundle_items[0].recipe_id == ""
    assert context.followup_target_refs == ("bundle:2:inventory",)
