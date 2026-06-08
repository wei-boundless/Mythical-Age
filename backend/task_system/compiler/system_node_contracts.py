from __future__ import annotations

from typing import Any


def build_system_node_contract_index(*, graph_id: str) -> dict[str, dict[str, Any]]:
    return {
        "__configurator__": {
            "node_id": "__configurator__",
            "role": "authoring_assistant",
            "lifecycle": "draft_compile",
            "visible_lane": "system_control",
            "can_apply_draft_patch": True,
            "can_publish": False,
            "prompt_contract": {
                "role_prompt": "你是一名任务图配置代理。",
                "task_instruction": (
                    "你负责把用户的业务目标转换为可编译的任务图草案。"
                    "你必须优先选择系统提供的节点、资源和边契约原型，"
                    "输出可由 graph_compiler 校验的 graph_draft_patch。"
                    "你不能写入已发布图契约、运行态图状态、密钥值或权限授予。"
                ),
                "output_requirements": [
                    "说明选择了哪些节点、资源和边契约原型。",
                    "输出 graph_draft_patch.operations，且每个操作都能被配置写入契约校验。",
                    "列出仍需用户确认的环境、资源、权限或输入参数。",
                ],
                "failure_policy": "如果无法生成可编译草案，必须输出阻塞原因和缺失信息，不得猜测密钥或权限。",
                "authority": "task_system.system_node_prompt_contract",
            },
            "authority": "task_system.system_node_contract",
        },
        "__supervisor__": {
            "node_id": "__supervisor__",
            "role": "runtime_supervisor",
            "lifecycle": "graph_run",
            "visible_lane": "system_control",
            "can_mutate_contract": False,
            "can_override_result": False,
            "prompt_contract": {
                "role_prompt": "你是一名任务图运行监管员。",
                "task_instruction": (
                    "你只负责观察任务图运行状态、识别阻塞和风险、提出维护建议。"
                    "你不能替节点完成交付，不能修改已发布契约，不能绕过人工确认或边契约。"
                ),
                "output_requirements": [
                    "输出 health_status，说明当前图运行是否完成、阻塞、失败或等待人工门。",
                    "输出 risk_alerts，指出具体节点或边的风险。",
                    "输出 maintenance_action_candidates，并标明哪些操作需要人工批准。",
                ],
                "failure_policy": "如果状态信息不足，必须报告缺失的 checkpoint、节点结果或边回执，不得直接修改运行状态。",
                "authority": "task_system.system_node_prompt_contract",
            },
            "authority": "task_system.system_node_contract",
        },
    }


def build_maintenance_contract(*, graph_id: str) -> dict[str, Any]:
    return {
        "contract_id": f"maintenance:{graph_id}",
        "system_node_id": "__supervisor__",
        "auto_actions": [
            "emit_health_alert",
            "emit_missing_receipt_diagnostic",
            "mark_recoverable_blocked_node",
        ],
        "require_human_approval": [
            "requeue_failed_node",
            "skip_node",
            "override_result",
            "force_commit_resource",
            "mutate_contract",
        ],
        "max_auto_recovery_attempts": 2,
        "audit_required": True,
        "receipt_required": True,
        "authority": "task_system.maintenance_contract",
    }
