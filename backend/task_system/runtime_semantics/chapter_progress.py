from __future__ import annotations

from typing import Any


AUTHORITY = "harness.writing.chapter_progress_receipt"


class ChapterProgressReceiptError(ValueError):
    """Raised when a chapter progress receipt is missing or invalid."""


def normalize_chapter_progress_receipt(
    value: Any,
    *,
    initial_inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ChapterProgressReceiptError("chapter_progress_receipt_not_object")
    receipt = dict(value)
    if str(receipt.get("authority") or "").strip() != AUTHORITY:
        raise ChapterProgressReceiptError("chapter_progress_receipt_authority_invalid")

    inputs = dict(initial_inputs or {})
    batch_start = _int_value(receipt.get("batch_start_index"), _int_value(inputs.get("batch_start_index"), 1))
    batch_end = _int_value(receipt.get("batch_end_index"), _int_value(inputs.get("batch_end_index"), batch_start))
    if batch_end < batch_start:
        raise ChapterProgressReceiptError("chapter_progress_receipt_batch_range_invalid")

    expected = _int_list(receipt.get("expected_chapter_indexes"))
    if not expected:
        expected = list(range(batch_start, batch_end + 1))
    if expected != list(range(min(expected), max(expected) + 1)):
        raise ChapterProgressReceiptError("chapter_progress_receipt_expected_indexes_not_contiguous")
    expected_set = set(expected)

    committed = _int_list(receipt.get("committed_chapter_indexes"))
    if not committed:
        raise ChapterProgressReceiptError("chapter_progress_receipt_committed_indexes_missing")
    if committed != list(range(min(committed), max(committed) + 1)):
        raise ChapterProgressReceiptError("chapter_progress_receipt_committed_indexes_not_contiguous")
    if max(committed) > expected[-1]:
        raise ChapterProgressReceiptError("chapter_progress_receipt_committed_indexes_outside_expected")
    committed = [index for index in committed if index in expected_set]
    if not committed:
        raise ChapterProgressReceiptError("chapter_progress_receipt_committed_indexes_outside_expected")
    if committed[0] != expected[0]:
        raise ChapterProgressReceiptError("chapter_progress_receipt_committed_prefix_required")

    missing = _int_list(receipt.get("missing_chapter_indexes"))
    if not missing:
        missing = [index for index in expected if index not in set(committed)]
    expected_missing = [index for index in expected if index not in set(committed)]
    if missing != expected_missing:
        raise ChapterProgressReceiptError("chapter_progress_receipt_missing_indexes_inconsistent")

    unexpected = _int_list(receipt.get("unexpected_chapter_indexes"))
    if unexpected:
        raise ChapterProgressReceiptError("chapter_progress_receipt_unexpected_indexes_present")

    next_chapter = _int_value(receipt.get("next_chapter_index"), (committed[-1] + 1 if missing else batch_end + 1))
    expected_next = committed[-1] + 1 if missing else batch_end + 1
    if next_chapter != expected_next:
        raise ChapterProgressReceiptError("chapter_progress_receipt_next_chapter_inconsistent")

    batch_complete = bool(receipt.get("batch_complete"))
    if batch_complete != (not missing):
        raise ChapterProgressReceiptError("chapter_progress_receipt_batch_complete_inconsistent")

    committed_words = max(0, _int_value(receipt.get("committed_words"), 0))

    authoritative_volume_index = _authoritative_volume_index(receipt=receipt, inputs=inputs)

    normalized = {
        **receipt,
        "authority": AUTHORITY,
        "volume_index": authoritative_volume_index,
        "batch_start_index": batch_start,
        "batch_end_index": batch_end,
        "expected_chapter_indexes": expected,
        "committed_chapter_indexes": committed,
        "missing_chapter_indexes": missing,
        "unexpected_chapter_indexes": unexpected,
        "committed_chapter_count": len(committed),
        "committed_words": committed_words,
        "next_chapter_index": next_chapter,
        "batch_complete": batch_complete,
        "volume_complete": bool(receipt.get("volume_complete")),
        "commit_allowed": bool(receipt.get("commit_allowed", True)),
    }
    if not normalized["commit_allowed"]:
        raise ChapterProgressReceiptError("chapter_progress_receipt_commit_not_allowed")
    return normalized


def _authoritative_volume_index(*, receipt: dict[str, Any], inputs: dict[str, Any]) -> int:
    if "volume_index" in inputs and inputs.get("volume_index") not in (None, ""):
        return _int_value(inputs.get("volume_index"), 1)
    return _int_value(receipt.get("volume_index"), 1)


def first_chapter_progress_receipt(
    sources: list[dict[str, Any]],
    *,
    key: str = "chapter_progress_receipt",
    initial_inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        candidates = []
        if key and isinstance(source.get(key), dict):
            candidates.append(source.get(key))
        if isinstance(source.get("progress_receipt"), dict):
            candidates.append(source.get("progress_receipt"))
        if isinstance(source.get("receipt"), dict):
            candidates.append(source.get("receipt"))
        if source.get("authority") == AUTHORITY:
            candidates.append(source)
        for candidate in candidates:
            try:
                return normalize_chapter_progress_receipt(candidate, initial_inputs=initial_inputs)
            except ChapterProgressReceiptError as exc:
                errors.append(str(exc))
    detail = ",".join(dict.fromkeys(errors)) if errors else "chapter_progress_receipt_missing"
    raise ChapterProgressReceiptError(detail)


def _int_value(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _int_list(value: Any) -> list[int]:
    result: list[int] = []
    for item in list(value or []):
        try:
            result.append(int(item))
        except (TypeError, ValueError):
            continue
    return result
