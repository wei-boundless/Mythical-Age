from __future__ import annotations

import hashlib
import json
from typing import Any


def stable_hash(payload: Any) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def safe_id(value: str, *, limit: int = 120) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_", ":", "."} else "_" for ch in str(value or ""))[:limit]


def build_work_order_id(kind: str, payload: Any) -> str:
    return f"work:{safe_id(kind or 'generic')}:{stable_hash(payload)[:16]}"


def build_assembly_contract_id(work_order_id: str, payload: Any) -> str:
    return f"assembly:{safe_id(work_order_id or 'work')}:{stable_hash(payload)[:16]}"


def build_execution_permit_id(assembly_contract_id: str, payload: Any) -> str:
    return f"permit:{safe_id(assembly_contract_id or 'assembly')}:{stable_hash(payload)[:16]}"


def build_execution_result_id(assembly_contract_id: str, payload: Any) -> str:
    return f"execresult:{safe_id(assembly_contract_id or 'assembly')}:{stable_hash(payload)[:16]}"

