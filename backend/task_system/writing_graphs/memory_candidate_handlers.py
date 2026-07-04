from __future__ import annotations

from typing import Any

from graph_system.memory_candidate_registry import MemoryCandidatePayloadHandler
from graph_system.models import safe_id


AUTHORITY = "task_system.writing_graphs.memory_candidate_handler"


def register_memory_candidate_payload_handlers(register) -> None:
    register(
        MemoryCandidatePayloadHandler(
            handler_id="writing_review_memory_candidates",
            augment_candidate_source_payload=augment_writing_review_candidate_payload,
            priority=200,
        )
    )


def augment_writing_review_candidate_payload(*, task_run_payload: dict[str, Any], base_payload: dict[str, Any]) -> dict[str, Any] | None:
    del task_run_payload
    final_answer = str(dict(base_payload or {}).get("final_answer") or "")
    if not final_answer.strip():
        return None
    return {
        "review_advisories": _review_advisory_candidates(final_answer),
        "review_blocking_issues": _review_blocking_issue_candidates(final_answer),
    }


def _review_advisory_candidates(final_answer: str) -> list[dict[str, Any]]:
    text = str(final_answer or "").strip()
    if not text:
        return []
    if _review_verdict(text) not in {"通过", "带备注通过"}:
        return []
    section = _review_advisory_section(text)
    if not section:
        return []
    items = _numbered_review_items(section)
    if not items:
        items = [section] if _looks_like_non_blocking_advisory(section) else []
    candidates: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        canonical = item.strip()
        if not canonical or not _looks_like_non_blocking_advisory(canonical):
            continue
        key = f"planning_advisory_{index:03d}_{safe_id(canonical[:48])}"
        candidates.append(
            {
                "record_key": key,
                "record_kind": "planning_advisory",
                "canonical_text": canonical,
                "summary": canonical[:240],
                "payload": {
                    "advisory_index": index,
                    "severity": "non_blocking",
                    "source": "review_report",
                    "content": canonical,
                    "authority": AUTHORITY,
                },
                "metadata": {
                    "advisory_kind": "planning_advisory",
                    "blocking": False,
                    "authority": AUTHORITY,
                },
            }
        )
    return candidates


def _review_blocking_issue_candidates(final_answer: str) -> list[dict[str, Any]]:
    text = str(final_answer or "").strip()
    if not text:
        return []
    verdict = _review_verdict(text)
    if verdict not in {"返修", "拒绝"} and not _contains_blocking_review_marker(text):
        return []
    return [
        {
            "record_key": "blocking_review_issue",
            "record_kind": "review_issue",
            "canonical_text": text,
            "summary": text[:240],
            "payload": {
                "severity": "blocking",
                "source": "review_report",
                "content": text,
                "authority": AUTHORITY,
            },
            "metadata": {
                "issue_kind": "review_issue",
                "blocking": True,
                "authority": AUTHORITY,
            },
        }
    ]


def _review_verdict(text: str) -> str:
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("审核裁决："):
            return line.split("：", 1)[1].strip()
        break
    return ""


def _review_advisory_section(text: str) -> str:
    lines = str(text or "").splitlines()
    start = -1
    for index, raw_line in enumerate(lines):
        line = raw_line.strip().lstrip("#").strip()
        if any(marker in line for marker in ("潜在风险与建议", "非阻塞性", "审核备注", "可选轻微建议")):
            start = index + 1
            break
    if start < 0:
        return ""
    collected: list[str] = []
    for raw_line in lines[start:]:
        line = raw_line.strip()
        heading = line.lstrip("#").strip()
        if heading.startswith("是否允许进入下一阶段"):
            break
        if line.startswith("##") and collected:
            break
        collected.append(raw_line)
    return "\n".join(collected).strip()


def _numbered_review_items(section: str) -> list[str]:
    items: list[str] = []
    current: list[str] = []
    for raw_line in str(section or "").splitlines():
        line = raw_line.strip()
        if _starts_numbered_item(line) or line.startswith("- "):
            if current:
                items.append("\n".join(current).strip())
            current = [line]
            continue
        if current and line:
            current.append(line)
    if current:
        items.append("\n".join(current).strip())
    return items


def _starts_numbered_item(line: str) -> bool:
    head = line.split(" ", 1)[0].strip()
    if not head.endswith((".", "、")):
        return False
    return head[:-1].isdigit()


def _looks_like_non_blocking_advisory(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    blocking_markers = ("阻塞", "必须修改", "返修", "拒绝", "不允许进入下一阶段", "冻结前必须处理")
    if any(marker in value for marker in blocking_markers):
        return False
    advisory_markers = ("建议", "可在", "可进一步", "增加", "明确", "细化", "铺垫", "避免")
    return any(marker in value for marker in advisory_markers)


def _contains_blocking_review_marker(text: str) -> bool:
    markers = ("必须修改", "不允许进入下一阶段", "冻结前必须处理", "阻塞问题", "硬设定冲突")
    return any(marker in str(text or "") for marker in markers)
