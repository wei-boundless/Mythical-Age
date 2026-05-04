from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from health_system.maintenance.test_system.case_registry import PROFILE_ORDER, cases_for_profile


TEST_FUNCTION_PATTERN = re.compile(r"^\s*def\s+test_[A-Za-z0-9_]*\s*\(", re.MULTILINE)


@dataclass(frozen=True, slots=True)
class RegressionTarget:
    path: str
    group: str
    description: str = ""


@dataclass(slots=True)
class RegressionOutcome:
    name: str
    path: str
    group: str
    runner: str
    command: list[str]
    passed: bool
    returncode: int
    duration_ms: float
    started_at: str
    ended_at: str
    stdout_tail: str
    stderr_tail: str
    artifact_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


PROFILES: tuple[str, ...] = tuple(PROFILE_ORDER)


def backend_root() -> Path:
    return Path(__file__).resolve().parents[1]


def detect_runner(path: Path) -> str:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return "python"
    if TEST_FUNCTION_PATTERN.search(content):
        return "pytest"
    return "python"


def build_profile(profile: str) -> tuple[RegressionTarget, ...]:
    deduped: list[RegressionTarget] = []
    seen: set[str] = set()
    for case in cases_for_profile(profile):
        target = RegressionTarget(case.path, case.layer, case.title)
        if target.path in seen:
            continue
        seen.add(target.path)
        deduped.append(target)
    return tuple(deduped)


def _tail(text: str, *, limit: int = 1200) -> str:
    normalized = str(text or "").strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[-limit:]


def _slug(value: str) -> str:
    parts = []
    for char in value:
        if char.isalnum():
            parts.append(char.lower())
        else:
            parts.append("-")
    slug = "".join(parts).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "artifact"


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def _build_command(root: Path, target_path: Path, runner: str) -> list[str]:
    if runner == "pytest":
        return [sys.executable, "-m", "pytest", str(target_path), "-q"]
    return [sys.executable, str(target_path)]


def execute_target(
    target: RegressionTarget,
    *,
    root: Path | None = None,
    artifact_dir: Path | None = None,
) -> RegressionOutcome:
    project_root = root or backend_root()
    target_path = project_root / target.path
    runner = detect_runner(target_path)
    command = _build_command(project_root, target_path, runner)
    started_at = _now_iso()
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=str(project_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    duration_ms = round((time.perf_counter() - started) * 1000.0, 2)
    ended_at = _now_iso()
    artifact_path = ""
    if artifact_dir is not None:
        artifact_dir.mkdir(parents=True, exist_ok=True)
        log_path = artifact_dir / f"{_slug(target.path)}.log"
        log_path.write_text(
            "\n".join(
                [
                    f"$ {' '.join(command)}",
                    "",
                    "[stdout]",
                    completed.stdout,
                    "",
                    "[stderr]",
                    completed.stderr,
                ]
            ),
            encoding="utf-8",
        )
        artifact_path = str(log_path)
    return RegressionOutcome(
        name=target_path.name,
        path=target.path,
        group=target.group,
        runner=runner,
        command=command,
        passed=completed.returncode == 0,
        returncode=int(completed.returncode),
        duration_ms=duration_ms,
        started_at=started_at,
        ended_at=ended_at,
        stdout_tail=_tail(completed.stdout),
        stderr_tail=_tail(completed.stderr),
        artifact_path=artifact_path,
    )


def run_profile(
    profile: str,
    *,
    root: Path | None = None,
    artifact_dir: Path | None = None,
) -> list[RegressionOutcome]:
    project_root = root or backend_root()
    return [
        execute_target(target, root=project_root, artifact_dir=artifact_dir)
        for target in build_profile(profile)
    ]


def summarize_outcomes(profile: str, outcomes: list[RegressionOutcome]) -> dict[str, Any]:
    failed = [outcome for outcome in outcomes if not outcome.passed]
    return {
        "profile": profile,
        "total": len(outcomes),
        "passed": len(outcomes) - len(failed),
        "failed": len(failed),
        "results": [outcome.to_dict() for outcome in outcomes],
    }


def _print_summary(summary: dict[str, Any]) -> None:
    print(
        f"[regression-gate] profile={summary['profile']} total={summary['total']} "
        f"passed={summary['passed']} failed={summary['failed']}"
    )
    for item in summary["results"]:
        status = "PASS" if item["passed"] else "FAIL"
        print(f"  [{status}] {item['path']} ({item['runner']}, {item['duration_ms']} ms)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Curated backend regression gate.")
    parser.add_argument("--profile", choices=PROFILES, default="chain")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    parser.add_argument("--artifact-dir", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    artifact_dir = Path(args.artifact_dir) if str(args.artifact_dir).strip() else None
    outcomes = run_profile(args.profile, artifact_dir=artifact_dir)
    summary = summarize_outcomes(args.profile, outcomes)
    if args.emit_json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        _print_summary(summary)
    return 0 if summary["failed"] == 0 else 1
