from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.system_eval.execution_core import SseEventCollector


def test_sse_collector_publishes_events_before_stream_finish() -> None:
    observed: list[tuple[str, int]] = []
    collector = SseEventCollector(
        request_start=time.perf_counter(),
        request_start_ts="2026-05-24T00:00:00.000",
        on_event=lambda event, events, _timing: observed.append((str(event["event"]), len(events))),
    )

    collector.consume_line("event: runtime_loop_event")
    collector.consume_line('data: {"event":{"event_type":"task_contract_built"}}')
    collector.consume_line("")

    assert observed == [("runtime_loop_event", 1)]
    assert collector.events[0]["data"]["event"]["event_type"] == "task_contract_built"

    collector.consume_line("event: token")
    collector.consume_line('data: {"content":"hello"}')
    collector.consume_line("")
    events, timing = collector.finish()

    assert observed[-1] == ("token", 2)
    assert len(events) == 2
    assert timing.event_count == 2
