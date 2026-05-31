from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


INTERNAL_TERMS = (
    "runtime_envelope",
    "task_run_id",
    "packet_id",
    "segment_plan",
    "payload_ref",
    "intent",
    "意图分类",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect model-visible runtime prompt packet size and boundaries.")
    parser.add_argument("target", help="Packet JSON path, payload ref, or task_run_id.")
    parser.add_argument("--base-dir", default=str(Path(__file__).resolve().parents[1]), help="Backend directory.")
    args = parser.parse_args()

    base_dir = Path(args.base_dir).resolve()
    packet_path = _resolve_target(base_dir, args.target)
    packet = _read_json(packet_path)
    messages = list(packet.get("model_messages") or [])
    segments_by_index = _segments_by_message_index(packet)

    print(f"packet_path: {packet_path}")
    print(f"message_count: {len(messages)}")
    print(f"model_chars: {sum(len(str(item.get('content') or '')) for item in messages)}")
    diagnostics = dict(packet.get("diagnostics") or {})
    if diagnostics:
        print(f"diagnostics_payload_size_bytes: {diagnostics.get('payload_size_bytes', '')}")
    print("")
    print("messages:")
    for index, message in enumerate(messages):
        segment = segments_by_index.get(index, {})
        content = str(dict(message).get("content") or "")
        terms = [term for term in INTERNAL_TERMS if term in content]
        print(
            f"- index={index} role={message.get('role', '')} kind={segment.get('kind', message.get('kind', ''))} "
            f"cache_scope={segment.get('cache_scope', message.get('cache_scope', ''))} "
            f"cache_role={segment.get('cache_role', message.get('cache_role', ''))} "
            f"chars={len(content)} internal_terms={','.join(terms)}"
        )
        payload = _json_payload_after_title(content)
        if isinstance(payload, dict):
            for key, size in _top_field_sizes(payload)[:5]:
                print(f"  field {key}: {size} chars")
    return 0


def _resolve_target(base_dir: Path, target: str) -> Path:
    raw = str(target or "").strip()
    direct = Path(raw)
    if direct.is_file():
        return direct.resolve()
    roots = _search_roots(base_dir)
    if raw.startswith("rtpayload:"):
        digest = raw.split(":", 1)[1]
        matches = _payload_digest_matches(roots, digest)
        if matches:
            return matches[0].resolve()
    if raw.startswith("taskrun:") or raw.startswith("turnrun:"):
        packet_from_tail = _packet_path_from_runtime_tail(roots, raw)
        if packet_from_tail is not None:
            return packet_from_tail.resolve()
        matches = []
        for root in roots:
            matches.extend(path for path in root.rglob("*.json") if _json_file_mentions(path, raw))
        packet_matches = [path for path in matches if _json_file_mentions(path, "model_messages")]
        if packet_matches:
            return sorted(packet_matches, key=lambda item: item.stat().st_mtime, reverse=True)[0].resolve()
    raise FileNotFoundError(f"Could not resolve packet target: {target}")


def _search_roots(base_dir: Path) -> list[Path]:
    project_root = base_dir.parent if base_dir.name == "backend" else base_dir
    candidates = [
        base_dir,
        project_root / "storage" / "runtime_state",
        project_root / "storage",
        project_root / "output" / "test_runs",
    ]
    roots: list[Path] = []
    for candidate in candidates:
        if candidate.exists() and candidate not in roots:
            roots.append(candidate)
    return roots


def _payload_digest_matches(roots: list[Path], digest: str) -> list[Path]:
    matches: list[Path] = []
    for root in roots:
        direct = root / "event_payloads" / digest[:2] / f"{digest}.json"
        if direct.is_file():
            matches.append(direct)
            continue
        matches.extend(root.rglob(f"{digest}.json"))
    return sorted(matches, key=lambda item: item.stat().st_mtime, reverse=True)


def _packet_path_from_runtime_tail(roots: list[Path], task_run_id: str) -> Path | None:
    for root in roots:
        tails = root / "event_index" / "tails"
        if not tails.exists():
            continue
        for path in sorted(tails.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if str(payload.get("task_run_id") or "") != task_run_id:
                continue
            events = [dict(item) for item in list(payload.get("events") or []) if isinstance(item, dict)]
            for event in reversed(events):
                if str(event.get("event_type") or "") != "runtime_invocation_packet_compiled":
                    continue
                refs = dict(event.get("refs") or {})
                payload_ref = str(refs.get("payload_ref") or dict(event.get("payload") or {}).get("payload_ref") or "")
                if payload_ref.startswith("rtpayload:"):
                    matches = _payload_digest_matches(roots, payload_ref.split(":", 1)[1])
                    if matches:
                        return matches[0]
                payload_path = str(refs.get("payload_path") or "").strip()
                if payload_path:
                    candidate = root / payload_path
                    if candidate.is_file():
                        return candidate
            return None
    return None


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and "packet" in payload and isinstance(payload.get("packet"), dict):
        payload = dict(payload["packet"])
    if isinstance(payload, dict) and isinstance(payload.get("payload"), dict):
        event_payload = dict(payload["payload"])
        if isinstance(event_payload.get("packet"), dict):
            payload = dict(event_payload["packet"])
    if not isinstance(payload, dict):
        raise ValueError(f"Packet payload must be a JSON object: {path}")
    return payload


def _segments_by_message_index(packet: dict[str, Any]) -> dict[int, dict[str, Any]]:
    plan = dict(packet.get("segment_plan") or {})
    segments: dict[int, dict[str, Any]] = {}
    for raw in list(plan.get("segments") or []):
        if not isinstance(raw, dict):
            continue
        try:
            index = int(raw.get("model_message_index"))
        except (TypeError, ValueError):
            continue
        segments[index] = raw
    return segments


def _json_file_mentions(path: Path, needle: str) -> bool:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return False
    return needle in text and "model_messages" in text


def _json_payload_after_title(content: str) -> Any | None:
    if not content:
        return None
    candidate = content.split("\n", 1)[1] if "\n" in content else content
    try:
        return json.loads(candidate)
    except Exception:
        return None


def _top_field_sizes(payload: dict[str, Any]) -> list[tuple[str, int]]:
    sizes = [
        (str(key), len(json.dumps(value, ensure_ascii=False, sort_keys=True)))
        for key, value in payload.items()
    ]
    return sorted(sizes, key=lambda item: item[1], reverse=True)


if __name__ == "__main__":
    raise SystemExit(main())
