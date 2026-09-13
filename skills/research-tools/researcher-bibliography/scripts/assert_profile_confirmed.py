#!/usr/bin/env python3
"""PI-gate precondition: refuse to run the full pass on an unconfirmed profile.

The skill's #1 rule is that identity disambiguation is a human decision — the
full pass must not run until the PI has confirmed a profile. That rule used to
live only in prose. This script makes it a machine-enforced precondition: call
it immediately before `author_gap_check.py`; a non-zero exit means "do not
proceed — the gate is not cleared".

Blocks (exit 2) unless BOTH hold:
  - profile_status == "confirmed"
  - accepted_openalex_author_ids is non-empty

Tolerates both the flat profile schema (method.md) and the nested `authors:`
schema seen in real runs, via the shared loader in build_author_map_verdict.

Read-only; prints a one-line verdict.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import build_author_map_verdict as bv


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--profile", type=Path, required=True, help="profile.yaml to check")
    args = ap.parse_args(argv)

    if not args.profile.exists():
        print(f"BLOCKED: profile not found: {args.profile}", file=sys.stderr)
        print("  → run the identity pass, present candidates to the PI, and have "
              "her confirm a profile.yaml before the full pass.", file=sys.stderr)
        return 2

    prof = bv.load_profile(args.profile)
    if prof is None:
        print(f"BLOCKED: cannot parse a profile from {args.profile}", file=sys.stderr)
        return 2

    status = str(prof.get("profile_status") or "").strip()
    accepted = list(prof.get("accepted_openalex_author_ids") or [])

    problems = []
    if status != "confirmed":
        problems.append(f'profile_status is "{status or "unset"}", must be "confirmed"')
    if not accepted:
        problems.append("accepted_openalex_author_ids is empty")

    if problems:
        print("BLOCKED: PI-gate not cleared —", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        print("  Do NOT run the full pass. Present the identity candidates + the "
              "cross-model second opinion to the PI first.", file=sys.stderr)
        return 2

    print(f"OK: PI-gate cleared — profile_status=confirmed, "
          f"{len(accepted)} accepted author id(s): {', '.join(accepted)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
