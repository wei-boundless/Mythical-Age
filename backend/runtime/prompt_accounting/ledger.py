from __future__ import annotations

import json
import threading
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from .cache_baseline import PromptCacheBaselineRecord, PromptCacheBaselineTracker
from .cache_break_detector import PromptCacheBreakRecord
from .models import ModelTokenUsageRecord, PromptCacheRecord, PromptSegment, PromptSegmentMap
from .stability_models import PromptStabilityReport


class PromptAccountingLedger:
    """Durable prompt/token/cache fact ledger for runtime consumers."""

    def __init__(self, root_dir: Path) -> None:
        self.root_dir = Path(root_dir)
        self.ledger_dir = self.root_dir / "prompt_accounting"
        self.ledger_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def record_segment_map(self, segment_map: PromptSegmentMap) -> None:
        self._append_jsonl("segment_maps.jsonl", segment_map.to_dict())
        for segment in segment_map.segments:
            self.record_segment(segment)

    def record_segment(self, segment: PromptSegment) -> None:
        self._append_jsonl("segments.jsonl", segment.to_dict())

    def record_token_usage(self, record: ModelTokenUsageRecord) -> None:
        self._append_jsonl("token_usage.jsonl", record.to_dict())

    def record_prompt_cache(self, record: PromptCacheRecord) -> None:
        self._append_jsonl("prompt_cache.jsonl", record.to_dict())

    def record_prompt_cache_baseline(self, record: PromptCacheBaselineRecord) -> None:
        self._append_jsonl("prompt_cache_baselines.jsonl", record.to_dict())

    def record_prompt_cache_break(self, record: PromptCacheBreakRecord) -> None:
        self._append_jsonl("prompt_cache_breaks.jsonl", record.to_dict())

    def record_prompt_stability(self, report: PromptStabilityReport) -> None:
        self._append_jsonl("prompt_stability.jsonl", report.to_dict())

    def list_segments(self, *, run_id: str = "", task_run_id: str = "", session_id: str = "") -> list[PromptSegment]:
        rows = self._read_jsonl("segments.jsonl")
        result: list[PromptSegment] = []
        for row in rows:
            if run_id and str(row.get("run_id") or row.get("task_run_id") or "") != run_id:
                continue
            if task_run_id and str(row.get("task_run_id") or "") != task_run_id:
                continue
            if session_id and str(row.get("session_id") or "") != session_id:
                continue
            result.append(_segment_from_dict(row))
        return result

    def list_segment_maps(self, *, run_id: str = "", task_run_id: str = "", session_id: str = "") -> list[dict[str, Any]]:
        rows = self._read_jsonl("segment_maps.jsonl")
        result: list[dict[str, Any]] = []
        for row in rows:
            if run_id and str(row.get("run_id") or row.get("task_run_id") or "") != run_id:
                continue
            if task_run_id and str(row.get("task_run_id") or "") != task_run_id:
                continue
            if session_id and str(row.get("session_id") or "") != session_id:
                continue
            result.append(row)
        return sorted(result, key=lambda item: float(item.get("created_at") or 0.0))

    def list_token_usage(self, *, run_id: str = "", task_run_id: str = "", session_id: str = "") -> list[ModelTokenUsageRecord]:
        records: dict[str, ModelTokenUsageRecord] = {}
        for row in self._read_jsonl("token_usage.jsonl"):
            if run_id and str(row.get("run_id") or row.get("task_run_id") or "") != run_id:
                continue
            if task_run_id and str(row.get("task_run_id") or "") != task_run_id:
                continue
            if session_id and str(row.get("session_id") or "") != session_id:
                continue
            record = ModelTokenUsageRecord.from_dict(row)
            key = record.usage_id or f"{record.request_id}:{record.source}:{record.created_at}"
            previous = records.get(key)
            if previous is None or record.created_at >= previous.created_at:
                records[key] = record
        return sorted(records.values(), key=lambda item: item.created_at)

    def list_prompt_cache(self, *, run_id: str = "", task_run_id: str = "", session_id: str = "") -> list[PromptCacheRecord]:
        records: dict[str, PromptCacheRecord] = {}
        for row in self._read_jsonl("prompt_cache.jsonl"):
            if run_id and str(row.get("run_id") or row.get("task_run_id") or "") != run_id:
                continue
            if task_run_id and str(row.get("task_run_id") or "") != task_run_id:
                continue
            if session_id and str(row.get("session_id") or "") != session_id:
                continue
            record = PromptCacheRecord.from_dict(row)
            key = record.cache_record_id or f"{record.request_id}:{record.created_at}"
            previous = records.get(key)
            if previous is None or record.created_at >= previous.created_at:
                records[key] = record
        return sorted(records.values(), key=lambda item: item.created_at)

    def list_prompt_cache_baselines(
        self,
        *,
        run_id: str = "",
        task_run_id: str = "",
        session_id: str = "",
        status: str = "",
    ) -> list[PromptCacheBaselineRecord]:
        records: dict[str, PromptCacheBaselineRecord] = {}
        for row in self._read_jsonl("prompt_cache_baselines.jsonl"):
            if run_id and str(row.get("run_id") or row.get("task_run_id") or "") != run_id:
                continue
            if task_run_id and str(row.get("task_run_id") or "") != task_run_id:
                continue
            if session_id and str(row.get("session_id") or "") != session_id:
                continue
            if status and str(row.get("status") or "") != status:
                continue
            record = PromptCacheBaselineRecord.from_dict(row)
            key = record.baseline_id or f"{record.request_id}:{record.status}:{record.created_at}"
            previous = records.get(key)
            if previous is None or record.created_at >= previous.created_at:
                records[key] = record
        return sorted(records.values(), key=lambda item: item.created_at)

    def reset_prompt_cache_baseline(
        self,
        *,
        request_id: str = "",
        run_id: str = "",
        task_run_id: str = "",
        session_id: str = "",
        invocation_kind: str = "",
        provider: str = "",
        model: str = "",
        reason: str,
        reset_ref: str = "",
        diagnostics: dict[str, Any] | None = None,
        created_at: float | None = None,
    ) -> PromptCacheBaselineRecord:
        previous = self.list_prompt_cache_baselines(
            run_id=run_id,
            task_run_id=task_run_id,
            session_id=session_id,
        )
        record = PromptCacheBaselineTracker().build_invalidation_record(
            previous_records=previous,
            request_id=request_id,
            run_id=run_id,
            task_run_id=task_run_id,
            session_id=session_id,
            invocation_kind=invocation_kind,
            provider=provider,
            model=model,
            reason=reason,
            reset_ref=reset_ref,
            diagnostics=diagnostics,
            created_at=created_at,
        )
        self.record_prompt_cache_baseline(record)
        return record

    def list_prompt_cache_breaks(self, *, run_id: str = "", task_run_id: str = "", session_id: str = "") -> list[PromptCacheBreakRecord]:
        records: dict[str, PromptCacheBreakRecord] = {}
        for row in self._read_jsonl("prompt_cache_breaks.jsonl"):
            if run_id and str(row.get("run_id") or row.get("task_run_id") or "") != run_id:
                continue
            if task_run_id and str(row.get("task_run_id") or "") != task_run_id:
                continue
            if session_id and str(row.get("session_id") or "") != session_id:
                continue
            record = PromptCacheBreakRecord.from_dict(row)
            key = record.break_id or f"{record.request_id}:{record.created_at}"
            previous = records.get(key)
            if previous is None or record.created_at >= previous.created_at:
                records[key] = record
        return sorted(records.values(), key=lambda item: item.created_at)

    def list_prompt_stability(self, *, run_id: str = "", task_run_id: str = "", session_id: str = "") -> list[PromptStabilityReport]:
        records: dict[str, PromptStabilityReport] = {}
        for row in self._read_jsonl("prompt_stability.jsonl"):
            if run_id and str(row.get("run_id") or row.get("task_run_id") or "") != run_id:
                continue
            if task_run_id and str(row.get("task_run_id") or "") != task_run_id:
                continue
            if session_id and str(row.get("session_id") or "") != session_id:
                continue
            report = PromptStabilityReport.from_dict(row)
            key = report.report_id or f"{report.request_id}:{report.created_at}"
            previous = records.get(key)
            if previous is None or report.created_at >= previous.created_at:
                records[key] = report
        return sorted(records.values(), key=lambda item: item.created_at)

    def summarize_task(self, task_run_id: str) -> dict[str, Any]:
        return summarize_usage_records(
            self.list_token_usage(task_run_id=task_run_id),
            cache_records=self.list_prompt_cache(task_run_id=task_run_id),
        )

    def summarize_tasks(self, task_run_ids: list[str] | tuple[str, ...] | set[str]) -> dict[str, dict[str, Any]]:
        targets = {str(item).strip() for item in task_run_ids if str(item).strip()}
        if not targets:
            return {}
        usage_by_task: dict[str, list[ModelTokenUsageRecord]] = {task_run_id: [] for task_run_id in targets}
        cache_by_task: dict[str, list[PromptCacheRecord]] = {task_run_id: [] for task_run_id in targets}
        latest_usage: dict[tuple[str, str], ModelTokenUsageRecord] = {}
        for row in self._read_jsonl("token_usage.jsonl"):
            task_run_id = str(row.get("task_run_id") or row.get("run_id") or "")
            if task_run_id not in targets:
                continue
            record = ModelTokenUsageRecord.from_dict(row)
            key = (task_run_id, record.usage_id or f"{record.request_id}:{record.source}:{record.created_at}")
            previous = latest_usage.get(key)
            if previous is None or record.created_at >= previous.created_at:
                latest_usage[key] = record
        for (task_run_id, _key), record in latest_usage.items():
            usage_by_task.setdefault(task_run_id, []).append(record)
        latest_cache: dict[tuple[str, str], PromptCacheRecord] = {}
        for row in self._read_jsonl("prompt_cache.jsonl"):
            task_run_id = str(row.get("task_run_id") or row.get("run_id") or "")
            if task_run_id not in targets:
                continue
            record = PromptCacheRecord.from_dict(row)
            key = (task_run_id, record.cache_record_id or f"{record.request_id}:{record.created_at}")
            previous = latest_cache.get(key)
            if previous is None or record.created_at >= previous.created_at:
                latest_cache[key] = record
        for (task_run_id, _key), record in latest_cache.items():
            cache_by_task.setdefault(task_run_id, []).append(record)
        return {
            task_run_id: summarize_usage_records(
                sorted(usage_by_task.get(task_run_id) or [], key=lambda item: item.created_at),
                cache_records=sorted(cache_by_task.get(task_run_id) or [], key=lambda item: item.created_at),
            )
            for task_run_id in targets
        }

    def summarize_run(self, run_id: str) -> dict[str, Any]:
        return summarize_usage_records(
            self.list_token_usage(run_id=run_id),
            cache_records=self.list_prompt_cache(run_id=run_id),
        )

    def summarize_session(self, session_id: str) -> dict[str, Any]:
        return summarize_usage_records(
            self.list_token_usage(session_id=session_id),
            cache_records=self.list_prompt_cache(session_id=session_id),
        )

    def summarize_all(self) -> dict[str, Any]:
        return summarize_usage_records(
            self.list_token_usage(),
            cache_records=self.list_prompt_cache(),
        )

    def prune_task_runs(self, task_run_ids: set[str] | list[str] | tuple[str, ...]) -> dict[str, Any]:
        targets = {str(item).strip() for item in task_run_ids if str(item).strip()}
        if not targets:
            return {
                "authority": "runtime.prompt_accounting.ledger.prune_task_runs",
                "deleted_counts": {},
                "requested_task_run_ids": [],
            }
        deleted_counts = {
            "segment_maps": self._rewrite_without_tasks("segment_maps.jsonl", targets),
            "segments": self._rewrite_without_tasks("segments.jsonl", targets),
            "token_usage": self._rewrite_without_tasks("token_usage.jsonl", targets),
            "prompt_cache": self._rewrite_without_tasks("prompt_cache.jsonl", targets),
            "prompt_cache_baselines": self._rewrite_without_tasks("prompt_cache_baselines.jsonl", targets),
            "prompt_cache_breaks": self._rewrite_without_tasks("prompt_cache_breaks.jsonl", targets),
            "prompt_stability": self._rewrite_without_tasks("prompt_stability.jsonl", targets),
        }
        return {
            "authority": "runtime.prompt_accounting.ledger.prune_task_runs",
            "requested_task_run_ids": sorted(targets),
            "deleted_counts": {key: value for key, value in deleted_counts.items() if value},
        }

    def prune_session(self, session_id: str, task_run_ids: set[str] | list[str] | tuple[str, ...] = ()) -> dict[str, Any]:
        normalized = str(session_id or "").strip()
        targets = {str(item).strip() for item in task_run_ids if str(item).strip()}
        if not normalized and not targets:
            return {
                "authority": "runtime.prompt_accounting.ledger.prune_session",
                "session_id": "",
                "requested_task_run_ids": [],
                "deleted_counts": {},
            }
        deleted_counts = {
            "segment_maps": self._rewrite_without_session_or_tasks("segment_maps.jsonl", normalized, targets),
            "segments": self._rewrite_without_session_or_tasks("segments.jsonl", normalized, targets),
            "token_usage": self._rewrite_without_session_or_tasks("token_usage.jsonl", normalized, targets),
            "prompt_cache": self._rewrite_without_session_or_tasks("prompt_cache.jsonl", normalized, targets),
            "prompt_cache_baselines": self._rewrite_without_session_or_tasks("prompt_cache_baselines.jsonl", normalized, targets),
            "prompt_cache_breaks": self._rewrite_without_session_or_tasks("prompt_cache_breaks.jsonl", normalized, targets),
            "prompt_stability": self._rewrite_without_session_or_tasks("prompt_stability.jsonl", normalized, targets),
        }
        return {
            "authority": "runtime.prompt_accounting.ledger.prune_session",
            "session_id": normalized,
            "requested_task_run_ids": sorted(targets),
            "deleted_counts": {key: value for key, value in deleted_counts.items() if value},
        }

    def _append_jsonl(self, filename: str, payload: dict[str, Any]) -> None:
        path = self.ledger_dir / filename
        with self._lock:
            with path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")

    def _read_jsonl(self, filename: str) -> list[dict[str, Any]]:
        path = self.ledger_dir / filename
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        with self._lock:
            lines = path.read_text(encoding="utf-8").splitlines()
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except JSONDecodeError:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
        return rows

    def _rewrite_without_tasks(self, filename: str, task_run_ids: set[str]) -> int:
        path = self.ledger_dir / filename
        if not path.exists():
            return 0
        rows = self._read_jsonl(filename)
        kept: list[dict[str, Any]] = []
        deleted = 0
        for row in rows:
            if str(row.get("task_run_id") or "") in task_run_ids or str(row.get("run_id") or "") in task_run_ids:
                deleted += 1
                continue
            kept.append(row)
        with self._lock:
            with path.open("w", encoding="utf-8", newline="\n") as handle:
                for row in kept:
                    handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        return deleted

    def _rewrite_without_session_or_tasks(self, filename: str, session_id: str, task_run_ids: set[str]) -> int:
        path = self.ledger_dir / filename
        if not path.exists():
            return 0
        rows = self._read_jsonl(filename)
        kept: list[dict[str, Any]] = []
        deleted = 0
        for row in rows:
            row_task_run_id = str(row.get("task_run_id") or row.get("run_id") or "")
            row_session_id = str(row.get("session_id") or "")
            if row_task_run_id in task_run_ids or (session_id and row_session_id == session_id):
                deleted += 1
                continue
            kept.append(row)
        with self._lock:
            with path.open("w", encoding="utf-8", newline="\n") as handle:
                for row in kept:
                    handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        return deleted


def summarize_usage_records(
    records: list[ModelTokenUsageRecord],
    *,
    cache_records: list[PromptCacheRecord] | None = None,
) -> dict[str, Any]:
    totals = {
        "exact_total_tokens": 0,
        "predicted_total_tokens": 0,
        "trace_estimate_total_tokens": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "reasoning_tokens": 0,
        "cached_tokens": 0,
        "cache_creation_tokens": 0,
        "cache_read_tokens": 0,
        "cache_savings_tokens": 0,
        "provider_usage_record_count": 0,
        "local_prediction_record_count": 0,
        "trace_estimate_record_count": 0,
        "record_count": 0,
    }
    by_request: dict[str, dict[str, ModelTokenUsageRecord]] = {}
    for record in records:
        by_request.setdefault(record.request_id or record.usage_id, {})[record.source] = record
        totals["record_count"] += 1
        if record.source == "provider_usage":
            totals["provider_usage_record_count"] += 1
            totals["exact_total_tokens"] += int(record.total_tokens or 0)
            totals["prompt_tokens"] += int(record.prompt_tokens or 0)
            totals["completion_tokens"] += int(record.completion_tokens or 0)
            totals["reasoning_tokens"] += int(record.reasoning_tokens or 0)
            totals["cached_tokens"] += int(record.cached_tokens or 0)
            totals["cache_creation_tokens"] += int(record.cache_creation_tokens or 0)
            totals["cache_read_tokens"] += int(record.cache_read_tokens or 0)
        elif record.source == "local_prediction":
            totals["local_prediction_record_count"] += 1
            totals["predicted_total_tokens"] += int(record.total_tokens or 0)
        elif record.source == "trace_estimate":
            totals["trace_estimate_record_count"] += 1
            totals["trace_estimate_total_tokens"] += int(record.total_tokens or 0)
    effective = 0
    for source_map in by_request.values():
        selected = (
            source_map.get("provider_usage")
            or source_map.get("local_prediction")
            or source_map.get("trace_estimate")
        )
        if selected is not None:
            effective += int(selected.total_tokens or 0)
    for cache_record in list(cache_records or []):
        totals["cache_savings_tokens"] += int(cache_record.cache_savings_tokens or 0)
    totals["effective_total_tokens"] = effective
    totals["total_tokens"] = effective
    totals["billing_truth_available"] = totals["provider_usage_record_count"] > 0
    return totals


def _segment_from_dict(payload: dict[str, Any]) -> PromptSegment:
    return PromptSegment(
        segment_id=str(payload.get("segment_id") or ""),
        request_id=str(payload.get("request_id") or ""),
        run_id=str(payload.get("run_id") or payload.get("task_run_id") or ""),
        task_run_id=str(payload.get("task_run_id") or ""),
        session_id=str(payload.get("session_id") or ""),
        kind=str(payload.get("kind") or "unknown_unplanned"),
        ordinal=int(payload.get("ordinal") or 0),
        role=str(payload.get("role") or ""),
        content_hash=str(payload.get("content_hash") or ""),
        byte_length=int(payload.get("byte_length") or 0),
        predicted_tokens=int(payload.get("predicted_tokens") or 0),
        cache_role=payload.get("cache_role", "volatile"),
        prefix_tier=payload.get("prefix_tier", "volatile"),
        compression_role=payload.get("compression_role", "summarize"),
        source=str(payload.get("source") or ""),
        created_at=float(payload.get("created_at") or 0.0),
        metadata=dict(payload.get("metadata") or {}),
        authority=str(payload.get("authority") or "runtime.prompt_accounting.prompt_segment"),
    )
