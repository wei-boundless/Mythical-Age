from __future__ import annotations

import asyncio
import argparse
import json
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from bootstrap.app_runtime import AppRuntime
from task_system.registry.flow_registry import TaskFlowRegistry


GRAPH_RUN_ID = "grun:graph_writing_modular_novel_master:1781042533607"
CONFIG_ID = "ghcfg:graph_writing_modular_novel_master:5531d8a4f71fb9f9"


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-node-executions", type=int, default=4)
    parser.add_argument("--max-runtime-seconds", type=float, default=1500.0)
    args = parser.parse_args()
    runtime = AppRuntime()
    runtime.initialize(BACKEND_DIR)
    graph_config = TaskFlowRegistry(BACKEND_DIR).get_graph_harness_config(CONFIG_ID)
    if graph_config is None:
        raise RuntimeError(f"config not found: {CONFIG_ID}")
    started = time.time()
    print(
        json.dumps(
            {
                "event": "runner_start",
                "graph_run_id": GRAPH_RUN_ID,
                "config_id": graph_config.config_id,
                "started_at": started,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    result = await runtime.harness_runtime.graph_harness.run_until_idle(
        graph_config=graph_config,
        graph_run_id=GRAPH_RUN_ID,
        max_node_executions=max(1, int(args.max_node_executions or 4)),
        max_loop_iterations=max(12, int(args.max_node_executions or 4) * 3),
        max_node_steps=12,
        max_dispatches=max(4, int(args.max_node_executions or 4)),
        max_runtime_seconds=max(1.0, float(args.max_runtime_seconds or 1500.0)),
        max_dispatch_requests=1,
    )
    state = runtime.harness_runtime.graph_harness.graph_loop.get_state(GRAPH_RUN_ID)
    print(
        json.dumps(
            {
                "event": "runner_done",
                "elapsed_seconds": round(time.time() - started, 2),
                "result": result.to_dict(),
                "state_summary": {
                    "status": state.status if state else "",
                    "ready": list(state.ready_node_ids) if state else [],
                    "running": list(state.running_node_ids) if state else [],
                    "blocked": list(state.blocked_node_ids) if state else [],
                    "active": dict(state.active_work_orders) if state else {},
                    "event_cursor": state.event_cursor if state else None,
                },
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
