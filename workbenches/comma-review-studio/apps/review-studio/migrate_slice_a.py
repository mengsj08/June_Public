#!/usr/bin/env python3
"""Dry-run or apply the Scientific Review v1.1 Slice A data migration."""

import argparse
import json
import os

import server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--apply", action="store_true", help="write normalized sidecars after byte backups")
    args = parser.parse_args()
    report = server.migrate_slice_a_data(
        os.path.realpath(os.path.expanduser(args.data_root)),
        apply=args.apply,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
