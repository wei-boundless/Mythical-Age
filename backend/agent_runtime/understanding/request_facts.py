from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any


PATH_RE = re.compile(
    r"(?P<path>(?:[A-Za-z]:)?(?:[./\\]?[\w\u4e00-\u9fff @()：:（），,\-]+[\\/])+[\w\u4e00-\u9fff @()：:（），,.\-]+"
    r"|[\w\u4e00-\u9fff @()\-./\\]+?\.(?:json|py|md|txt|log|csv|tsv|xlsx|xls|pdf|yaml|yml|toml|ts|tsx|js|jsx|css|html|parquet))",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class RequestFacts:
    facts_id: str
    user_message: str
    session_id: str = ""
    task_id: str = ""
    turn_id: str = ""
    source: str = ""
    explicit_paths: tuple[str, ...] = ()
    material_suffixes: tuple[str, ...] = ()
    raw_action_markers: tuple[str, ...] = ()
    raw_constraint_markers: tuple[str, ...] = ()
    explicit_selection: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "agent_runtime.request_facts"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["explicit_paths"] = list(self.explicit_paths)
        payload["material_suffixes"] = list(self.material_suffixes)
        payload["raw_action_markers"] = list(self.raw_action_markers)
        payload["raw_constraint_markers"] = list(self.raw_constraint_markers)
        payload["explicit_selection"] = dict(self.explicit_selection or {})
        payload["diagnostics"] = dict(self.diagnostics or {})
        return payload


def build_request_facts(
    *,
    user_message: str,
    session_id: str = "",
    task_id: str = "",
    turn_id: str = "",
    source: str = "",
    explicit_selection: dict[str, Any] | None = None,
) -> RequestFacts:
    text = str(user_message or "").strip()
    paths = tuple(_dedupe(_extract_paths(text)))
    return RequestFacts(
        facts_id=f"request-facts:{_slug(text)[:48] or 'runtime'}",
        user_message=text,
        session_id=str(session_id or ""),
        task_id=str(task_id or ""),
        turn_id=str(turn_id or ""),
        source=str(source or ""),
        explicit_paths=paths,
        material_suffixes=tuple(_dedupe([_suffix(path) for path in paths if _suffix(path)])),
        raw_action_markers=tuple(_markers(text.lower(), ("问", "解释", "审查", "检查", "计划", "读", "看", "搜索", "修改", "实现", "修复", "运行", "验证", "继续", "停止"))),
        raw_constraint_markers=tuple(_markers(text.lower(), ("不要", "不能", "只", "必须", "禁止", "不要改", "只分析", "不要修改", "不要搜索", "不要联网"))),
        explicit_selection=dict(explicit_selection or {}),
        diagnostics={
            "fact_only": True,
            "does_not_select_intent": True,
            "does_not_select_route": True,
            "does_not_select_tools": True,
        },
    )


def _extract_paths(text: str) -> list[str]:
    paths: list[str] = []
    for match in PATH_RE.finditer(text or ""):
        value = _clean_path_candidate(str(match.group("path") or ""))
        if value:
            paths.append(value.replace("\\", "/"))
    return paths


def _clean_path_candidate(value: str) -> str:
    text = str(value or "").strip().strip("'\"`，,。；;")
    if not text:
        return ""
    known_root = re.search(
        r"(?i)((?:[A-Za-z]:[\\/])?(?:\.{0,2}[\\/])?(?:backend|frontend|docs|storage|tests|scripts|output|src|app|packages|knowledge|Data|data)[\\/][^\s，,。；;]+)",
        text,
    )
    if known_root:
        return known_root.group(1).strip().strip("'\"`，,。；;")
    extension = re.search(
        r"(?i)([^\s，,。；;]+?\.(?:json|py|md|txt|log|csv|tsv|xlsx|xls|pdf|yaml|yml|toml|ts|tsx|js|jsx|css|html|parquet))",
        text,
    )
    if extension:
        return extension.group(1).strip().strip("'\"`，,。；;")
    return text


def _suffix(path: str) -> str:
    value = str(path or "").strip().lower()
    if "." not in value:
        return ""
    return "." + value.rsplit(".", 1)[-1]


def _markers(text: str, candidates: tuple[str, ...]) -> list[str]:
    return _dedupe([marker for marker in candidates if marker and marker in text])


def _dedupe(values: list[str] | tuple[str, ...]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _slug(value: str) -> str:
    slug = "".join(ch if ch.isalnum() else "_" for ch in str(value or "").lower()).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug or "runtime"
