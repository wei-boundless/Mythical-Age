from __future__ import annotations

import hashlib
import json
import threading
import time
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from .cache_baseline import PromptCacheBaselineRecord, PromptCacheBaselineTracker
from .cache_break_detector import PromptCacheBreakRecord
from .models import ModelTokenUsageRecord, PromptCacheRecord, PromptSegment, PromptSegmentMap
from .stability_models import PromptStabilityReport


class PromptAccountingLedger:
    """Durable prompt/token/cache fact ledger for runtime consumers."""

    RECENT_RECORD_LIMIT = 1024
    SUMMARY_INDEX_VERSION = 1
    SUMMARY_SCAN_MAX_BYTES = 64 * 1024 * 1024
    RETAINED_TOKEN_STATS_VERSION = 1
    DEFAULT_DETAIL_RETENTION_DAYS = 7
    RETENTION_DETAIL_FILES = (
        "segment_maps.jsonl",
        "segments.jsonl",
        "token_usage.jsonl",
        "prompt_cache.jsonl",
        "prompt_cache_breaks.jsonl",
        "prompt_stability.jsonl",
    )
    TIME_BUCKETED_DETAIL_FILES = (
        "segment_maps.jsonl",
        "segments.jsonl",
        "token_usage.jsonl",
        "prompt_cache.jsonl",
        "prompt_cache_baselines.jsonl",
        "prompt_cache_breaks.jsonl",
        "prompt_stability.jsonl",
    )

    def __init__(self, root_dir: Path) -> None:
        self.root_dir = Path(root_dir)
        self.ledger_dir = self.root_dir / "prompt_accounting"
        self.ledger_dir.mkdir(parents=True, exist_ok=True)
        self.hot_day_dir = self.ledger_dir / "hot" / "by_day"
        self.hot_time_dir = self.ledger_dir / "hot" / "by_time"
        self.summary_index_dir = self.ledger_dir / "summary_index" / "by_key"
        self.summary_index_dir.mkdir(parents=True, exist_ok=True)
        self.summary_index_manifest_path = self.ledger_dir / "summary_index" / "manifest.json"
        self.context_usage_latest_dir = self.ledger_dir / "context_usage" / "latest_by_session"
        self.context_usage_latest_dir.mkdir(parents=True, exist_ok=True)
        self.retention_dir = self.ledger_dir / "retention"
        self.retention_dir.mkdir(parents=True, exist_ok=True)
        self.retained_token_stats_path = self.retention_dir / "token_stats.json"
        self.retention_receipts_path = self.retention_dir / "receipts.jsonl"
        self._lock = threading.RLock()
        self._filtered_read_cache: dict[
            tuple[str, str, str, str],
            tuple[tuple[int, int], list[dict[str, Any]]],
        ] = {}
        self._retained_token_stats_cache: tuple[tuple[int, int], dict[str, Any]] | None = None
        self._recent_token_usage: list[ModelTokenUsageRecord] = []
        self._recent_prompt_cache: list[PromptCacheRecord] = []
        self._recent_prompt_cache_baselines: list[PromptCacheBaselineRecord] = []
        self._recent_prompt_stability: list[PromptStabilityReport] = []
        self._bootstrap_context_usage_latest_from_summary_index()

    def record_segment_map(self, segment_map: PromptSegmentMap) -> None:
        self._append_jsonl("segment_maps.jsonl", segment_map.to_dict())
        for segment in segment_map.segments:
            self.record_segment(segment)

    def record_segment(self, segment: PromptSegment) -> None:
        self._append_jsonl("segments.jsonl", segment.to_dict())

    def record_token_usage(self, record: ModelTokenUsageRecord) -> None:
        self._append_jsonl("token_usage.jsonl", record.to_dict())
        self._remember_recent(self._recent_token_usage, record)
        self._upsert_usage_summary(record)

    def record_context_usage_snapshot(
        self,
        record: ModelTokenUsageRecord,
        *,
        request_started_at: float | None = None,
        observed_at: float | None = None,
    ) -> None:
        session_id = str(getattr(record, "session_id", "") or "").strip()
        if not session_id:
            return
        payload = _context_usage_snapshot_from_record(
            record,
            request_started_at=request_started_at,
            observed_at=observed_at,
        )
        if int(payload.get("current_context_tokens") or 0) <= 0:
            return
        path = self._context_usage_snapshot_path(session_id)
        with self._lock:
            current = self._read_context_usage_snapshot_path(path)
            if current is not None and not _context_usage_snapshot_should_replace(current, payload):
                return
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = path.with_suffix(f"{path.suffix}.{threading.get_ident()}.tmp")
            tmp_path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
            tmp_path.replace(path)

    def read_latest_context_usage_snapshot(self, session_id: str) -> dict[str, Any]:
        normalized = str(session_id or "").strip()
        if not normalized:
            return {}
        with self._lock:
            payload = self._read_context_usage_snapshot_path(self._context_usage_snapshot_path(normalized))
        return dict(payload or {})

    def record_prompt_cache(self, record: PromptCacheRecord) -> None:
        self._append_jsonl("prompt_cache.jsonl", record.to_dict())
        self._remember_recent(self._recent_prompt_cache, record)
        self._upsert_cache_summary(record)

    def record_prompt_cache_baseline(self, record: PromptCacheBaselineRecord) -> None:
        self._append_jsonl("prompt_cache_baselines.jsonl", record.to_dict())
        self._remember_recent(self._recent_prompt_cache_baselines, record)

    def record_prompt_cache_break(self, record: PromptCacheBreakRecord) -> None:
        self._append_jsonl("prompt_cache_breaks.jsonl", record.to_dict())

    def record_prompt_stability(self, report: PromptStabilityReport) -> None:
        self._append_jsonl("prompt_stability.jsonl", report.to_dict())
        self._remember_recent(self._recent_prompt_stability, report)

    def _remember_recent(self, records: list[Any], record: Any) -> None:
        with self._lock:
            records.append(record)
            overflow = len(records) - self.RECENT_RECORD_LIMIT
            if overflow > 0:
                del records[:overflow]

    def list_segments(self, *, run_id: str = "", task_run_id: str = "", session_id: str = "") -> list[PromptSegment]:
        rows = self._read_jsonl("segments.jsonl", run_id=run_id, task_run_id=task_run_id, session_id=session_id)
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
        rows = self._read_jsonl("segment_maps.jsonl", run_id=run_id, task_run_id=task_run_id, session_id=session_id)
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
        for row in self._read_jsonl("token_usage.jsonl", run_id=run_id, task_run_id=task_run_id, session_id=session_id):
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

    def list_recent_token_usage(
        self,
        *,
        run_id: str = "",
        task_run_id: str = "",
        session_id: str = "",
        limit: int = 512,
    ) -> list[ModelTokenUsageRecord]:
        with self._lock:
            records = list(self._recent_token_usage)
        return _recent_records(
            records,
            run_id=run_id,
            task_run_id=task_run_id,
            session_id=session_id,
            limit=limit,
            key_fn=lambda record: record.usage_id or f"{record.request_id}:{record.source}:{record.created_at}",
        )

    def list_prompt_cache(self, *, run_id: str = "", task_run_id: str = "", session_id: str = "") -> list[PromptCacheRecord]:
        records: dict[str, PromptCacheRecord] = {}
        for row in self._read_jsonl("prompt_cache.jsonl", run_id=run_id, task_run_id=task_run_id, session_id=session_id):
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

    def list_recent_prompt_cache(
        self,
        *,
        run_id: str = "",
        task_run_id: str = "",
        session_id: str = "",
        limit: int = 128,
    ) -> list[PromptCacheRecord]:
        with self._lock:
            records = list(self._recent_prompt_cache)
        return _recent_records(
            records,
            run_id=run_id,
            task_run_id=task_run_id,
            session_id=session_id,
            limit=limit,
            key_fn=lambda record: record.cache_record_id or f"{record.request_id}:{record.created_at}",
        )

    def list_prompt_cache_baselines(
        self,
        *,
        run_id: str = "",
        task_run_id: str = "",
        session_id: str = "",
        status: str = "",
    ) -> list[PromptCacheBaselineRecord]:
        records: dict[str, PromptCacheBaselineRecord] = {}
        for row in self._read_jsonl("prompt_cache_baselines.jsonl", run_id=run_id, task_run_id=task_run_id, session_id=session_id):
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

    def list_recent_prompt_cache_baselines(
        self,
        *,
        run_id: str = "",
        task_run_id: str = "",
        session_id: str = "",
        status: str = "",
        limit: int = 128,
    ) -> list[PromptCacheBaselineRecord]:
        with self._lock:
            records = list(self._recent_prompt_cache_baselines)
        filtered = _recent_records(
            records,
            run_id=run_id,
            task_run_id=task_run_id,
            session_id=session_id,
            limit=self.RECENT_RECORD_LIMIT,
            key_fn=lambda record: record.baseline_id or f"{record.request_id}:{record.status}:{record.created_at}",
        )
        normalized_status = str(status or "")
        if normalized_status:
            filtered = [record for record in filtered if str(getattr(record, "status", "") or "") == normalized_status]
        return filtered[-max(1, int(limit or 128)) :]

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
        if self.scoped_reads_are_expensive():
            previous = self.list_recent_prompt_cache_baselines(
                run_id=run_id,
                task_run_id=task_run_id,
                session_id=session_id,
                limit=self.RECENT_RECORD_LIMIT,
            )
            previous_records_source = "recent"
        else:
            previous = self.list_prompt_cache_baselines(
                run_id=run_id,
                task_run_id=task_run_id,
                session_id=session_id,
            )
            previous_records_source = "ledger"
        next_diagnostics = dict(diagnostics or {})
        next_diagnostics.setdefault("previous_records_source", previous_records_source)
        next_diagnostics.setdefault("previous_record_count", len(previous))
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
            diagnostics=next_diagnostics,
            created_at=created_at,
        )
        self.record_prompt_cache_baseline(record)
        return record

    def list_prompt_cache_breaks(self, *, run_id: str = "", task_run_id: str = "", session_id: str = "") -> list[PromptCacheBreakRecord]:
        records: dict[str, PromptCacheBreakRecord] = {}
        for row in self._read_jsonl("prompt_cache_breaks.jsonl", run_id=run_id, task_run_id=task_run_id, session_id=session_id):
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
        for row in self._read_jsonl("prompt_stability.jsonl", run_id=run_id, task_run_id=task_run_id, session_id=session_id):
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

    def list_recent_prompt_stability(
        self,
        *,
        run_id: str = "",
        task_run_id: str = "",
        session_id: str = "",
        limit: int = 128,
    ) -> list[PromptStabilityReport]:
        with self._lock:
            records = list(self._recent_prompt_stability)
        return _recent_records(
            records,
            run_id=run_id,
            task_run_id=task_run_id,
            session_id=session_id,
            limit=limit,
            key_fn=lambda record: record.report_id or f"{record.request_id}:{record.created_at}",
        )

    def summarize_task(self, task_run_id: str) -> dict[str, Any]:
        indexed = self._summary_for_key(task_run_id)
        if indexed is not None:
            return indexed
        if not self._summary_scan_allowed():
            return _empty_usage_summary()
        return summarize_usage_records(
            self.list_token_usage(task_run_id=task_run_id),
            cache_records=self.list_prompt_cache(task_run_id=task_run_id),
        )

    def summarize_tasks(self, task_run_ids: list[str] | tuple[str, ...] | set[str]) -> dict[str, dict[str, Any]]:
        targets = {str(item).strip() for item in task_run_ids if str(item).strip()}
        if not targets:
            return {}
        indexed: dict[str, dict[str, Any]] = {}
        missing: set[str] = set()
        for task_run_id in targets:
            summary = self._summary_for_key(task_run_id)
            if summary is None:
                missing.add(task_run_id)
            else:
                indexed[task_run_id] = summary
        if not missing:
            return indexed
        if not self._summary_scan_allowed():
            for task_run_id in missing:
                indexed[task_run_id] = _empty_usage_summary()
            return indexed
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
        scanned = {
            task_run_id: summarize_usage_records(
                sorted(usage_by_task.get(task_run_id) or [], key=lambda item: item.created_at),
                cache_records=sorted(cache_by_task.get(task_run_id) or [], key=lambda item: item.created_at),
            )
            for task_run_id in targets
        }
        indexed.update(scanned)
        return indexed

    def summarize_run(self, run_id: str) -> dict[str, Any]:
        indexed = self._summary_for_key(run_id)
        if indexed is not None:
            return indexed
        if not self._summary_scan_allowed():
            return _empty_usage_summary()
        return summarize_usage_records(
            self.list_token_usage(run_id=run_id),
            cache_records=self.list_prompt_cache(run_id=run_id),
        )

    def summarize_session(self, session_id: str) -> dict[str, Any]:
        normalized = str(session_id or "").strip()
        if not normalized:
            return _empty_usage_summary()
        indexed = self._summary_for_session(normalized)
        if indexed is not None:
            return indexed
        if not self._summary_scan_allowed():
            return _empty_usage_summary()
        return summarize_usage_records(
            self.list_token_usage(session_id=normalized),
            cache_records=self.list_prompt_cache(session_id=normalized),
        )

    def summarize_all(self) -> dict[str, Any]:
        return summarize_usage_records(
            self.list_token_usage(),
            cache_records=self.list_prompt_cache(),
        )

    def list_run_summaries(self, *, limit: int = 100) -> list[dict[str, Any]]:
        manifest_rows = self._read_summary_manifest()
        if not manifest_rows:
            rows: list[dict[str, Any]] = []
            for path in self.summary_index_dir.glob("*.json"):
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, JSONDecodeError):
                    continue
                if self._valid_summary_payload(payload):
                    rows.append(dict(payload))
            if rows:
                self._rewrite_summary_manifest(rows)
            manifest_rows = rows
        retained_rows = self.list_retained_token_summaries(limit=max(1, int(limit or 100)))
        combined_rows = _merge_summary_rows([*retained_rows, *manifest_rows])
        return sorted(combined_rows, key=lambda item: float(item.get("updated_at") or 0.0), reverse=True)[: max(1, int(limit or 100))]

    def list_run_summary_payloads(self, *, limit: int = 100) -> list[dict[str, Any]]:
        payloads: list[dict[str, Any]] = []
        for row in self.list_run_summaries(limit=max(1, int(limit or 100))):
            key = str(row.get("key") or row.get("task_run_id") or row.get("run_id") or "").strip()
            payload = self._read_summary_payload(key) if key else None
            payloads.append(dict(payload or row))
        return payloads

    def list_retained_token_summaries(self, *, limit: int = 100) -> list[dict[str, Any]]:
        stats = self._read_retained_token_stats()
        rows = [
            dict(item)
            for item in list(stats.get("run_summaries") or [])
            if isinstance(item, dict) and isinstance(item.get("summary"), dict)
        ]
        return sorted(rows, key=lambda item: float(item.get("updated_at") or 0.0), reverse=True)[: max(1, int(limit or 100))]

    def scoped_reads_are_expensive(self) -> bool:
        return not self._summary_scan_allowed()

    def build_hot_cache_pressure_report(self) -> dict[str, Any]:
        files: dict[str, Any] = {}
        total_bytes = 0
        legacy_bytes = 0
        hot_bucket_bytes = 0
        buckets_seen: set[str] = set()
        for filename in self.TIME_BUCKETED_DETAIL_FILES:
            paths = self._jsonl_paths(filename)
            file_rows: list[dict[str, Any]] = []
            for path in paths:
                size = _file_signature(path)[1]
                bucket = _bucket_from_hot_path(self.hot_time_dir, path) or _bucket_from_hot_path(self.hot_day_dir, path)
                total_bytes += size
                if bucket:
                    hot_bucket_bytes += size
                    buckets_seen.add(bucket)
                else:
                    legacy_bytes += size
                file_rows.append(
                    {
                        "path": str(path.relative_to(self.ledger_dir)),
                        "bucket": bucket or "legacy_root",
                        "size_bytes": size,
                        "size_mb": round(size / 1024 / 1024, 2),
                        "row_count": _jsonl_line_count(path),
                    }
                )
            files[filename] = {
                "shard_count": len(paths),
                "size_bytes": sum(int(item["size_bytes"]) for item in file_rows),
                "size_mb": round(sum(int(item["size_bytes"]) for item in file_rows) / 1024 / 1024, 2),
                "shards": file_rows,
            }
        return {
            "authority": "runtime.prompt_accounting.hot_cache_pressure",
            "layout": "hot/by_time/YYYYMMDD/HH/{ledger_file}",
            "summary": {
                "size_bytes": total_bytes,
                "size_mb": round(total_bytes / 1024 / 1024, 2),
                "legacy_root_bytes": legacy_bytes,
                "legacy_root_mb": round(legacy_bytes / 1024 / 1024, 2),
                "hot_bucket_bytes": hot_bucket_bytes,
                "hot_bucket_mb": round(hot_bucket_bytes / 1024 / 1024, 2),
                "bucket_count": len(buckets_seen),
                "oldest_bucket": min(buckets_seen) if buckets_seen else "",
                "newest_bucket": max(buckets_seen) if buckets_seen else "",
            },
            "files": files,
        }

    def rebuild_summary_index(self) -> dict[str, Any]:
        payloads: dict[str, dict[str, Any]] = {}
        usage_count = 0
        cache_count = 0
        for row in self._iter_jsonl_rows("token_usage.jsonl"):
            record = ModelTokenUsageRecord.from_dict(row)
            key = _summary_key_for_usage(record)
            if not key:
                continue
            payload = payloads.setdefault(key, _new_summary_payload(key))
            usage_records = dict(payload.get("usage_records") or {})
            usage_key = record.usage_id or f"{record.request_id}:{record.source}:{record.created_at}"
            previous = usage_records.get(usage_key)
            if previous is None or float(record.created_at or 0.0) >= float(dict(previous).get("created_at") or 0.0):
                usage_records[usage_key] = _compact_usage_record(record)
            payload["usage_records"] = usage_records
            usage_count += 1
        for row in self._iter_jsonl_rows("prompt_cache.jsonl"):
            record = PromptCacheRecord.from_dict(row)
            key = _summary_key_for_cache(record)
            if not key:
                continue
            payload = payloads.setdefault(key, _new_summary_payload(key))
            cache_records = dict(payload.get("cache_records") or {})
            cache_key = record.cache_record_id or f"{record.request_id}:{record.created_at}"
            previous = cache_records.get(cache_key)
            if previous is None or float(record.created_at or 0.0) >= float(dict(previous).get("created_at") or 0.0):
                cache_records[cache_key] = _compact_cache_record(record)
            payload["cache_records"] = cache_records
            cache_count += 1
        with self._lock:
            for existing in self.summary_index_dir.glob("*.json"):
                try:
                    existing.unlink()
                except OSError:
                    continue
            for key, payload in payloads.items():
                self._rewrite_summary_payload(key, payload, update_manifest=False)
            self._rewrite_summary_manifest(payloads.values())
        return {
            "authority": "runtime.prompt_accounting.summary_index_rebuild",
            "summary_key_count": len(payloads),
            "token_usage_rows_scanned": usage_count,
            "prompt_cache_rows_scanned": cache_count,
        }

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
            "summary_index": self._delete_summary_keys(targets),
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
            "summary_index": self._delete_summary_session_or_tasks(normalized, targets),
            "context_usage_latest": self._delete_context_usage_snapshot(normalized),
        }
        return {
            "authority": "runtime.prompt_accounting.ledger.prune_session",
            "session_id": normalized,
            "requested_task_run_ids": sorted(targets),
            "deleted_counts": {key: value for key, value in deleted_counts.items() if value},
        }

    def build_retention_preview(
        self,
        *,
        cutoff_days: int = DEFAULT_DETAIL_RETENTION_DAYS,
        now: float | None = None,
        protected_task_run_ids: set[str] | list[str] | tuple[str, ...] = (),
        protected_session_ids: set[str] | list[str] | tuple[str, ...] = (),
    ) -> dict[str, Any]:
        timestamp = time.time() if now is None else float(now)
        cutoff_timestamp = self._retention_cutoff_timestamp(cutoff_days=cutoff_days, now=timestamp)
        protection = self._retention_protection(
            protected_task_run_ids=protected_task_run_ids,
            protected_session_ids=protected_session_ids,
        )
        plan = self._build_retention_plan(cutoff_timestamp=cutoff_timestamp, protection=protection, now=timestamp)
        return self._retention_response(plan=plan, mode="preflight", now=timestamp)

    def compact_before(
        self,
        *,
        cutoff_days: int = DEFAULT_DETAIL_RETENTION_DAYS,
        dry_run: bool = True,
        now: float | None = None,
        protected_task_run_ids: set[str] | list[str] | tuple[str, ...] = (),
        protected_session_ids: set[str] | list[str] | tuple[str, ...] = (),
    ) -> dict[str, Any]:
        timestamp = time.time() if now is None else float(now)
        cutoff_timestamp = self._retention_cutoff_timestamp(cutoff_days=cutoff_days, now=timestamp)
        protection = self._retention_protection(
            protected_task_run_ids=protected_task_run_ids,
            protected_session_ids=protected_session_ids,
        )
        plan = self._build_retention_plan(cutoff_timestamp=cutoff_timestamp, protection=protection, now=timestamp)
        mode = "dry_run" if dry_run else "execute"
        result = self._retention_response(plan=plan, mode=mode, now=timestamp)
        if dry_run:
            return result

        with self._lock:
            existing_stats = self._read_retained_token_stats()
            merged_stats = self._merge_retained_token_stats(
                existing_stats,
                list(plan["cold_token_stats"].get("run_summaries") or []),
                policy=dict(plan.get("policy") or {}),
                now=timestamp,
            )
            self._write_retained_token_stats(merged_stats)
            rewrite_results = self._execute_retention_rewrites(plan=plan, cutoff_timestamp=cutoff_timestamp)
            rebuild = self.rebuild_summary_index()
            receipt = self._retention_receipt(
                plan=plan,
                rewrite_results=rewrite_results,
                stats=merged_stats,
                now=timestamp,
            )
            self._append_retention_receipt(receipt)

        result["rewrite_results"] = rewrite_results
        result["summary_index_rebuild"] = rebuild
        result["retained_token_stats"] = {
            "path": str(self.retained_token_stats_path),
            "run_summary_count": int(merged_stats.get("run_summary_count") or 0),
            "summary": dict(merged_stats.get("summary") or {}),
            "checksum": str(merged_stats.get("checksum") or ""),
        }
        result["retention_receipt"] = receipt
        return result

    def _retention_cutoff_timestamp(self, *, cutoff_days: int, now: float) -> float:
        days = max(1, int(cutoff_days or self.DEFAULT_DETAIL_RETENTION_DAYS))
        return float(now) - float(days * 24 * 60 * 60)

    def _retention_protection(
        self,
        *,
        protected_task_run_ids: set[str] | list[str] | tuple[str, ...],
        protected_session_ids: set[str] | list[str] | tuple[str, ...],
    ) -> dict[str, set[str]]:
        protected_keys = {
            str(item).strip()
            for item in list(protected_task_run_ids or [])
            if str(item).strip()
        }
        protected_sessions = {
            str(item).strip()
            for item in list(protected_session_ids or [])
            if str(item).strip()
        }
        return {
            "keys": protected_keys,
            "sessions": protected_sessions,
        }

    def _build_retention_plan(self, *, cutoff_timestamp: float, protection: dict[str, set[str]], now: float) -> dict[str, Any]:
        usage_plan = self._token_usage_retention_plan(cutoff_timestamp=cutoff_timestamp, protection=protection)
        cache_plan = self._prompt_cache_retention_plan(cutoff_timestamp=cutoff_timestamp, protection=protection)
        retained_request_ids = set(usage_plan.get("retained_request_ids") or set()) | set(cache_plan.get("retained_request_ids") or set())
        cold_stats = self._cold_token_stats_from_plans(
            usage_by_key=dict(usage_plan.get("usage_by_key") or {}),
            cache_by_key=dict(cache_plan.get("cache_by_key") or {}),
            cutoff_timestamp=cutoff_timestamp,
            now=now,
        )
        generic_files: dict[str, dict[str, Any]] = {}
        for filename in self.RETENTION_DETAIL_FILES:
            if filename in {"token_usage.jsonl", "prompt_cache.jsonl"}:
                continue
            generic_files[filename] = self._generic_detail_retention_plan(
                filename,
                cutoff_timestamp=cutoff_timestamp,
                protection=protection,
                retained_request_ids=retained_request_ids,
            )
        files = {
            "token_usage.jsonl": dict(usage_plan.get("preview") or {}),
            "prompt_cache.jsonl": dict(cache_plan.get("preview") or {}),
            **{filename: dict(plan.get("preview") or {}) for filename, plan in generic_files.items()},
        }
        compactable_rows = sum(int(item.get("compactable_rows") or 0) for item in files.values())
        return {
            "authority": "runtime.prompt_accounting.retention_plan",
            "policy": {
                "authority": "runtime.prompt_accounting.retention_policy",
                "detail_retention_days": max(1, int((now - cutoff_timestamp) // (24 * 60 * 60))),
                "cutoff_timestamp": cutoff_timestamp,
                "requires_token_stats_before_detail_prune": True,
                "detail_files": list(self.RETENTION_DETAIL_FILES),
                "state_files_retained": ["prompt_cache_baselines.jsonl"],
                "protected_task_run_ids": sorted(protection.get("keys") or set()),
                "protected_session_ids": sorted(protection.get("sessions") or set()),
            },
            "files": files,
            "usage_plan": usage_plan,
            "cache_plan": cache_plan,
            "generic_files": generic_files,
            "cold_token_stats": cold_stats,
            "summary": {
                "file_count": len(files),
                "rows_scanned": sum(int(item.get("rows_scanned") or 0) for item in files.values()),
                "compactable_detail_rows": compactable_rows,
                "protected_rows": sum(int(item.get("protected_rows") or 0) for item in files.values()),
                "undated_rows_kept": sum(int(item.get("undated_rows_kept") or 0) for item in files.values()),
                "malformed_rows_kept": sum(int(item.get("malformed_rows_kept") or 0) for item in files.values()),
                "retained_token_run_summary_count": int(cold_stats.get("run_summary_count") or 0),
            },
        }

    def _token_usage_retention_plan(self, *, cutoff_timestamp: float, protection: dict[str, set[str]]) -> dict[str, Any]:
        filename = "token_usage.jsonl"
        paths = self._jsonl_paths(filename)
        groups: dict[str, dict[str, Any]] = {}
        rows_scanned = 0
        malformed_rows = 0
        for path in paths:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        row = json.loads(stripped)
                    except JSONDecodeError:
                        malformed_rows += 1
                        continue
                    if not isinstance(row, dict):
                        malformed_rows += 1
                        continue
                    rows_scanned += 1
                    record = ModelTokenUsageRecord.from_dict(row)
                    summary_key = _summary_key_for_usage(record)
                    group_id = _retention_group_id(row, primary_fields=("request_id", "usage_id"))
                    group = groups.setdefault(
                        group_id,
                        {
                            "rows": [],
                            "row_count": 0,
                            "summary_keys": set(),
                            "request_ids": set(),
                            "keep": False,
                            "protected": False,
                            "undated": False,
                            "unkeyed": False,
                        },
                    )
                    group["row_count"] = int(group["row_count"]) + 1
                    group["rows"].append(_compact_usage_record(record))
                    if summary_key:
                        group["summary_keys"].add(summary_key)
                    else:
                        group["unkeyed"] = True
                        group["keep"] = True
                    if record.request_id:
                        group["request_ids"].add(record.request_id)
                    if _row_is_retention_protected(row, protection=protection):
                        group["protected"] = True
                        group["keep"] = True
                    if float(record.created_at or 0.0) <= 0:
                        group["undated"] = True
                        group["keep"] = True
                    elif float(record.created_at or 0.0) >= cutoff_timestamp:
                        group["keep"] = True
        usage_by_key: dict[str, list[dict[str, Any]]] = {}
        compact_group_ids: set[str] = set()
        retained_request_ids: set[str] = set()
        kept_rows = 0
        compactable_rows = 0
        protected_rows = 0
        undated_rows = 0
        unkeyed_rows = 0
        for group_id, group in groups.items():
            row_count = int(group.get("row_count") or 0)
            if group.get("protected"):
                protected_rows += row_count
            if group.get("undated"):
                undated_rows += row_count
            if group.get("unkeyed"):
                unkeyed_rows += row_count
            if group.get("keep"):
                kept_rows += row_count
                retained_request_ids.update(str(item) for item in set(group.get("request_ids") or set()) if str(item))
                continue
            summary_keys = sorted(str(item) for item in set(group.get("summary_keys") or set()) if str(item))
            if not summary_keys:
                kept_rows += row_count
                continue
            summary_key = summary_keys[0]
            compact_group_ids.add(group_id)
            compactable_rows += row_count
            usage_by_key.setdefault(summary_key, []).extend(dict(item) for item in list(group.get("rows") or []))
        return {
            "filename": filename,
            "drop_group_ids": compact_group_ids,
            "retained_request_ids": retained_request_ids,
            "usage_by_key": usage_by_key,
            "preview": {
                "filename": filename,
                "exists": bool(paths),
                "shard_count": len(paths),
                "size_bytes": self._jsonl_size_bytes(filename),
                "rows_scanned": rows_scanned,
                "kept_rows": kept_rows + malformed_rows,
                "compactable_rows": compactable_rows,
                "protected_rows": protected_rows,
                "undated_rows_kept": undated_rows,
                "unkeyed_rows_kept": unkeyed_rows,
                "malformed_rows_kept": malformed_rows,
                "rewrite_required": compactable_rows > 0,
            },
        }

    def _prompt_cache_retention_plan(self, *, cutoff_timestamp: float, protection: dict[str, set[str]]) -> dict[str, Any]:
        filename = "prompt_cache.jsonl"
        paths = self._jsonl_paths(filename)
        groups: dict[str, dict[str, Any]] = {}
        rows_scanned = 0
        malformed_rows = 0
        for path in paths:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        row = json.loads(stripped)
                    except JSONDecodeError:
                        malformed_rows += 1
                        continue
                    if not isinstance(row, dict):
                        malformed_rows += 1
                        continue
                    rows_scanned += 1
                    record = PromptCacheRecord.from_dict(row)
                    summary_key = _summary_key_for_cache(record)
                    group_id = _retention_group_id(row, primary_fields=("request_id", "cache_record_id"))
                    group = groups.setdefault(
                        group_id,
                        {
                            "rows": [],
                            "row_count": 0,
                            "summary_keys": set(),
                            "request_ids": set(),
                            "keep": False,
                            "protected": False,
                            "undated": False,
                            "unkeyed": False,
                        },
                    )
                    group["row_count"] = int(group["row_count"]) + 1
                    group["rows"].append(_compact_cache_record(record))
                    if summary_key:
                        group["summary_keys"].add(summary_key)
                    else:
                        group["unkeyed"] = True
                        group["keep"] = True
                    if record.request_id:
                        group["request_ids"].add(record.request_id)
                    if _row_is_retention_protected(row, protection=protection):
                        group["protected"] = True
                        group["keep"] = True
                    if float(record.created_at or 0.0) <= 0:
                        group["undated"] = True
                        group["keep"] = True
                    elif float(record.created_at or 0.0) >= cutoff_timestamp:
                        group["keep"] = True
        cache_by_key: dict[str, list[dict[str, Any]]] = {}
        compact_group_ids: set[str] = set()
        retained_request_ids: set[str] = set()
        kept_rows = 0
        compactable_rows = 0
        protected_rows = 0
        undated_rows = 0
        unkeyed_rows = 0
        for group_id, group in groups.items():
            row_count = int(group.get("row_count") or 0)
            if group.get("protected"):
                protected_rows += row_count
            if group.get("undated"):
                undated_rows += row_count
            if group.get("unkeyed"):
                unkeyed_rows += row_count
            if group.get("keep"):
                kept_rows += row_count
                retained_request_ids.update(str(item) for item in set(group.get("request_ids") or set()) if str(item))
                continue
            summary_keys = sorted(str(item) for item in set(group.get("summary_keys") or set()) if str(item))
            if not summary_keys:
                kept_rows += row_count
                continue
            summary_key = summary_keys[0]
            compact_group_ids.add(group_id)
            compactable_rows += row_count
            cache_by_key.setdefault(summary_key, []).extend(dict(item) for item in list(group.get("rows") or []))
        return {
            "filename": filename,
            "drop_group_ids": compact_group_ids,
            "retained_request_ids": retained_request_ids,
            "cache_by_key": cache_by_key,
            "preview": {
                "filename": filename,
                "exists": bool(paths),
                "shard_count": len(paths),
                "size_bytes": self._jsonl_size_bytes(filename),
                "rows_scanned": rows_scanned,
                "kept_rows": kept_rows + malformed_rows,
                "compactable_rows": compactable_rows,
                "protected_rows": protected_rows,
                "undated_rows_kept": undated_rows,
                "unkeyed_rows_kept": unkeyed_rows,
                "malformed_rows_kept": malformed_rows,
                "rewrite_required": compactable_rows > 0,
            },
        }

    def _generic_detail_retention_plan(
        self,
        filename: str,
        *,
        cutoff_timestamp: float,
        protection: dict[str, set[str]],
        retained_request_ids: set[str],
    ) -> dict[str, Any]:
        paths = self._jsonl_paths(filename)
        rows_scanned = 0
        kept_rows = 0
        compactable_rows = 0
        protected_rows = 0
        undated_rows = 0
        malformed_rows = 0
        for path in paths:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        row = json.loads(stripped)
                    except JSONDecodeError:
                        malformed_rows += 1
                        kept_rows += 1
                        continue
                    if not isinstance(row, dict):
                        malformed_rows += 1
                        kept_rows += 1
                        continue
                    rows_scanned += 1
                    decision = _row_retention_decision(
                        row,
                        cutoff_timestamp=cutoff_timestamp,
                        protection=protection,
                        retained_request_ids=retained_request_ids,
                    )
                    if decision == "compact":
                        compactable_rows += 1
                    else:
                        kept_rows += 1
                        if decision == "protected":
                            protected_rows += 1
                        elif decision == "undated":
                            undated_rows += 1
        return {
            "filename": filename,
            "preview": {
                "filename": filename,
                "exists": bool(paths),
                "shard_count": len(paths),
                "size_bytes": self._jsonl_size_bytes(filename),
                "rows_scanned": rows_scanned,
                "kept_rows": kept_rows,
                "compactable_rows": compactable_rows,
                "protected_rows": protected_rows,
                "undated_rows_kept": undated_rows,
                "malformed_rows_kept": malformed_rows,
                "rewrite_required": compactable_rows > 0,
            },
        }

    def _cold_token_stats_from_plans(
        self,
        *,
        usage_by_key: dict[str, list[dict[str, Any]]],
        cache_by_key: dict[str, list[dict[str, Any]]],
        cutoff_timestamp: float,
        now: float,
    ) -> dict[str, Any]:
        entries: list[dict[str, Any]] = []
        for key in sorted(set(usage_by_key) | set(cache_by_key)):
            entry = _summary_entry_from_compact_records(
                key,
                usage_records=list(usage_by_key.get(key) or []),
                cache_records=list(cache_by_key.get(key) or []),
                authority="runtime.prompt_accounting.retained_token_summary",
            )
            summary = dict(entry.get("summary") or {})
            if int(summary.get("record_count") or 0) <= 0 and int(summary.get("cache_record_count") or 0) <= 0:
                continue
            entries.append(entry)
        summary = _aggregate_summary_entries(entries)
        return {
            "authority": "runtime.prompt_accounting.retention_cold_token_stats",
            "version": self.RETAINED_TOKEN_STATS_VERSION,
            "cutoff_timestamp": cutoff_timestamp,
            "created_at": now,
            "run_summary_count": len(entries),
            "usage_rows_compacted": sum(len(list(value or [])) for value in usage_by_key.values()),
            "cache_rows_compacted": sum(len(list(value or [])) for value in cache_by_key.values()),
            "summary": summary,
            "daily": _daily_token_stats(entries),
            "run_summaries": sorted(entries, key=lambda item: float(item.get("updated_at") or 0.0), reverse=True),
            "sample_run_summaries": sorted(entries, key=lambda item: float(item.get("updated_at") or 0.0), reverse=True)[:20],
            "checksum": _json_checksum(entries),
        }

    def _retention_response(self, *, plan: dict[str, Any], mode: str, now: float) -> dict[str, Any]:
        cold_stats = dict(plan.get("cold_token_stats") or {})
        return {
            "authority": "runtime.prompt_accounting.retention",
            "mode": mode,
            "policy": dict(plan.get("policy") or {}),
            "summary": dict(plan.get("summary") or {}),
            "files": dict(plan.get("files") or {}),
            "cold_token_stats": {
                "authority": str(cold_stats.get("authority") or ""),
                "version": int(cold_stats.get("version") or self.RETAINED_TOKEN_STATS_VERSION),
                "run_summary_count": int(cold_stats.get("run_summary_count") or 0),
                "usage_rows_compacted": int(cold_stats.get("usage_rows_compacted") or 0),
                "cache_rows_compacted": int(cold_stats.get("cache_rows_compacted") or 0),
                "summary": dict(cold_stats.get("summary") or {}),
                "daily": list(cold_stats.get("daily") or []),
                "sample_run_summaries": list(cold_stats.get("sample_run_summaries") or []),
                "checksum": str(cold_stats.get("checksum") or ""),
            },
            "retained_token_stats_path": str(self.retained_token_stats_path),
            "retention_receipts_path": str(self.retention_receipts_path),
            "updated_at": now,
        }

    def _execute_retention_rewrites(self, *, plan: dict[str, Any], cutoff_timestamp: float) -> dict[str, Any]:
        protection = {
            "keys": set(dict(plan.get("policy") or {}).get("protected_task_run_ids") or []),
            "sessions": set(dict(plan.get("policy") or {}).get("protected_session_ids") or []),
        }
        retained_request_ids = (
            set(dict(plan.get("usage_plan") or {}).get("retained_request_ids") or set())
            | set(dict(plan.get("cache_plan") or {}).get("retained_request_ids") or set())
        )
        results = {
            "token_usage.jsonl": self._rewrite_jsonl_dropping_groups(
                "token_usage.jsonl",
                drop_group_ids=set(dict(plan.get("usage_plan") or {}).get("drop_group_ids") or set()),
                primary_fields=("request_id", "usage_id"),
            ),
            "prompt_cache.jsonl": self._rewrite_jsonl_dropping_groups(
                "prompt_cache.jsonl",
                drop_group_ids=set(dict(plan.get("cache_plan") or {}).get("drop_group_ids") or set()),
                primary_fields=("request_id", "cache_record_id"),
            ),
        }
        for filename in dict(plan.get("generic_files") or {}):
            results[filename] = self._rewrite_jsonl_for_retention(
                filename,
                cutoff_timestamp=cutoff_timestamp,
                protection=protection,
                retained_request_ids=retained_request_ids,
            )
        return {
            "authority": "runtime.prompt_accounting.retention_rewrite",
            "files": results,
            "deleted_counts": {
                filename.removesuffix(".jsonl"): int(result.get("deleted_rows") or 0)
                for filename, result in results.items()
                if int(result.get("deleted_rows") or 0) > 0
            },
        }

    def _rewrite_jsonl_dropping_groups(
        self,
        filename: str,
        *,
        drop_group_ids: set[str],
        primary_fields: tuple[str, ...],
    ) -> dict[str, Any]:
        paths = self._jsonl_paths(filename)
        if not paths or not drop_group_ids:
            return {
                "filename": filename,
                "exists": bool(paths),
                "shard_count": len(paths),
                "kept_rows": 0,
                "deleted_rows": 0,
                "malformed_rows_kept": 0,
                "rewritten": False,
            }
        kept_rows = 0
        deleted_rows = 0
        malformed_rows = 0
        rewritten = False
        for path in paths:
            result = self._rewrite_jsonl_path(
                path,
                should_delete=lambda row: _retention_group_id(row, primary_fields=primary_fields) in drop_group_ids,
            )
            kept_rows += int(result.get("kept_rows") or 0)
            deleted_rows += int(result.get("deleted_rows") or 0)
            malformed_rows += int(result.get("malformed_rows_kept") or 0)
            rewritten = rewritten or bool(result.get("rewritten") is True)
        self._invalidate_filtered_read_cache(filename)
        return {
            "filename": filename,
            "exists": True,
            "shard_count": len(paths),
            "kept_rows": kept_rows,
            "deleted_rows": deleted_rows,
            "malformed_rows_kept": malformed_rows,
            "rewritten": rewritten,
        }

    def _rewrite_jsonl_for_retention(
        self,
        filename: str,
        *,
        cutoff_timestamp: float,
        protection: dict[str, set[str]],
        retained_request_ids: set[str],
    ) -> dict[str, Any]:
        paths = self._jsonl_paths(filename)
        if not paths:
            return {
                "filename": filename,
                "exists": False,
                "shard_count": 0,
                "kept_rows": 0,
                "deleted_rows": 0,
                "malformed_rows_kept": 0,
                "rewritten": False,
            }
        kept_rows = 0
        deleted_rows = 0
        malformed_rows = 0
        rewritten = False
        for path in paths:
            result = self._rewrite_jsonl_path(
                path,
                should_delete=lambda row: _row_retention_decision(
                    row,
                    cutoff_timestamp=cutoff_timestamp,
                    protection=protection,
                    retained_request_ids=retained_request_ids,
                )
                == "compact",
            )
            kept_rows += int(result.get("kept_rows") or 0)
            deleted_rows += int(result.get("deleted_rows") or 0)
            malformed_rows += int(result.get("malformed_rows_kept") or 0)
            rewritten = rewritten or bool(result.get("rewritten") is True)
        self._invalidate_filtered_read_cache(filename)
        return {
            "filename": filename,
            "exists": True,
            "shard_count": len(paths),
            "kept_rows": kept_rows,
            "deleted_rows": deleted_rows,
            "malformed_rows_kept": malformed_rows,
            "rewritten": rewritten,
        }

    def _read_retained_token_stats(self) -> dict[str, Any]:
        path = self.retained_token_stats_path
        signature = _file_signature(path)
        cached = self._retained_token_stats_cache
        if cached is not None and cached[0] == signature:
            return dict(cached[1])
        if not path.exists():
            payload = _empty_retained_token_stats(version=self.RETAINED_TOKEN_STATS_VERSION)
            self._retained_token_stats_cache = (signature, dict(payload))
            return payload
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, JSONDecodeError):
            payload = _empty_retained_token_stats(version=self.RETAINED_TOKEN_STATS_VERSION)
        if not isinstance(payload, dict) or int(payload.get("version") or 0) != self.RETAINED_TOKEN_STATS_VERSION:
            payload = _empty_retained_token_stats(version=self.RETAINED_TOKEN_STATS_VERSION)
        self._retained_token_stats_cache = (signature, dict(payload))
        return dict(payload)

    def _write_retained_token_stats(self, payload: dict[str, Any]) -> None:
        self.retention_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = self.retained_token_stats_path.with_suffix(f"{self.retained_token_stats_path.suffix}.{threading.get_ident()}.tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        tmp_path.replace(self.retained_token_stats_path)
        self._retained_token_stats_cache = (_file_signature(self.retained_token_stats_path), dict(payload))

    def _retained_summary_payload_for_key(self, key: str) -> dict[str, Any] | None:
        normalized = str(key or "").strip()
        if not normalized:
            return None
        for payload in list(self._read_retained_token_stats().get("run_summaries") or []):
            if not isinstance(payload, dict):
                continue
            keys = {
                str(payload.get("key") or ""),
                str(payload.get("task_run_id") or ""),
                str(payload.get("run_id") or ""),
            }
            if normalized in keys:
                return dict(payload)
        return None

    def _merge_retained_token_stats(
        self,
        existing: dict[str, Any],
        additions: list[dict[str, Any]],
        *,
        policy: dict[str, Any],
        now: float,
    ) -> dict[str, Any]:
        rows = _merge_summary_rows([
            *[
                dict(item)
                for item in list(existing.get("run_summaries") or [])
                if isinstance(item, dict)
            ],
            *[dict(item) for item in additions if isinstance(item, dict)],
        ])
        payload = {
            "authority": "runtime.prompt_accounting.retained_token_stats",
            "version": self.RETAINED_TOKEN_STATS_VERSION,
            "retention_policy": dict(policy or {}),
            "updated_at": now,
            "run_summary_count": len(rows),
            "summary": _aggregate_summary_entries(rows),
            "daily": _daily_token_stats(rows),
            "run_summaries": sorted(rows, key=lambda item: float(item.get("updated_at") or 0.0), reverse=True),
        }
        payload["checksum"] = _json_checksum(payload["run_summaries"])
        return payload

    def _retention_receipt(
        self,
        *,
        plan: dict[str, Any],
        rewrite_results: dict[str, Any],
        stats: dict[str, Any],
        now: float,
    ) -> dict[str, Any]:
        deleted_counts = dict(dict(rewrite_results or {}).get("deleted_counts") or {})
        checksum_input = {
            "policy": dict(plan.get("policy") or {}),
            "deleted_counts": deleted_counts,
            "stats_checksum": str(stats.get("checksum") or ""),
        }
        return {
            "authority": "runtime.prompt_accounting.retention_receipt",
            "receipt_id": f"prompt-accounting-retention:{int(now * 1000)}",
            "command_ref": "health-system/prompt-accounting/retention/compact",
            "status": "completed",
            "created_at": now,
            "policy": dict(plan.get("policy") or {}),
            "summary": dict(plan.get("summary") or {}),
            "deleted_counts": deleted_counts,
            "retained_token_stats": {
                "path": str(self.retained_token_stats_path),
                "run_summary_count": int(stats.get("run_summary_count") or 0),
                "checksum": str(stats.get("checksum") or ""),
            },
            "checksum": _json_checksum(checksum_input),
        }

    def _append_retention_receipt(self, receipt: dict[str, Any]) -> None:
        self.retention_dir.mkdir(parents=True, exist_ok=True)
        with self.retention_receipts_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(receipt, ensure_ascii=False, sort_keys=True) + "\n")

    def _append_jsonl(self, filename: str, payload: dict[str, Any]) -> None:
        path = self._append_jsonl_path(filename, payload)
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
            self._invalidate_filtered_read_cache(filename)

    def _summary_for_key(self, key: str) -> dict[str, Any] | None:
        normalized = str(key or "").strip()
        if not normalized:
            return None
        with self._lock:
            payload = self._read_summary_payload(normalized)
        retained = self._retained_summary_payload_for_key(normalized)
        if payload is None and retained is None:
            return None
        if payload is None:
            return dict(dict(retained or {}).get("summary") or _empty_usage_summary())
        if retained is None:
            return dict(payload.get("summary") or _empty_usage_summary())
        merged = _merge_summary_rows([dict(retained), _summary_manifest_entry(payload)])
        if not merged:
            return _empty_usage_summary()
        return dict(merged[0].get("summary") or _empty_usage_summary())

    def _summary_for_session(self, session_id: str) -> dict[str, Any] | None:
        normalized = str(session_id or "").strip()
        if not normalized:
            return None
        entries = [
            dict(item)
            for item in [*self.list_retained_token_summaries(limit=10_000), *self._read_summary_manifest()]
            if str(item.get("session_id") or "") == normalized
        ]
        if not entries:
            return None
        merged = _merge_summary_rows(entries)
        if not merged:
            return _empty_usage_summary()
        return _aggregate_summary_entries(merged)

    def _upsert_usage_summary(self, record: ModelTokenUsageRecord) -> None:
        key = _summary_key_for_usage(record)
        if not key:
            return
        with self._lock:
            payload = self._read_summary_payload(key) or _new_summary_payload(key)
            usage_records = dict(payload.get("usage_records") or {})
            usage_key = record.usage_id or f"{record.request_id}:{record.source}:{record.created_at}"
            previous = usage_records.get(usage_key)
            if previous is None or float(record.created_at or 0.0) >= float(dict(previous).get("created_at") or 0.0):
                usage_records[usage_key] = _compact_usage_record(record)
            payload["usage_records"] = usage_records
            self._rewrite_summary_payload(key, payload)

    def _upsert_cache_summary(self, record: PromptCacheRecord) -> None:
        key = _summary_key_for_cache(record)
        if not key:
            return
        with self._lock:
            payload = self._read_summary_payload(key) or _new_summary_payload(key)
            cache_records = dict(payload.get("cache_records") or {})
            cache_key = record.cache_record_id or f"{record.request_id}:{record.created_at}"
            previous = cache_records.get(cache_key)
            if previous is None or float(record.created_at or 0.0) >= float(dict(previous).get("created_at") or 0.0):
                cache_records[cache_key] = _compact_cache_record(record)
            payload["cache_records"] = cache_records
            self._rewrite_summary_payload(key, payload)

    def _rewrite_summary_payload(self, key: str, payload: dict[str, Any], *, update_manifest: bool = True) -> None:
        normalized = str(key or "").strip()
        if not normalized:
            return
        usage_records = [
            ModelTokenUsageRecord.from_dict(dict(item))
            for item in dict(payload.get("usage_records") or {}).values()
        ]
        cache_records = [
            PromptCacheRecord.from_dict(dict(item))
            for item in dict(payload.get("cache_records") or {}).values()
        ]
        sorted_usage = sorted(usage_records, key=lambda item: float(item.created_at or 0.0))
        sorted_cache = sorted(cache_records, key=lambda item: float(item.created_at or 0.0))
        timeline = list(sorted_usage) + list(sorted_cache)
        first = min(timeline, key=lambda item: float(getattr(item, "created_at", 0.0) or 0.0), default=None)
        last = max(timeline, key=lambda item: float(getattr(item, "created_at", 0.0) or 0.0), default=None)
        summary = summarize_usage_records(sorted_usage, cache_records=sorted_cache)
        payload = {
            "authority": "runtime.prompt_accounting.summary_index",
            "version": self.SUMMARY_INDEX_VERSION,
            "key": normalized,
            "summary": summary,
            "usage_records": {
                record.usage_id or f"{record.request_id}:{record.source}:{record.created_at}": _compact_usage_record(record)
                for record in sorted_usage
            },
            "cache_records": {
                record.cache_record_id or f"{record.request_id}:{record.created_at}": _compact_cache_record(record)
                for record in sorted_cache
            },
            "record_count": int(summary.get("record_count") or 0),
            "task_run_id": str(getattr(last, "task_run_id", "") or getattr(first, "task_run_id", "") or ""),
            "run_id": str(getattr(last, "run_id", "") or getattr(first, "run_id", "") or normalized),
            "session_id": str(getattr(last, "session_id", "") or getattr(first, "session_id", "") or ""),
            "provider": str(getattr(last, "provider", "") or getattr(first, "provider", "") or ""),
            "model": str(getattr(last, "model", "") or getattr(first, "model", "") or ""),
            "created_at": float(getattr(first, "created_at", 0.0) or 0.0),
            "updated_at": float(getattr(last, "created_at", 0.0) or 0.0),
        }
        path = self._summary_index_path(normalized)
        tmp_path = path.with_suffix(f"{path.suffix}.{threading.get_ident()}.tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        tmp_path.replace(path)
        if update_manifest:
            self._upsert_summary_manifest_entry(payload)

    def _bootstrap_context_usage_latest_from_summary_index(self) -> None:
        try:
            payloads = self.list_run_summary_payloads(limit=2000)
        except Exception:
            return
        records: list[ModelTokenUsageRecord] = []
        for payload in list(payloads or []):
            usage_records = dict(dict(payload or {}).get("usage_records") or {})
            for item in usage_records.values():
                if not isinstance(item, dict):
                    continue
                try:
                    record = ModelTokenUsageRecord.from_dict(dict(item))
                except Exception:
                    continue
                if not str(record.session_id or "").strip():
                    continue
                if int(record.prompt_tokens or record.total_tokens or 0) <= 0:
                    continue
                records.append(record)
        for record in sorted(records, key=lambda item: float(item.created_at or 0.0)):
            try:
                self.record_context_usage_snapshot(
                    record,
                    request_started_at=float(record.created_at or 0.0),
                    observed_at=float(record.created_at or 0.0),
                )
            except Exception:
                continue

    def _read_summary_payload(self, key: str) -> dict[str, Any] | None:
        path = self._summary_index_path(key)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, JSONDecodeError):
            return None
        if not self._valid_summary_payload(payload):
            return None
        return dict(payload)

    def _read_summary_manifest(self) -> list[dict[str, Any]]:
        path = self.summary_index_manifest_path
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, JSONDecodeError):
            return []
        if not isinstance(payload, dict):
            return []
        if int(payload.get("version") or 0) != self.SUMMARY_INDEX_VERSION:
            return []
        rows = payload.get("summaries")
        if not isinstance(rows, list):
            return []
        return [dict(item) for item in rows if isinstance(item, dict) and isinstance(item.get("summary"), dict)]

    def _upsert_summary_manifest_entry(self, payload: dict[str, Any]) -> None:
        rows = {
            str(item.get("key") or ""): dict(item)
            for item in self._read_summary_manifest()
            if str(item.get("key") or "")
        }
        key = str(payload.get("key") or "")
        if not key:
            return
        rows[key] = _summary_manifest_entry(payload)
        self._rewrite_summary_manifest(rows.values())

    def _rewrite_summary_manifest(self, payloads: Any) -> None:
        rows = [_summary_manifest_entry(dict(payload)) for payload in payloads]
        manifest = {
            "authority": "runtime.prompt_accounting.summary_index_manifest",
            "version": self.SUMMARY_INDEX_VERSION,
            "summary_count": len(rows),
            "summaries": sorted(rows, key=lambda item: float(item.get("updated_at") or 0.0), reverse=True),
        }
        self.summary_index_manifest_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.summary_index_manifest_path.with_suffix(f"{self.summary_index_manifest_path.suffix}.{threading.get_ident()}.tmp")
        tmp_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        tmp_path.replace(self.summary_index_manifest_path)

    def _valid_summary_payload(self, payload: Any) -> bool:
        if not isinstance(payload, dict):
            return False
        if int(payload.get("version") or 0) != self.SUMMARY_INDEX_VERSION:
            return False
        summary = payload.get("summary")
        return isinstance(summary, dict)

    def _summary_index_path(self, key: str) -> Path:
        digest = hashlib.sha256(str(key or "").encode("utf-8")).hexdigest()
        return self.summary_index_dir / f"{digest}.json"

    def _context_usage_snapshot_path(self, session_id: str) -> Path:
        digest = hashlib.sha256(str(session_id or "").encode("utf-8")).hexdigest()
        return self.context_usage_latest_dir / f"{digest}.json"

    def _delete_context_usage_snapshot(self, session_id: str) -> int:
        normalized = str(session_id or "").strip()
        if not normalized:
            return 0
        path = self._context_usage_snapshot_path(normalized)
        if not path.exists():
            return 0
        try:
            path.unlink()
        except OSError:
            return 0
        return 1

    @staticmethod
    def _read_context_usage_snapshot_path(path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        if str(payload.get("authority") or "") != "runtime.prompt_accounting.latest_context_usage_snapshot":
            return None
        return payload

    def _summary_scan_allowed(self) -> bool:
        total = 0
        for filename in ("token_usage.jsonl", "prompt_cache.jsonl", "segment_maps.jsonl"):
            total += self._jsonl_size_bytes(filename)
            if total > self.SUMMARY_SCAN_MAX_BYTES:
                return False
        return True

    def _delete_summary_keys(self, keys: set[str]) -> int:
        deleted = 0
        with self._lock:
            for key in {str(item).strip() for item in keys if str(item).strip()}:
                path = self._summary_index_path(key)
                if not path.exists():
                    continue
                try:
                    path.unlink()
                    deleted += 1
                except OSError:
                    continue
            self._rewrite_summary_manifest(
                payload
                for payload in self._read_summary_manifest()
                if str(payload.get("key") or "") not in keys
            )
        return deleted

    def _delete_summary_session_or_tasks(self, session_id: str, task_run_ids: set[str]) -> int:
        deleted = 0
        targets = {str(item).strip() for item in task_run_ids if str(item).strip()}
        normalized_session = str(session_id or "").strip()
        with self._lock:
            for path in self.summary_index_dir.glob("*.json"):
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, JSONDecodeError):
                    continue
                if not self._valid_summary_payload(payload):
                    continue
                payload_key = str(payload.get("key") or "")
                payload_task_run_id = str(payload.get("task_run_id") or "")
                payload_run_id = str(payload.get("run_id") or "")
                payload_session_id = str(payload.get("session_id") or "")
                if payload_key in targets or payload_task_run_id in targets or payload_run_id in targets or (normalized_session and payload_session_id == normalized_session):
                    try:
                        path.unlink()
                        deleted += 1
                    except OSError:
                        continue
            self._rewrite_summary_manifest(
                payload
                for payload in self._read_summary_manifest()
                if str(payload.get("key") or "") not in targets
                and str(payload.get("task_run_id") or "") not in targets
                and str(payload.get("run_id") or "") not in targets
                and not (normalized_session and str(payload.get("session_id") or "") == normalized_session)
            )
        return deleted

    def _append_jsonl_path(self, filename: str, payload: dict[str, Any]) -> Path:
        target = str(filename or "")
        if target not in self.TIME_BUCKETED_DETAIL_FILES:
            return self.ledger_dir / target
        day, hour = _time_bucket_from_payload(payload)
        return self.hot_time_dir / day / hour / target

    def _jsonl_paths(self, filename: str) -> list[Path]:
        target = str(filename or "")
        paths: list[Path] = []
        legacy_path = self.ledger_dir / target
        if legacy_path.exists():
            paths.append(legacy_path)
        if target in self.TIME_BUCKETED_DETAIL_FILES and self.hot_day_dir.exists():
            paths.extend(
                sorted(
                    path
                    for path in self.hot_day_dir.glob(f"*/{target}")
                    if path.is_file()
                )
            )
        if target in self.TIME_BUCKETED_DETAIL_FILES and self.hot_time_dir.exists():
            paths.extend(
                sorted(
                    path
                    for path in self.hot_time_dir.glob(f"*/*/{target}")
                    if path.is_file()
                )
            )
        return paths

    def _jsonl_signature(self, filename: str) -> tuple[int, int]:
        return self._jsonl_signature_for_paths(self._jsonl_paths(filename))

    def _jsonl_signature_for_paths(self, paths: list[Path]) -> tuple[int, int]:
        mtime_total = 0
        size_total = 0
        for path in paths:
            mtime, size = _file_signature(path)
            mtime_total += int(mtime)
            size_total += int(size)
        return (mtime_total + len(paths), size_total)

    def _jsonl_size_bytes(self, filename: str) -> int:
        return sum(_file_signature(path)[1] for path in self._jsonl_paths(filename))

    def _read_jsonl(self, filename: str, *, run_id: str = "", task_run_id: str = "", session_id: str = "") -> list[dict[str, Any]]:
        normalized_run_id = str(run_id or "")
        normalized_task_run_id = str(task_run_id or "")
        normalized_session_id = str(session_id or "")
        cache_key = (filename, normalized_run_id, normalized_task_run_id, normalized_session_id)
        cacheable = bool(normalized_run_id or normalized_task_run_id or normalized_session_id)
        prefilter = _line_prefilter(
            run_id=normalized_run_id,
            task_run_id=normalized_task_run_id,
            session_id=normalized_session_id,
        )
        with self._lock:
            paths = self._jsonl_paths(filename)
            if not paths:
                return []
            signature = self._jsonl_signature_for_paths(paths)
            if cacheable:
                cached = self._filtered_read_cache.get(cache_key)
                if cached is not None:
                    cached_signature, cached_rows = cached
                    if cached_signature == signature:
                        return [dict(row) for row in cached_rows]

        rows: list[dict[str, Any]] = []
        for path in paths:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    if prefilter and not _line_matches_prefilter(stripped, prefilter):
                        continue
                    try:
                        payload = json.loads(stripped)
                    except JSONDecodeError:
                        continue
                    if isinstance(payload, dict):
                        rows.append(payload)
        if cacheable:
            with self._lock:
                current_paths = self._jsonl_paths(filename)
                current_signature = self._jsonl_signature_for_paths(current_paths)
                if current_paths == paths and current_signature == signature:
                    self._filtered_read_cache[cache_key] = (signature, [dict(row) for row in rows])
                if len(self._filtered_read_cache) > 256:
                    self._filtered_read_cache.pop(next(iter(self._filtered_read_cache)))
        return rows

    def _iter_jsonl_rows(self, filename: str):
        for path in self._jsonl_paths(filename):
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        payload = json.loads(stripped)
                    except JSONDecodeError:
                        continue
                    if isinstance(payload, dict):
                        yield payload

    def _invalidate_filtered_read_cache(self, filename: str | None = None) -> None:
        if filename is None:
            self._filtered_read_cache.clear()
            return
        target = str(filename or "")
        for key in list(self._filtered_read_cache):
            if key[0] == target:
                self._filtered_read_cache.pop(key, None)

    def _rewrite_jsonl_path(self, path: Path, *, should_delete: Any) -> dict[str, Any]:
        if not path.exists():
            return {
                "path": str(path),
                "exists": False,
                "kept_rows": 0,
                "deleted_rows": 0,
                "malformed_rows_kept": 0,
                "rewritten": False,
            }
        tmp_path = path.with_suffix(f"{path.suffix}.{threading.get_ident()}.retention.tmp")
        kept_rows = 0
        deleted_rows = 0
        malformed_rows = 0
        with path.open("r", encoding="utf-8") as source, tmp_path.open("w", encoding="utf-8", newline="\n") as target:
            for line in source:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    row = json.loads(stripped)
                except JSONDecodeError:
                    target.write(line if line.endswith("\n") else line + "\n")
                    malformed_rows += 1
                    kept_rows += 1
                    continue
                if not isinstance(row, dict):
                    target.write(line if line.endswith("\n") else line + "\n")
                    malformed_rows += 1
                    kept_rows += 1
                    continue
                if bool(should_delete(row)):
                    deleted_rows += 1
                    continue
                target.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
                kept_rows += 1
        tmp_path.replace(path)
        return {
            "path": str(path),
            "exists": True,
            "kept_rows": kept_rows,
            "deleted_rows": deleted_rows,
            "malformed_rows_kept": malformed_rows,
            "rewritten": deleted_rows > 0,
        }

    def _rewrite_without_tasks(self, filename: str, task_run_ids: set[str]) -> int:
        deleted = 0
        with self._lock:
            for path in self._jsonl_paths(filename):
                result = self._rewrite_jsonl_path(
                    path,
                    should_delete=lambda row: str(row.get("task_run_id") or "") in task_run_ids
                    or str(row.get("run_id") or "") in task_run_ids,
                )
                deleted += int(result.get("deleted_rows") or 0)
            self._invalidate_filtered_read_cache(filename)
        return deleted

    def _rewrite_without_session_or_tasks(self, filename: str, session_id: str, task_run_ids: set[str]) -> int:
        deleted = 0
        with self._lock:
            for path in self._jsonl_paths(filename):
                result = self._rewrite_jsonl_path(
                    path,
                    should_delete=lambda row: str(row.get("task_run_id") or row.get("run_id") or "") in task_run_ids
                    or (session_id and str(row.get("session_id") or "") == session_id),
                )
                deleted += int(result.get("deleted_rows") or 0)
            self._invalidate_filtered_read_cache(filename)
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
        "cache_miss_tokens": 0,
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
            totals["cache_miss_tokens"] += int(record.cache_miss_tokens or 0)
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


def _empty_usage_summary() -> dict[str, Any]:
    return summarize_usage_records([])


def _new_summary_payload(key: str) -> dict[str, Any]:
    return {
        "authority": "runtime.prompt_accounting.summary_index",
        "version": PromptAccountingLedger.SUMMARY_INDEX_VERSION,
        "key": str(key or ""),
        "summary": _empty_usage_summary(),
        "usage_records": {},
        "cache_records": {},
        "record_count": 0,
        "task_run_id": "",
        "run_id": str(key or ""),
        "session_id": "",
        "provider": "",
        "model": "",
        "created_at": 0.0,
        "updated_at": 0.0,
    }


def _summary_key_for_usage(record: ModelTokenUsageRecord) -> str:
    return str(record.task_run_id or record.run_id or record.request_id or record.usage_id or "").strip()


def _summary_key_for_cache(record: PromptCacheRecord) -> str:
    return str(record.task_run_id or record.run_id or record.request_id or record.cache_record_id or "").strip()


def _compact_usage_record(record: ModelTokenUsageRecord) -> dict[str, Any]:
    return {
        "usage_id": record.usage_id,
        "request_id": record.request_id,
        "run_id": record.run_id,
        "task_run_id": record.task_run_id,
        "session_id": record.session_id,
        "provider": record.provider,
        "model": record.model,
        "source": record.source,
        "prompt_tokens": int(record.prompt_tokens or 0),
        "completion_tokens": int(record.completion_tokens or 0),
        "reasoning_tokens": int(record.reasoning_tokens or 0),
        "cached_tokens": int(record.cached_tokens or 0),
        "cache_creation_tokens": int(record.cache_creation_tokens or 0),
        "cache_read_tokens": int(record.cache_read_tokens or 0),
        "cache_miss_tokens": int(record.cache_miss_tokens or 0),
        "total_tokens": int(record.total_tokens or 0),
        "created_at": float(record.created_at or 0.0),
        "authority": record.authority,
    }


def _compact_cache_record(record: PromptCacheRecord) -> dict[str, Any]:
    return {
        "cache_record_id": record.cache_record_id,
        "request_id": record.request_id,
        "provider": record.provider,
        "model": record.model,
        "run_id": record.run_id,
        "task_run_id": record.task_run_id,
        "session_id": record.session_id,
        "scope": record.scope,
        "status": record.status,
        "cached_tokens": int(record.cached_tokens or 0),
        "cache_savings_tokens": int(record.cache_savings_tokens or 0),
        "cache_creation_tokens": int(record.cache_creation_tokens or 0),
        "cache_read_tokens": int(record.cache_read_tokens or 0),
        "created_at": float(record.created_at or 0.0),
        "authority": record.authority,
    }


def _context_usage_snapshot_from_record(
    record: ModelTokenUsageRecord,
    *,
    request_started_at: float | None,
    observed_at: float | None,
) -> dict[str, Any]:
    current_context_tokens = _context_tokens_from_usage_record(record)
    request_started = _positive_float(request_started_at, float(record.created_at or 0.0))
    observed = _positive_float(observed_at, time.time())
    return {
        "authority": "runtime.prompt_accounting.latest_context_usage_snapshot",
        "version": 1,
        "session_id": str(record.session_id or ""),
        "run_id": str(record.run_id or record.task_run_id or ""),
        "task_run_id": str(record.task_run_id or ""),
        "request_id": str(record.request_id or ""),
        "usage_id": str(record.usage_id or ""),
        "provider": str(record.provider or ""),
        "model": str(record.model or ""),
        "source": str(record.source or ""),
        "current_context_tokens": int(current_context_tokens),
        "prompt_tokens": int(record.prompt_tokens or 0),
        "completion_tokens": int(record.completion_tokens or 0),
        "reasoning_tokens": int(record.reasoning_tokens or 0),
        "cached_tokens": int(record.cached_tokens or 0),
        "cache_creation_tokens": int(record.cache_creation_tokens or 0),
        "cache_read_tokens": int(record.cache_read_tokens or 0),
        "cache_miss_tokens": int(record.cache_miss_tokens or 0),
        "total_tokens": int(record.total_tokens or 0),
        "record_created_at": float(record.created_at or 0.0),
        "request_started_at": request_started,
        "observed_at": observed,
        "diagnostics": {
            "usage_record_authority": str(record.authority or ""),
            "usage_record_source": str(record.source or ""),
        },
    }


def _context_tokens_from_usage_record(record: ModelTokenUsageRecord) -> int:
    prompt_tokens = int(record.prompt_tokens or 0)
    if prompt_tokens > 0:
        return prompt_tokens
    total_tokens = int(record.total_tokens or 0)
    if total_tokens <= 0:
        return 0
    generated_tokens = int(record.completion_tokens or 0) + int(record.reasoning_tokens or 0)
    return max(0, total_tokens - generated_tokens)


def _context_usage_snapshot_should_replace(current: dict[str, Any], candidate: dict[str, Any]) -> bool:
    current_request = str(current.get("request_id") or "")
    candidate_request = str(candidate.get("request_id") or "")
    current_started = _positive_float(current.get("request_started_at"), 0.0)
    candidate_started = _positive_float(candidate.get("request_started_at"), 0.0)
    if current_request and candidate_request and current_request == candidate_request:
        current_priority = _usage_source_priority(current.get("source"))
        candidate_priority = _usage_source_priority(candidate.get("source"))
        if candidate_priority != current_priority:
            return candidate_priority > current_priority
        return _positive_float(candidate.get("observed_at"), 0.0) >= _positive_float(current.get("observed_at"), 0.0)
    if current_started > 0 and candidate_started > 0 and candidate_started != current_started:
        return candidate_started > current_started
    return _positive_float(candidate.get("observed_at"), 0.0) >= _positive_float(current.get("observed_at"), 0.0)


def _usage_source_priority(value: Any) -> int:
    source = str(value or "")
    if source == "provider_usage":
        return 3
    if source == "local_prediction":
        return 2
    if source == "trace_estimate":
        return 1
    return 0


def _positive_float(value: Any, fallback: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = 0.0
    return parsed if parsed > 0 else float(fallback or 0.0)


def _summary_manifest_entry(payload: dict[str, Any]) -> dict[str, Any]:
    summary = dict(payload.get("summary") or {})
    return {
        "authority": str(payload.get("authority") or "runtime.prompt_accounting.summary_index"),
        "key": str(payload.get("key") or ""),
        "task_run_id": str(payload.get("task_run_id") or ""),
        "run_id": str(payload.get("run_id") or ""),
        "session_id": str(payload.get("session_id") or ""),
        "provider": str(payload.get("provider") or ""),
        "model": str(payload.get("model") or ""),
        "created_at": float(payload.get("created_at") or 0.0),
        "updated_at": float(payload.get("updated_at") or 0.0),
        "summary": {
            "total_tokens": int(summary.get("total_tokens") or 0),
            "effective_total_tokens": int(summary.get("effective_total_tokens") or summary.get("total_tokens") or 0),
            "exact_total_tokens": int(summary.get("exact_total_tokens") or 0),
            "predicted_total_tokens": int(summary.get("predicted_total_tokens") or 0),
            "trace_estimate_total_tokens": int(summary.get("trace_estimate_total_tokens") or 0),
            "prompt_tokens": int(summary.get("prompt_tokens") or 0),
            "completion_tokens": int(summary.get("completion_tokens") or 0),
            "reasoning_tokens": int(summary.get("reasoning_tokens") or 0),
            "cached_tokens": int(summary.get("cached_tokens") or 0),
            "cache_creation_tokens": int(summary.get("cache_creation_tokens") or 0),
            "cache_read_tokens": int(summary.get("cache_read_tokens") or 0),
            "cache_miss_tokens": int(summary.get("cache_miss_tokens") or 0),
            "cache_savings_tokens": int(summary.get("cache_savings_tokens") or 0),
            "record_count": int(summary.get("record_count") or 0),
            "cache_record_count": int(summary.get("cache_record_count") or 0),
            "provider_usage_record_count": int(summary.get("provider_usage_record_count") or 0),
            "local_prediction_record_count": int(summary.get("local_prediction_record_count") or 0),
            "trace_estimate_record_count": int(summary.get("trace_estimate_record_count") or 0),
            "billing_truth_available": bool(summary.get("billing_truth_available") is True),
        },
    }


def _summary_entry_from_compact_records(
    key: str,
    *,
    usage_records: list[dict[str, Any]],
    cache_records: list[dict[str, Any]],
    authority: str,
) -> dict[str, Any]:
    usage = [
        ModelTokenUsageRecord.from_dict(dict(item))
        for item in list(usage_records or [])
        if isinstance(item, dict)
    ]
    cache = [
        PromptCacheRecord.from_dict(dict(item))
        for item in list(cache_records or [])
        if isinstance(item, dict)
    ]
    sorted_usage = sorted(usage, key=lambda item: float(item.created_at or 0.0))
    sorted_cache = sorted(cache, key=lambda item: float(item.created_at or 0.0))
    timeline = [*sorted_usage, *sorted_cache]
    first = min(timeline, key=lambda item: float(getattr(item, "created_at", 0.0) or 0.0), default=None)
    last = max(timeline, key=lambda item: float(getattr(item, "created_at", 0.0) or 0.0), default=None)
    summary = summarize_usage_records(sorted_usage, cache_records=sorted_cache)
    summary["cache_record_count"] = len(sorted_cache)
    payload = {
        "authority": authority,
        "version": PromptAccountingLedger.SUMMARY_INDEX_VERSION,
        "key": str(key or ""),
        "summary": summary,
        "task_run_id": str(getattr(last, "task_run_id", "") or getattr(first, "task_run_id", "") or ""),
        "run_id": str(getattr(last, "run_id", "") or getattr(first, "run_id", "") or str(key or "")),
        "session_id": str(getattr(last, "session_id", "") or getattr(first, "session_id", "") or ""),
        "provider": str(getattr(last, "provider", "") or getattr(first, "provider", "") or ""),
        "model": str(getattr(last, "model", "") or getattr(first, "model", "") or ""),
        "created_at": float(getattr(first, "created_at", 0.0) or 0.0),
        "updated_at": float(getattr(last, "created_at", 0.0) or 0.0),
    }
    return _summary_manifest_entry(payload)


def _merge_summary_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for row in list(rows or []):
        if not isinstance(row, dict):
            continue
        key = str(row.get("key") or row.get("task_run_id") or row.get("run_id") or "").strip()
        if not key:
            continue
        entry = _summary_manifest_entry({**dict(row), "key": key})
        existing = by_key.get(key)
        by_key[key] = entry if existing is None else _merge_summary_entry(existing, entry)
    return list(by_key.values())


def _merge_summary_entry(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    left_entry = _summary_manifest_entry(left)
    right_entry = _summary_manifest_entry(right)
    left_summary = dict(left_entry.get("summary") or {})
    right_summary = dict(right_entry.get("summary") or {})
    numeric_keys = {
        "total_tokens",
        "effective_total_tokens",
        "exact_total_tokens",
        "predicted_total_tokens",
        "trace_estimate_total_tokens",
        "prompt_tokens",
        "completion_tokens",
        "reasoning_tokens",
        "cached_tokens",
        "cache_creation_tokens",
        "cache_read_tokens",
        "cache_miss_tokens",
        "cache_savings_tokens",
        "record_count",
        "cache_record_count",
        "provider_usage_record_count",
        "local_prediction_record_count",
        "trace_estimate_record_count",
    }
    summary = {
        key: int(left_summary.get(key) or 0) + int(right_summary.get(key) or 0)
        for key in numeric_keys
    }
    summary["billing_truth_available"] = bool(summary["provider_usage_record_count"] > 0)
    created_candidates = [
        float(item.get("created_at") or 0.0)
        for item in (left_entry, right_entry)
        if float(item.get("created_at") or 0.0) > 0
    ]
    updated_at = max(float(left_entry.get("updated_at") or 0.0), float(right_entry.get("updated_at") or 0.0))
    latest = right_entry if float(right_entry.get("updated_at") or 0.0) >= float(left_entry.get("updated_at") or 0.0) else left_entry
    earliest = min(created_candidates) if created_candidates else 0.0
    return {
        "authority": "runtime.prompt_accounting.merged_token_summary",
        "key": str(latest.get("key") or left_entry.get("key") or right_entry.get("key") or ""),
        "task_run_id": str(latest.get("task_run_id") or left_entry.get("task_run_id") or right_entry.get("task_run_id") or ""),
        "run_id": str(latest.get("run_id") or left_entry.get("run_id") or right_entry.get("run_id") or ""),
        "session_id": str(latest.get("session_id") or left_entry.get("session_id") or right_entry.get("session_id") or ""),
        "provider": str(latest.get("provider") or left_entry.get("provider") or right_entry.get("provider") or ""),
        "model": str(latest.get("model") or left_entry.get("model") or right_entry.get("model") or ""),
        "created_at": earliest,
        "updated_at": updated_at,
        "summary": summary,
    }


def _aggregate_summary_entries(entries: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "total_tokens": 0,
        "overall_total_tokens": 0,
        "effective_total_tokens": 0,
        "exact_total_tokens": 0,
        "predicted_total_tokens": 0,
        "trace_estimate_total_tokens": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "reasoning_tokens": 0,
        "cached_tokens": 0,
        "cache_creation_tokens": 0,
        "cache_read_tokens": 0,
        "cache_miss_tokens": 0,
        "cache_savings_tokens": 0,
        "record_count": 0,
        "cache_record_count": 0,
        "provider_usage_record_count": 0,
        "local_prediction_record_count": 0,
        "trace_estimate_record_count": 0,
        "run_summary_count": len(entries),
        "session_count": len({str(item.get("session_id") or "") for item in entries if str(item.get("session_id") or "")}),
    }
    for entry in list(entries or []):
        item_summary = dict(entry.get("summary") or {})
        for key in (
            "total_tokens",
            "effective_total_tokens",
            "exact_total_tokens",
            "predicted_total_tokens",
            "trace_estimate_total_tokens",
            "prompt_tokens",
            "completion_tokens",
            "reasoning_tokens",
            "cached_tokens",
            "cache_creation_tokens",
            "cache_read_tokens",
            "cache_miss_tokens",
            "cache_savings_tokens",
            "record_count",
            "cache_record_count",
            "provider_usage_record_count",
            "local_prediction_record_count",
            "trace_estimate_record_count",
        ):
            summary[key] = int(summary.get(key) or 0) + int(item_summary.get(key) or 0)
    summary["overall_total_tokens"] = int(summary.get("total_tokens") or 0)
    summary["billing_truth_available"] = bool(int(summary.get("provider_usage_record_count") or 0) > 0)
    return summary


def _daily_token_stats(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_day: dict[int, dict[str, Any]] = {}
    for entry in list(entries or []):
        updated_at = float(entry.get("updated_at") or entry.get("created_at") or 0.0)
        if updated_at <= 0:
            continue
        day_start = int(updated_at // 86400) * 86400
        summary = dict(entry.get("summary") or {})
        bucket = by_day.setdefault(
            day_start,
            {
                "bucket_start": day_start,
                "bucket_end": day_start + 86400,
                "bucket": time.strftime("%Y-%m-%d", time.localtime(day_start)),
                "tokens": 0,
                "exact_tokens": 0,
                "predicted_tokens": 0,
                "trace_estimate_tokens": 0,
                "cache_savings_tokens": 0,
                "records": 0,
                "sessions": set(),
            },
        )
        bucket["tokens"] = int(bucket["tokens"]) + int(summary.get("total_tokens") or 0)
        bucket["exact_tokens"] = int(bucket["exact_tokens"]) + int(summary.get("exact_total_tokens") or 0)
        bucket["predicted_tokens"] = int(bucket["predicted_tokens"]) + int(summary.get("predicted_total_tokens") or 0)
        bucket["trace_estimate_tokens"] = int(bucket["trace_estimate_tokens"]) + int(summary.get("trace_estimate_total_tokens") or 0)
        bucket["cache_savings_tokens"] = int(bucket["cache_savings_tokens"]) + int(summary.get("cache_savings_tokens") or 0)
        bucket["records"] = int(bucket["records"]) + int(summary.get("record_count") or 0)
        session_id = str(entry.get("session_id") or "")
        if session_id:
            bucket["sessions"].add(session_id)
    rows: list[dict[str, Any]] = []
    for bucket in sorted(by_day.values(), key=lambda item: int(item.get("bucket_start") or 0)):
        payload = dict(bucket)
        payload["sessions"] = len(set(payload.get("sessions") or set()))
        rows.append(payload)
    return rows


def _empty_retained_token_stats(*, version: int) -> dict[str, Any]:
    return {
        "authority": "runtime.prompt_accounting.retained_token_stats",
        "version": version,
        "retention_policy": {},
        "updated_at": 0.0,
        "run_summary_count": 0,
        "summary": _aggregate_summary_entries([]),
        "daily": [],
        "run_summaries": [],
        "checksum": _json_checksum([]),
    }


def _json_checksum(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _time_bucket_from_payload(payload: dict[str, Any]) -> tuple[str, str]:
    created_at = _created_at_from_payload(payload)
    return time.strftime("%Y%m%d", time.localtime(created_at)), time.strftime("%H", time.localtime(created_at))


def _created_at_from_payload(payload: dict[str, Any]) -> float:
    try:
        created_at = float(dict(payload or {}).get("created_at") or 0.0)
    except (TypeError, ValueError):
        created_at = 0.0
    return created_at if created_at > 0 else time.time()


def _bucket_from_hot_path(hot_day_dir: Path, path: Path) -> str:
    try:
        relative = path.resolve().relative_to(hot_day_dir.resolve())
    except ValueError:
        return ""
    parts = relative.parts
    if len(parts) >= 2 and str(parts[0]).isdigit() and str(parts[1]).isdigit():
        return f"{parts[0]}/{parts[1]}"
    return str(parts[0]) if parts else ""


def _jsonl_line_count(path: Path) -> int:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return sum(1 for line in handle if line.strip())
    except OSError:
        return 0


def _recent_records(
    records: list[Any],
    *,
    run_id: str = "",
    task_run_id: str = "",
    session_id: str = "",
    limit: int = 128,
    key_fn: Any,
) -> list[Any]:
    normalized_run_id = str(run_id or "")
    normalized_task_run_id = str(task_run_id or "")
    normalized_session_id = str(session_id or "")
    target = max(1, int(limit or 128))
    deduped: dict[str, Any] = {}
    for record in reversed(list(records or [])):
        if normalized_run_id and str(getattr(record, "run_id", "") or getattr(record, "task_run_id", "") or "") != normalized_run_id:
            continue
        if normalized_task_run_id and str(getattr(record, "task_run_id", "") or "") != normalized_task_run_id:
            continue
        if normalized_session_id and str(getattr(record, "session_id", "") or "") != normalized_session_id:
            continue
        key = str(key_fn(record) or f"{getattr(record, 'request_id', '')}:{getattr(record, 'created_at', '')}")
        if key in deduped:
            continue
        deduped[key] = record
        if len(deduped) >= target:
            break
    return sorted(deduped.values(), key=lambda item: float(getattr(item, "created_at", 0.0) or 0.0))


def _line_prefilter(*, run_id: str, task_run_id: str, session_id: str) -> tuple[tuple[str, ...], ...]:
    groups: list[tuple[str, ...]] = []
    if session_id:
        groups.append(_json_field_markers("session_id", session_id))
    if task_run_id:
        groups.append(_json_field_markers("task_run_id", task_run_id) + _json_field_markers("run_id", task_run_id))
    elif run_id:
        groups.append(_json_field_markers("run_id", run_id) + _json_field_markers("task_run_id", run_id))
    return tuple(groups)


def _json_field_markers(field: str, value: str) -> tuple[str, str]:
    encoded = json.dumps(str(value), ensure_ascii=False)
    return (f'"{field}": {encoded}', f'"{field}":{encoded}')


def _line_matches_prefilter(line: str, groups: tuple[tuple[str, ...], ...]) -> bool:
    return all(any(marker in line for marker in group) for group in groups)


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


def _retention_group_id(row: dict[str, Any], *, primary_fields: tuple[str, ...]) -> str:
    for field in primary_fields:
        value = str(row.get(field) or "").strip()
        if value:
            return f"{field}:{value}"
    for field in ("request_id", "task_run_id", "run_id", "cache_record_id", "usage_id", "report_id", "segment_id"):
        value = str(row.get(field) or "").strip()
        if value:
            return f"{field}:{value}"
    return "row:" + hashlib.sha256(json.dumps(row, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _row_is_retention_protected(row: dict[str, Any], *, protection: dict[str, set[str]]) -> bool:
    protected_keys = set(protection.get("keys") or set())
    protected_sessions = set(protection.get("sessions") or set())
    row_keys = {
        str(row.get("task_run_id") or "").strip(),
        str(row.get("run_id") or "").strip(),
        str(row.get("request_id") or "").strip(),
    }
    row_session = str(row.get("session_id") or "").strip()
    return bool((protected_keys & row_keys) or (row_session and row_session in protected_sessions))


def _row_retention_decision(
    row: dict[str, Any],
    *,
    cutoff_timestamp: float,
    protection: dict[str, set[str]],
    retained_request_ids: set[str],
) -> str:
    if _row_is_retention_protected(row, protection=protection):
        return "protected"
    request_id = str(row.get("request_id") or "").strip()
    if request_id and request_id in retained_request_ids:
        return "protected"
    created_at = _row_created_at(row)
    if created_at <= 0:
        return "undated"
    if created_at < cutoff_timestamp:
        return "compact"
    return "hot"


def _row_created_at(row: dict[str, Any]) -> float:
    for field in ("created_at", "updated_at", "recorded_at"):
        try:
            value = float(row.get(field) or 0.0)
        except (TypeError, ValueError):
            value = 0.0
        if value > 0:
            return value
    return 0.0


def _file_signature(path: Path) -> tuple[int, int]:
    try:
        stat = path.stat()
    except OSError:
        return (0, 0)
    return int(stat.st_mtime_ns), int(stat.st_size)
