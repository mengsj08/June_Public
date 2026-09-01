#!/usr/bin/env python3
"""Re-verify a drug-label output directory against manifest.json."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from label_common import LabelError, verify_manifest, write_json


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir")
    parser.add_argument("--no-write", action="store_true", help="只打印，不刷新 verification.json")
    args = parser.parse_args()
    root = Path(args.output_dir).expanduser().resolve()
    manifest_path = root / "manifest.json"
    try:
        if not manifest_path.is_file():
            raise LabelError(f"缺少 manifest.json: {manifest_path}")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LabelError(f"manifest.json 无法读取: {exc}") from exc
        report = verify_manifest(root, manifest)
        if not args.no_write:
            write_json(root / "verification.json", report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1 if report["status"] == "fail" else 0
    except LabelError as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
