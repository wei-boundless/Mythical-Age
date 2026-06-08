from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any


BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from bootstrap.app_runtime import AppRuntime
from harness.entrypoint.models import HarnessRuntimeRequest
from harness.loop.task_executor import stop_task_run


TERMINAL_STATUSES = {"completed", "failed", "blocked", "aborted"}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a real HarnessRuntimeFacade five-floor dungeon task and report DeepSeek prompt-cache facts."
    )
    parser.add_argument("--provider", default="deepseek")
    parser.add_argument("--model", default="deepseek-v4-pro")
    parser.add_argument("--thinking-mode", default="enabled", choices=("disabled", "enabled"))
    parser.add_argument("--reasoning-effort", default="auto", choices=("auto", "high", "max"))
    parser.add_argument("--max-output-tokens", type=int, default=32768)
    parser.add_argument("--min-provider-calls", type=int, default=4)
    parser.add_argument("--stop-after-provider-calls", type=int, default=0)
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    parser.add_argument("--scenario", default="basic", choices=("basic", "complex"))
    parser.add_argument(
        "--output-root",
        default=str(PROJECT_ROOT / "storage" / "runtime_state" / "prompt_cache_live_tests"),
    )
    args = parser.parse_args()
    _validate_model_mode_args(args, parser)
    try:
        report = asyncio.run(_run(args))
    except Exception as exc:
        print(f"LIVE E2E FAILED: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "ok": bool(report.get("ok")),
                "task_run_id": report.get("task_run_id", ""),
                "task_status": report.get("task_status", ""),
                "provider_usage_records": report.get("summary", {}).get("provider_usage_record_count", 0),
                "prompt_tokens": report.get("summary", {}).get("prompt_tokens", 0),
                "cached_tokens": report.get("summary", {}).get("cached_tokens", 0),
                "cache_hit_rate": report.get("summary", {}).get("cache_hit_rate", 0.0),
                "post_warm_cache_hit_rate": report.get("summary", {}).get("post_warm_cache_hit_rate", 0.0),
                "report_dir": report.get("report_dir", ""),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report.get("ok") else 2


def _validate_model_mode_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    provider = str(args.provider or "").strip().lower()
    thinking_mode = str(args.thinking_mode or "disabled").strip().lower()
    reasoning_effort = str(args.reasoning_effort or "auto").strip().lower()
    if provider == "deepseek" and reasoning_effort == "max" and thinking_mode != "enabled":
        parser.error("--reasoning-effort max requires --thinking-mode enabled for DeepSeek max mode.")


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    run_id = f"five_floor_dungeon_e2e_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    report_dir = Path(args.output_root).resolve() / run_id
    report_dir.mkdir(parents=True, exist_ok=True)
    scenario = str(getattr(args, "scenario", "basic") or "basic")
    artifact_dir = "five_floor_dungeon_complex" if scenario == "complex" else "five_floor_dungeon"
    artifact_path = f"artifacts/prompt_cache_live_e2e/{run_id}/{artifact_dir}/index.html"

    runtime = AppRuntime()
    runtime.initialize(BACKEND_DIR)
    app = runtime.require_ready()
    settings = app.settings.static
    session = app.session_manager.create_session(
        title=f"Prompt cache live E2E {run_id}",
        scope={"workspace_view": "task_environment", "task_environment_id": "env.development.sandbox"},
    )
    session_id = str(session["id"])
    model_selection = {
        "provider": str(args.provider or "deepseek"),
        "model": str(args.model or "deepseek-v4-pro"),
        "credential_ref": f"provider:{str(args.provider or 'deepseek')}:primary",
        "max_output_tokens": max(1, int(args.max_output_tokens or 32768)),
        "timeout_seconds": float(getattr(settings, "llm_timeout_seconds", 45.0) or 45.0),
        "long_output_timeout_seconds": float(getattr(settings, "llm_long_output_timeout_seconds", 180.0) or 180.0),
        "max_retries": 0,
        "temperature": 0,
        "thinking_mode": str(args.thinking_mode or "disabled"),
        "reasoning_effort": str(args.reasoning_effort or "auto"),
    }
    runtime_contract = _runtime_contract(run_id=run_id, artifact_path=artifact_path, model_selection=model_selection, scenario=scenario)
    request = HarnessRuntimeRequest(
        session_id=session_id,
        message=(
            "启动真实长任务缓存测试：请按系统给出的显式合同完成复杂版五层地下塔网页小游戏。"
            if scenario == "complex"
            else "启动真实长任务缓存测试：请按系统给出的显式合同完成五层地下塔网页小游戏。"
        )
        + (
            "必须真实写入文件并验证，不要只写计划。"
        ),
        runtime_contract=runtime_contract,
        model_selection=model_selection,
    )

    stream_events = await _collect_stream(app.harness_runtime, request)
    task_run_id = _created_task_run_id(stream_events)
    if not task_run_id:
        _write_json(report_dir / "stream_events.json", stream_events)
        raise RuntimeError("explicit contract did not create a task_run")

    wait_report = await _wait_for_task(
        app.harness_runtime,
        task_run_id=task_run_id,
        min_provider_calls=max(1, int(args.min_provider_calls or 1)),
        stop_after_provider_calls=max(0, int(args.stop_after_provider_calls or 0)),
        timeout_seconds=max(1.0, float(args.timeout_seconds or 300.0)),
    )
    host = app.harness_runtime.single_agent_runtime_host
    await _drain_background_tasks(host, timeout_seconds=10.0)
    task = host.state_index.get_task_run(task_run_id)
    trace = host.get_trace(task_run_id, include_payloads=True, include_model_messages=False)
    artifacts = host.get_task_run_artifacts(task_run_id)
    ledger = host.prompt_accounting_ledger
    usage_rows = [item.to_dict() for item in ledger.list_token_usage(task_run_id=task_run_id)]
    provider_usage = [row for row in usage_rows if str(row.get("source") or "") == "provider_usage"]
    cache_records = [item.to_dict() for item in ledger.list_prompt_cache(task_run_id=task_run_id)]
    segment_maps = ledger.list_segment_maps(task_run_id=task_run_id)
    stability_reports = [item.to_dict() for item in ledger.list_prompt_stability(task_run_id=task_run_id)]
    cache_breaks = [item.to_dict() for item in ledger.list_prompt_cache_breaks(task_run_id=task_run_id)]
    summary = _cache_summary(provider_usage)
    packet_summary = _packet_summary(segment_maps)
    task_status = str(getattr(task, "status", "") or "")
    measurement_ok = bool(provider_usage) and bool(segment_maps)

    report = {
        "ok": measurement_ok and task_status == "completed",
        "measurement_ok": measurement_ok,
        "authority": "backend.scripts.live_five_floor_dungeon_prompt_cache_e2e",
        "run_id": run_id,
        "report_dir": str(report_dir),
        "session_id": session_id,
        "task_run_id": task_run_id,
        "task_status": task_status,
        "task_terminal_reason": str(getattr(task, "terminal_reason", "") or ""),
        "scenario": scenario,
        "model_selection": {key: value for key, value in model_selection.items() if key != "api_key"},
        "artifact_path": artifact_path,
        "wait_report": wait_report,
        "summary": summary,
        "packet_summary": packet_summary,
        "provider_usage": _usage_projection(provider_usage),
        "cache_records": _cache_record_projection(cache_records),
        "cache_breaks": _cache_break_projection(cache_breaks),
        "stability_reports": _stability_projection(stability_reports),
        "artifacts": artifacts,
        "stream_event_types": [str(item.get("type") or "") for item in stream_events],
        "trace_event_types": _trace_event_counts(trace),
    }
    _write_json(report_dir / "stream_events.json", stream_events)
    _write_json(report_dir / "trace.json", trace)
    _write_json(report_dir / "artifacts.json", artifacts)
    _write_json(report_dir / "provider_usage.json", provider_usage)
    _write_json(report_dir / "prompt_cache.json", cache_records)
    _write_json(report_dir / "segment_maps.json", segment_maps)
    _write_json(report_dir / "prompt_stability.json", stability_reports)
    _write_json(report_dir / "prompt_cache_breaks.json", cache_breaks)
    _write_json(report_dir / "report.json", report)
    await runtime.shutdown()
    return report


def _runtime_contract(*, run_id: str, artifact_path: str, model_selection: dict[str, Any], scenario: str = "basic") -> dict[str, Any]:
    complex_scenario = str(scenario or "basic") == "complex"
    allowed_operations = [
        "op.model_response",
        "op.read_file",
        "op.list_dir",
        "op.stat_path",
        "op.path_exists",
        "op.glob_paths",
        "op.search_files",
        "op.search_text",
        "op.write_file",
        "op.edit_file",
        "op.shell",
        "op.agent_todo",
    ]
    image_artifacts: list[dict[str, str]] = []
    if complex_scenario:
        allowed_operations.append("op.image_generate")
        image_targets = [
            {
                "target_id": f"five-floor-dungeon-pixel-tower-{run_id}",
                "asset_kind": "scene",
                "path": f"storage/generated/images/scene-five-floor-dungeon-pixel-tower-{run_id}.png",
                "user_visible_name": "五层地下塔像素主视觉",
            },
            {
                "target_id": f"five-floor-dungeon-pixel-boss-{run_id}",
                "asset_kind": "character",
                "path": f"storage/generated/images/character-five-floor-dungeon-pixel-boss-{run_id}.png",
                "user_visible_name": "五层地下塔像素 Boss 图",
            },
        ]
        image_artifacts = [{"path": item["path"], "kind": "image", "user_visible_name": item["user_visible_name"]} for item in image_targets]
    else:
        image_targets = []
    task_run_goal = (
        f"在 `{artifact_path}` 创建一个复杂版 2D 像素风五层地下塔剧情肉鸽游戏，并生成真实图片资产。"
        "图片服务不稳定，所以必须使用最低配置生图：只生成两张 PNG，image_generate 参数使用 size=`1024x1024`、quality=`low`、output_size=`512x512`、request_timeout_seconds=120、overwrite=false。"
        "你必须先调用 image_generate 生成这两张图，并在 HTML 中引用返回的图片 src："
        f"1) 像素风五层塔主视觉，target_id=`five-floor-dungeon-pixel-tower-{run_id}`，asset_kind=`scene`；"
        f"2) 像素风最终 Boss 图，target_id=`five-floor-dungeon-pixel-boss-{run_id}`，asset_kind=`character`。"
        "两张图都必须是 2D pixel art / 16-bit dark fantasy 风格，轮廓清晰，不能包含图片内文字。"
        "不允许用 emoji、纯 CSS、占位图片或外链图片替代真实 image_generate 产物；如果图片生成失败，必须报告阻塞和结构化错误，不能假装完成。"
        "必须包含：1) 五层地下塔推进，每层有不同主题、房间/事件/敌人配置和层末 Boss；"
        "2) 可操作地图或房间选择，支持键盘或按钮操作；"
        "3) 战斗系统包含生命、攻击、防御、暴击或闪避、敌人行动和战斗日志；"
        "4) 至少三类普通敌人、五个 Boss、药水/金币/装备/遗物掉落；"
        "5) 角色成长包含经验升级、属性提升、技能或遗物选择；"
        "6) 剧情必须可见：开场设定、每层章节文本、至少三个事件叙事、Boss 台词、胜利/失败结局；"
        "7) 至少一种非战斗事件，例如商店、陷阱、宝箱或休息点；"
        "8) 失败、胜利、重新开始和基础存档/读档或本地进度保存；"
        "9) UI 需要有 2D 像素风游戏视图、状态面板、日志、背包/装备/技能展示和清晰操作按钮。"
        "任务必须真实写入文件，并通过 read_file、search_text 或 terminal 检查关键实现；最终回答必须引用真实 artifact。"
    )
    if not complex_scenario:
        task_run_goal = (
            f"在 `{artifact_path}` 创建一个单文件 HTML 游戏。游戏必须包含五层地下塔推进、"
            "房间探索、基础战斗、掉落成长、失败/胜利状态和基础可操作 UI。"
            "任务必须通过 read_file、path_exists 或 terminal 做真实验证；最终回答必须引用真实 artifact。"
        )
    completion_criteria = [
        "产物必须是真实写入的 HTML 文件，不允许用计划或说明替代。",
        "游戏必须有五层推进、房间探索、基础战斗、掉落成长、失败和胜利状态。",
        "最终收口前必须读取文件或运行命令验证关键内容。",
        "最终 action 的 diagnostics.artifacts 必须包含 artifact 路径。",
    ]
    if complex_scenario:
        completion_criteria = [
            "产物必须包含真实写入的 HTML 文件和真实生成的图片资产，不允许用计划或说明替代。",
            "必须实现五层地下塔，每层有独立主题、敌人配置和层末 Boss。",
            "必须实现可操作地图/房间选择、战斗日志、背包/装备/技能或遗物展示。",
            "必须实现至少三类普通敌人、五个 Boss、掉落装备/金币/药水/遗物、经验升级或成长选择。",
            "必须包含可见剧情：开场设定、每层章节文本、事件叙事、Boss 台词、胜利/失败结局。",
            "必须包含至少一种非战斗事件，例如商店、陷阱、宝箱或休息点。",
            "必须包含失败、胜利、重新开始，以及本地保存/读档或进度保存能力。",
            "必须真实调用 image_generate 生成两张低配置 2D 像素风 PNG 图片，并在 HTML 中引用生成结果的 /api/image-assets/files/ 路径。",
            "image_generate 必须使用最低配置：size=1024x1024、quality=low、output_size=512x512、request_timeout_seconds=120、overwrite=false。",
            "不得用 emoji、纯 CSS、占位图或外链图替代真实生成图片；如果 image_generate 失败，必须按阻塞任务处理。",
            "最终收口前必须读取文件或运行命令验证关键关键词和核心逻辑存在。",
            "最终收口前必须验证生成图片文件存在，并验证 HTML 引用了这些图片路径。",
            "最终 action 的 diagnostics.artifacts 必须包含 artifact 路径。",
        ]
    contract = {
        "system_issued": True,
        "contract_id": f"prompt-cache-live-five-floor-dungeon:{scenario}:{run_id}",
        "task_environment_id": "env.development.sandbox",
        "title": "复杂版五层地下塔网页肉鸽" if complex_scenario else "五层地下塔网页小游戏",
        "user_visible_goal": (
            "完成一个复杂版可打开的五层地下塔网页肉鸽，并真实验证产物存在。"
            if complex_scenario
            else "完成一个可打开的五层地下塔网页小游戏，并真实验证产物存在。"
        ),
        "task_run_goal": task_run_goal,
        "required_artifacts": [
            {
                "path": artifact_path,
                "kind": "html_document",
                "user_visible_name": "五层地下塔 HTML 游戏",
            }
        ]
        + image_artifacts,
        "required_verifications": [
            {
                "kind": "file_readback_or_terminal_check",
                "description": (
                    "验证 HTML 文件真实存在，检查关键文本/逻辑包含五层、Boss、装备/背包、技能/遗物、事件、存档、战斗、掉落、胜败状态，并验证 HTML 引用了 image_generate 返回的图片路径。"
                    if complex_scenario
                    else "验证 HTML 文件真实存在，并检查关键文本/逻辑包含五层推进、战斗、掉落、胜败状态。"
                ),
            }
        ]
        + (
            [
                {
                    "kind": "image_asset_check",
                    "description": (
                        "验证 image_generate 生成的场景图和 Boss 图文件真实存在；"
                        f"预期 target_id 包括 `{image_targets[0]['target_id']}` 和 `{image_targets[1]['target_id']}`。"
                    ),
                }
            ]
            if complex_scenario
            else []
        ),
        "completion_criteria": completion_criteria,
        "acceptance_policy": {
            "fail_closed": True,
            "artifact_evidence_required": True,
            "verification_required": True,
        },
        "runtime_profile": {
            "task_environment_id": "env.development.sandbox",
            "model_requirement": model_selection,
            "control_capabilities": {
                "may_call_tools": True,
                "may_request_task_run": False,
                "may_use_subagents": False,
                "requires_json_action_protocol": True,
            },
        },
    }
    return {
        "system_issued_contract": True,
        "task_environment_id": "env.development.sandbox",
        "allowed_operations": allowed_operations,
        "task_contract": contract,
        "runtime_profile": {
            "task_environment_id": "env.development.sandbox",
            "model_requirement": model_selection,
            "control_capabilities": {
                "may_call_tools": True,
                "may_request_task_run": False,
                "may_use_subagents": False,
                "requires_json_action_protocol": True,
            },
        },
    }


async def _collect_stream(runtime_facade: Any, request: HarnessRuntimeRequest) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    async for event in runtime_facade.astream(request):
        events.append(dict(event))
    return events


def _created_task_run_id(events: list[dict[str, Any]]) -> str:
    for event in events:
        task_run_id = str(dict(event.get("task_run") or {}).get("task_run_id") or "")
        if task_run_id.startswith("taskrun:"):
            return task_run_id
    return ""


async def _wait_for_task(
    runtime_facade: Any,
    *,
    task_run_id: str,
    min_provider_calls: int,
    stop_after_provider_calls: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    host = runtime_facade.single_agent_runtime_host
    ledger = host.prompt_accounting_ledger
    deadline = time.monotonic() + timeout_seconds
    stop_requested = False
    samples: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        task = host.state_index.get_task_run(task_run_id)
        usage = [item for item in ledger.list_token_usage(task_run_id=task_run_id) if item.source == "provider_usage"]
        status = str(getattr(task, "status", "") or "")
        samples.append(
            {
                "t": round(time.time(), 3),
                "status": status,
                "provider_usage_records": len(usage),
            }
        )
        if stop_after_provider_calls and len(usage) >= stop_after_provider_calls and not stop_requested and status not in TERMINAL_STATUSES:
            stop_task_run(host, task_run_id, reason="live_prompt_cache_probe_stop_after_provider_calls", requested_by="system")
            stop_requested = True
        if status in TERMINAL_STATUSES:
            return {
                "finished": status == "completed" and len(usage) >= min_provider_calls,
                "terminal_reached": True,
                "timeout": False,
                "stop_requested": stop_requested,
                "provider_usage_records": len(usage),
                "min_provider_calls": min_provider_calls,
                "provider_usage_sufficient": len(usage) >= min_provider_calls,
                "status": status,
                "terminal_reason": str(getattr(task, "terminal_reason", "") or ""),
                "samples": samples[-20:],
            }
        terminal_reason = str(getattr(task, "terminal_reason", "") or "")
        if (
            status == "waiting_executor"
            and terminal_reason
            and terminal_reason != "waiting_executor"
            and not _has_running_background_task(host, task_run_id)
        ):
            return {
                "finished": False,
                "terminal_reached": False,
                "timeout": False,
                "stop_requested": stop_requested,
                "provider_usage_records": len(usage),
                "min_provider_calls": min_provider_calls,
                "provider_usage_sufficient": len(usage) >= min_provider_calls,
                "status": status,
                "terminal_reason": terminal_reason,
                "samples": samples[-20:],
            }
        await asyncio.sleep(1.0)
    usage = [item for item in ledger.list_token_usage(task_run_id=task_run_id) if item.source == "provider_usage"]
    task = host.state_index.get_task_run(task_run_id)
    status = str(getattr(task, "status", "") or "")
    if status not in TERMINAL_STATUSES and not stop_requested:
        stop_task_run(host, task_run_id, reason="live_prompt_cache_probe_timeout", requested_by="system")
        stop_requested = True
        stop_deadline = time.monotonic() + 20.0
        while time.monotonic() < stop_deadline:
            task = host.state_index.get_task_run(task_run_id)
            status = str(getattr(task, "status", "") or "")
            if status in TERMINAL_STATUSES or not _has_running_background_task(host, task_run_id):
                break
            await asyncio.sleep(0.5)
    return {
        "finished": False,
        "terminal_reached": status in TERMINAL_STATUSES,
        "timeout": True,
        "stop_requested": stop_requested,
        "provider_usage_records": len(usage),
        "min_provider_calls": min_provider_calls,
        "provider_usage_sufficient": len(usage) >= min_provider_calls,
        "status": str(getattr(task, "status", "") or ""),
        "terminal_reason": str(getattr(task, "terminal_reason", "") or ""),
        "samples": samples[-20:],
    }


async def _drain_background_tasks(host: Any, *, timeout_seconds: float) -> None:
    tasks = [task for task in list(getattr(host, "_background_tasks", set()) or set()) if not task.done()]
    if not tasks:
        return
    done, pending = await asyncio.wait(tasks, timeout=timeout_seconds)
    for task in done:
        try:
            task.result()
        except Exception:
            pass
    if pending:
        await asyncio.sleep(0)


def _has_running_background_task(host: Any, task_run_id: str) -> bool:
    task_name_prefix = f"task-run-executor:{task_run_id}"
    recovery_name_prefix = f"task-run-executor-recover:{task_run_id}"
    for task in list(getattr(host, "_background_tasks", set()) or set()):
        if task.done():
            continue
        try:
            name = str(task.get_name())
        except Exception:
            name = ""
        if name.startswith(task_name_prefix) or name.startswith(recovery_name_prefix):
            return True
    return False


def _cache_summary(provider_usage: list[dict[str, Any]]) -> dict[str, Any]:
    prompt_tokens = sum(int(row.get("prompt_tokens") or 0) for row in provider_usage)
    cached_tokens = sum(_cached_tokens(row) for row in provider_usage)
    completion_tokens = sum(int(row.get("completion_tokens") or 0) for row in provider_usage)
    post_warm = provider_usage[1:] if len(provider_usage) > 1 else []
    post_prompt = sum(int(row.get("prompt_tokens") or 0) for row in post_warm)
    post_cached = sum(_cached_tokens(row) for row in post_warm)
    return {
        "provider_usage_record_count": len(provider_usage),
        "prompt_tokens": prompt_tokens,
        "cached_tokens": cached_tokens,
        "completion_tokens": completion_tokens,
        "cache_miss_tokens": max(0, prompt_tokens - cached_tokens),
        "cache_hit_rate": round(cached_tokens / prompt_tokens, 4) if prompt_tokens else 0.0,
        "post_warm_prompt_tokens": post_prompt,
        "post_warm_cached_tokens": post_cached,
        "post_warm_cache_hit_rate": round(post_cached / post_prompt, 4) if post_prompt else 0.0,
        "per_call_hit_rates": [
            round(_cached_tokens(row) / int(row.get("prompt_tokens") or 1), 4)
            for row in provider_usage
            if int(row.get("prompt_tokens") or 0) > 0
        ],
    }


def _packet_summary(segment_maps: list[dict[str, Any]]) -> dict[str, Any]:
    stable_hashes = [
        str(dict(row.get("metadata") or {}).get("stable_prefix_hash") or "")
        for row in segment_maps
    ]
    task_hashes = [
        str(dict(row.get("metadata") or {}).get("task_prefix_hash") or "")
        for row in segment_maps
    ]
    provider_hashes = [
        str(dict(row.get("metadata") or {}).get("provider_global_prefix_hash") or "")
        for row in segment_maps
    ]
    first_segments = list(dict(segment_maps[0] if segment_maps else {}).get("segments") or [])
    return {
        "segment_map_count": len(segment_maps),
        "stable_prefix_all_equal": _all_equal_nonempty(stable_hashes),
        "task_prefix_all_equal": _all_equal_nonempty(task_hashes),
        "provider_global_prefix_all_equal": _all_equal_nonempty(provider_hashes),
        "stable_prefix_hashes": stable_hashes,
        "task_prefix_hashes": task_hashes,
        "provider_global_prefix_hashes": provider_hashes,
        "first_segment_kinds": [str(item.get("kind") or "") for item in first_segments],
        "first_cache_roles": [str(item.get("cache_role") or "") for item in first_segments],
        "first_prefix_tiers": [str(item.get("prefix_tier") or "") for item in first_segments],
    }


def _usage_projection(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in rows:
        result.append(
            {
                "request_id": str(row.get("request_id") or ""),
                "provider": str(row.get("provider") or ""),
                "model": str(row.get("model") or ""),
                "prompt_tokens": int(row.get("prompt_tokens") or 0),
                "completion_tokens": int(row.get("completion_tokens") or 0),
                "cached_tokens": _cached_tokens(row),
                "cache_read_tokens": int(row.get("cache_read_tokens") or 0),
                "total_tokens": int(row.get("total_tokens") or 0),
            }
        )
    return result


def _cache_record_projection(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in rows:
        diagnostics = dict(row.get("diagnostics") or {})
        result.append(
            {
                "request_id": str(row.get("request_id") or ""),
                "status": str(row.get("status") or ""),
                "prefix_hash": str(row.get("prefix_hash") or ""),
                "scope": str(row.get("scope") or ""),
                "cached_tokens": int(row.get("cached_tokens") or 0),
                "cache_read_tokens": int(row.get("cache_read_tokens") or 0),
                "cache_savings_tokens": int(row.get("cache_savings_tokens") or 0),
                "provider_cache_policy": dict(diagnostics.get("provider_cache_policy") or {}),
                "stable_prefix_predicted_tokens": int(diagnostics.get("stable_prefix_predicted_tokens") or 0),
                "task_prefix_predicted_tokens": int(diagnostics.get("task_prefix_predicted_tokens") or 0),
                "provider_global_prefix_predicted_tokens": int(diagnostics.get("provider_global_prefix_predicted_tokens") or 0),
            }
        )
    return result


def _cache_break_projection(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "request_id": str(row.get("request_id") or ""),
            "reason": str(row.get("reason") or ""),
            "provider": str(row.get("provider") or ""),
            "model": str(row.get("model") or ""),
            "diagnostics": dict(row.get("diagnostics") or {}),
        }
        for row in rows
    ]


def _stability_projection(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "request_id": str(row.get("request_id") or ""),
            "stable_prefix_tokens": int(row.get("stable_prefix_tokens") or 0),
            "volatile_token_count": int(row.get("volatile_token_count") or 0),
            "stable_prefix_hash": str(row.get("stable_prefix_hash") or ""),
            "first_changed_section": dict(row.get("first_changed_section") or {}),
            "provider_usage": dict(row.get("provider_usage") or {}),
        }
        for row in rows
    ]


def _trace_event_counts(trace: dict[str, Any] | None) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in list(dict(trace or {}).get("events") or []):
        event_type = str(dict(event).get("event_type") or "")
        counts[event_type] = counts.get(event_type, 0) + 1
    return dict(sorted(counts.items()))


def _cached_tokens(row: dict[str, Any]) -> int:
    return max(int(row.get("cached_tokens") or 0), int(row.get("cache_read_tokens") or 0))


def _all_equal_nonempty(values: list[str]) -> bool:
    cleaned = [value for value in values if value]
    return bool(cleaned) and len(set(cleaned)) == 1


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
