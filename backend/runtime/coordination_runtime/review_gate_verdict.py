from __future__ import annotations

import re
from typing import Iterable


ACCEPTED_REVIEW_VERDICTS = {"pass", "pass_with_notes"}
REJECTED_REVIEW_VERDICTS = {
    "revise",
    "revise_volume",
    "revise_extension",
    "repair_canon",
    "repair_world",
    "repair_outline",
    "repair_character",
    "fail_closed",
    "human_review_required",
    "reject",
    "blocker_found",
}

_REVIEW_LABELS = {
    "审核结论",
    "审核结果",
    "审核状态",
    "审核裁决",
    "评审结论",
    "评审结果",
    "评审状态",
    "评审裁决",
    "复核结论",
    "复核结果",
    "裁决",
    "结论",
    "verdict",
    "reviewverdict",
    "decision",
}
_NEXT_STAGE_LABELS = {
    "可进入下一节点",
    "是否进入下一节点",
    "是否允许进入下一节点",
    "允许进入下一节点",
    "进入下一节点",
    "可进入下一阶段",
    "是否进入下一阶段",
    "是否允许进入下一阶段",
    "允许进入下一阶段",
    "进入下一阶段",
    "canproceed",
    "proceed",
}
_BLOCKER_LABELS = {"阻塞项", "阻塞问题", "blockers", "blockingissues"}

_EXPLICIT_LABEL_PATTERN = re.compile(
    r"^\s*(?:[-*+]\s*)?(?:#{1,6}\s*)?[【\[]?\s*(?P<label>[^:：\-\n\r|]{1,60})\s*[】\]]?\s*[:：-]\s*(?P<value>[^\n\r]+)",
    re.IGNORECASE | re.MULTILINE,
)
_TABLE_ROW_PATTERN = re.compile(
    r"^\s*\|\s*(?P<label>[^|\n\r]{1,60})\s*\|\s*(?P<value>[^|\n\r]+)\s*\|",
    re.IGNORECASE | re.MULTILINE,
)


def extract_review_verdict(content: str) -> str:
    text = str(content or "").strip()
    if not text:
        return ""
    explicit_verdict = extract_explicit_review_verdict(text)
    if explicit_verdict:
        return explicit_verdict

    lowered = text.lower()
    if _has_blocking_revision_signal(text):
        return "revise"
    if "不允许写入" in text or "不允许批次写入" in text or "必须等正文" in text:
        return "revise"
    if "允许批次写入记忆：否" in text or "是否允许批次写入记忆：否" in text:
        return "revise"
    if re.search(r"\bfail[_ -]?closed\b", lowered):
        return "fail_closed"
    for verdict in (
        "repair_canon",
        "repair_world",
        "repair_outline",
        "repair_character",
        "revise_volume",
        "revise_extension",
        "blocker_found",
        "reject",
        "human_review_required",
        "pass_with_notes",
    ):
        if verdict in lowered:
            return verdict
    if re.search(r"\b(revise|revision required|rejected|reject)\b", lowered):
        return "revise"
    if re.search(r"\b(pass|approved|approve)\b", lowered):
        return "pass"
    return ""


def extract_explicit_review_verdict(text: str) -> str:
    signals: list[str] = []
    for label, value in _iter_explicit_label_values(text):
        label_kind = _review_label_kind(label)
        if label_kind == "review":
            verdict = _classify_review_value(value)
        elif label_kind == "next_stage":
            verdict = _classify_next_stage_value(value)
        elif label_kind == "blocker":
            verdict = _classify_blocker_value(value)
        else:
            verdict = ""
        if verdict:
            signals.append(verdict)

    if _has_blocking_revision_signal(text):
        accepted_signals = {"pass", "pass_with_notes"}
        if any(verdict in accepted_signals for verdict in signals) and not any(
            review_verdict_is_rejected(verdict) for verdict in signals
        ):
            return "revise"

    for verdict in signals:
        if review_verdict_is_rejected(verdict):
            return verdict
    for verdict in signals:
        if verdict == "pass_with_notes":
            return verdict
    for verdict in signals:
        if verdict == "pass":
            return verdict
    return ""


def review_verdict_is_accepted(verdict: str) -> bool:
    return str(verdict or "").strip() in ACCEPTED_REVIEW_VERDICTS


def review_verdict_is_rejected(verdict: str) -> bool:
    return str(verdict or "").strip() in REJECTED_REVIEW_VERDICTS


def _iter_explicit_label_values(text: str) -> Iterable[tuple[str, str]]:
    seen: set[tuple[str, str]] = set()
    for pattern in (_EXPLICIT_LABEL_PATTERN, _TABLE_ROW_PATTERN):
        for match in pattern.finditer(str(text or "")):
            label = str(match.group("label") or "").strip()
            value = str(match.group("value") or "").strip().strip("|").strip()
            if _is_table_header_or_separator(label, value):
                continue
            key = (label, value)
            if not label or not value or key in seen:
                continue
            seen.add(key)
            yield label, value


def _review_label_kind(label: str) -> str:
    normalized = _normalize_label(label)
    if normalized in _REVIEW_LABELS:
        return "review"
    if normalized in _NEXT_STAGE_LABELS:
        return "next_stage"
    if normalized in _BLOCKER_LABELS:
        return "blocker"
    return ""


def _normalize_label(label: str) -> str:
    return re.sub(r"[\s_./\\【】\[\]（）()]+", "", str(label or "").strip()).lower()


def _is_table_header_or_separator(label: str, value: str) -> bool:
    normalized_label = _normalize_label(label)
    normalized_value = _normalize_label(value)
    if not normalized_label or not normalized_value:
        return False
    if normalized_label in _BLOCKER_LABELS and normalized_value in {"状态", "status"}:
        return True
    if normalized_label in {"硬设定要求", "要求", "检查项", "项目", "类型", "序号"} and normalized_value in {
        "合规状态",
        "状态",
        "内容",
        "优先级",
        "status",
    }:
        return True
    if re.fullmatch(r"[-:：| ]+", str(label or "")) or re.fullmatch(r"[-:：| ]+", str(value or "")):
        return True
    return False


def _classify_review_value(value: str) -> str:
    raw = str(value or "").strip()
    lowered = raw.lower()
    compact = re.sub(r"\s+", "", raw)
    compact_lower = compact.lower()

    if re.search(r"\bfail[_ -]?closed\b", lowered):
        return "fail_closed"
    if "human_review_required" in lowered or "人工复核" in compact or "人工审核" in compact:
        return "human_review_required"
    for token in ("repair_canon", "repair_world", "repair_outline", "repair_character"):
        if token in lowered:
            return token
    if any(token in lowered for token in ("revise_volume", "revise_extension", "blocker_found")):
        return "revise"
    if _contains_hard_rejection(raw):
        return "revise"

    has_pass = _contains_positive_pass(raw)
    if has_pass:
        if "pass_with_notes" in lowered or any(
            token in compact for token in ("附条件", "有条件", "带备注", "附建议", "建议优化")
        ):
            return "pass_with_notes"
        return "pass"

    if re.search(r"\b(revise|revision required|rejected|reject)\b", lowered):
        return "revise"
    if any(token in compact for token in ("修订", "修改", "调整", "补充", "重写")):
        return "revise"
    if any(token in compact_lower for token in ("pass_with_notes", "approved", "approve", "pass")):
        return "pass_with_notes" if "pass_with_notes" in compact_lower else "pass"
    return ""


def _classify_next_stage_value(value: str) -> str:
    raw = str(value or "").strip()
    lowered = raw.lower()
    compact = re.sub(r"\s+", "", raw)
    if re.search(r"\b(no|false|blocked|reject|rejected)\b", lowered):
        return "revise"
    if any(token in compact for token in ("否", "不可", "不能", "不允许", "暂不", "停止")):
        return "revise"
    if re.search(r"\b(yes|true|pass|approved|approve)\b", lowered):
        return "pass"
    if any(token in compact for token in ("是", "可", "允许", "进入", "同意")):
        return "pass"
    return ""


def _classify_blocker_value(value: str) -> str:
    compact = re.sub(r"\s+", "", str(value or "").strip())
    compact = compact.strip("。；;，,：:")
    lowered = compact.lower()
    if not compact:
        return ""
    if compact in {"无", "没有", "暂无", "无明显", "无阻塞", "无阻塞项", "零", "0", "零项", "0项"}:
        return ""
    if lowered in {"none", "no", "n/a", "na", "zero"}:
        return ""
    if compact.startswith(("无，", "无。", "无；", "无;", "没有，", "暂无，")):
        return ""
    return "blocker_found"


def _contains_hard_rejection(value: str) -> bool:
    compact = re.sub(r"\s+", "", str(value or "").strip())
    lowered = compact.lower()
    if re.search(r"\b(no|false|blocked|reject|rejected)\b", str(value or "").lower()):
        return True
    if any(
        token in compact
        for token in (
            "不通过",
            "未通过",
            "不能通过",
            "不可通过",
            "拒绝",
            "驳回",
            "退回",
            "返修",
            "返工",
            "阻塞",
            "不可进入",
            "不能进入",
            "不允许进入",
        )
    ):
        return True
    return any(token in lowered for token in ("repair_", "blocker_found"))


def _has_blocking_revision_signal(text: str) -> bool:
    compact = re.sub(r"\s+", "", str(text or ""))
    if not compact:
        return False
    hard_signals = (
        "必须修订项",
        "必须修订",
        "阻塞后续写作",
        "阻塞后续",
        "阻塞项",
        "阻塞问题",
        "返修",
        "退回修改",
        "退回修订",
        "第二轮审核",
        "修订后进入",
        "修订完成后进入",
        "不允许进入",
        "不能进入",
        "暂不进入",
    )
    if any(signal in compact for signal in hard_signals):
        no_blocker_patterns = (
            "阻塞项：无",
            "阻塞项:无",
            "阻塞问题：无",
            "阻塞问题:无",
            "无阻塞项",
            "无阻塞问题",
            "阻塞问题：零",
            "阻塞问题:零",
        )
        if any(pattern in compact for pattern in no_blocker_patterns) and not any(
            signal in compact
            for signal in (
                "必须修订项",
                "阻塞后续写作",
                "返修",
                "第二轮审核",
                "不允许进入",
                "不能进入",
            )
        ):
            return False
        return True
    return False


def _contains_positive_pass(value: str) -> bool:
    compact = re.sub(r"\s+", "", str(value or "").strip())
    lowered = str(value or "").lower()
    if re.search(r"\b(pass|approved|approve|yes|true)\b", lowered):
        return True
    if any(token in compact for token in ("通过", "同意", "准入", "允许")):
        return True
    return False
