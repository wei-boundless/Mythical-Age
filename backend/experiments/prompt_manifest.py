from __future__ import annotations

from pathlib import Path
from typing import Any

from experiments.artifacts import read_json_file


def get_turn_prompt_manifest(output_dir: Path, turn_id: str) -> dict[str, Any]:
    turn_path = _find_turn_path(output_dir, turn_id)
    if turn_path is None:
        return {
            "status": "missing_manifest",
            "reason": "没有找到对应 turn artifact。",
            "prompt_manifest": None,
        }
    payload = read_json_file(turn_path, {})
    manifest = extract_prompt_manifest_from_turn(payload if isinstance(payload, dict) else {})
    if not manifest:
        return {
            "status": "missing_manifest",
            "reason": "此运行没有记录 prompt manifest。需要重新运行测试后才会生成。",
            "prompt_manifest": None,
        }
    return {
        "status": "available",
        "reason": "",
        "prompt_manifest": manifest,
    }


def extract_prompt_manifest_from_turn(payload: dict[str, Any]) -> dict[str, Any] | None:
    for event in list(payload.get("events") or []):
        if not isinstance(event, dict):
            continue
        event_name = str(event.get("event") or "")
        data = event.get("data")
        if event_name != "prompt_manifest" or not isinstance(data, dict):
            continue
        manifest = data.get("prompt_manifest")
        if isinstance(manifest, dict):
            return manifest
    return None


def _find_turn_path(output_dir: Path, turn_id: str) -> Path | None:
    normalized = str(turn_id or "").strip()
    if not normalized or "/" in normalized or "\\" in normalized or normalized.startswith("."):
        return None
    for path in output_dir.glob("artifacts/**/turn-*.json"):
        if path.stem == normalized:
            return path
    return None
