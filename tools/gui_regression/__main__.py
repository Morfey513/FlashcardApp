from __future__ import annotations

import argparse
from pathlib import Path

from .configuration import PROFILES, RunConfig
from .runner import run


def main() -> int:
    parser = argparse.ArgumentParser(description="Visible Windows Study Buddy GUI regression runner")
    parser.add_argument("run", nargs="?", default="run")
    parser.add_argument("--profile", choices=sorted(PROFILES), default="smoke")
    parser.add_argument("--scenario", help="one Workflows method for diagnostic profile")
    parser.add_argument("--validation", choices=("no-uia", "uia"), help="bounded launcher validation; no role matrix")
    parser.add_argument("--repetitions", type=int, default=1, help="number of independent launcher processes")
    parser.add_argument("--hold-seconds", type=float, default=30.0, help="healthy-window observation duration per launcher")
    parser.add_argument(
        "--artifacts",
        type=Path,
        default=Path(".temp") / "artifacts" / "windows-gui",
        help="artifact root (default: .temp/artifacts/windows-gui)",
    )
    parser.add_argument("--keep-runtime", action="store_true")
    parser.add_argument("--procdump", type=Path)
    args = parser.parse_args()
    if args.repetitions < 1 or args.hold_seconds < 0:
        parser.error("--repetitions must be >= 1 and --hold-seconds must be >= 0")
    return run(RunConfig(
        args.profile, args.artifacts, args.scenario, args.keep_runtime, args.procdump,
        validation=args.validation, repetitions=args.repetitions, hold_seconds=args.hold_seconds,
    ))


if __name__ == "__main__":
    raise SystemExit(main())
