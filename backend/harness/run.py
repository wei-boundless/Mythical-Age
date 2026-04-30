from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Unified test harness entrypoint.")
    parser.add_argument(
        "--profile",
        choices=(
            "smoke",
            "stable",
            "full",
            "deep",
            "benchmark",
            "regression",
            "chain",
            "functional",
            "system",
            "scenario",
            "long",
        ),
        required=True,
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args, extra_args = parser.parse_known_args()
    backend_dir = Path(__file__).resolve().parents[1]

    if args.profile == "regression":
        target = backend_dir / "tests" / "run_regression_gate.py"
        cmd = [sys.executable, str(target), "--profile", "full"]
    elif args.profile in {"chain", "functional", "system", "scenario"}:
        target = backend_dir / "tests" / "run_regression_gate.py"
        cmd = [sys.executable, str(target), "--profile", args.profile]
    elif args.profile == "long":
        target = backend_dir / "tests" / "system_eval" / "long_runner.py"
        cmd = [sys.executable, str(target)]
    else:
        target = backend_dir / "tests" / "system_eval" / "runner.py"
        cmd = [sys.executable, str(target), "--profile", args.profile]

    cmd.extend(list(extra_args or []))
    completed = subprocess.run(cmd, cwd=str(backend_dir), check=False)
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
