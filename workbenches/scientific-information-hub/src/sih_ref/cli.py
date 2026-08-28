"""Command-line interface for the SIH public reference implementation."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Sequence

from .pipeline import run_pipeline


PACKAGE_ROOT = Path(__file__).resolve().parents[2]


def _iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD") from None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sih-reference")
    subparsers = parser.add_subparsers(dest="command", required=True)
    demo = subparsers.add_parser("demo", help="run the deterministic synthetic fixture set")
    demo.add_argument("--date", type=_iso_date, default=date(2026, 1, 15))
    demo.add_argument("--output-dir", type=Path, default=PACKAGE_ROOT / "demo" / "output")

    run = subparsers.add_parser("run", help="run an explicit local configuration")
    run.add_argument("--config", type=Path, required=True)
    run.add_argument("--profile", type=Path, required=True)
    run.add_argument("--output-dir", type=Path, required=True)
    run.add_argument("--date", type=_iso_date, default=date.today())
    run.add_argument("--live", action="store_true", help="allow configured network source adapters")
    run.add_argument("--llm", action="store_true", help="allow configured LLM triage")
    run.add_argument("--publish", action="store_true", help="allow an enabled network sink")
    run.add_argument("--stateless", action="store_true", help="do not read or persist incremental state")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "demo":
        result = run_pipeline(
            config_path=PACKAGE_ROOT / "config" / "sources.demo.json",
            profile_path=PACKAGE_ROOT / "config" / "profile.example.json",
            output_dir=args.output_dir,
            as_of=args.date,
            stateless=True,
            deterministic=True,
        )
    else:
        result = run_pipeline(
            config_path=args.config,
            profile_path=args.profile,
            output_dir=args.output_dir,
            as_of=args.date,
            live=args.live,
            llm_enabled=args.llm,
            publish=args.publish,
            stateless=args.stateless,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["daily_status"] not in {"failed", "degraded"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
