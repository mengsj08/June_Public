#!/usr/bin/env python3
"""Plan a Mario Event batch without writing any upstream source.

The planner is deliberately boring: it indexes explicitly supplied source
roots/files/manifests, snapshots content identities, proposes a small Event
scope from an optional read-only Event ledger, and runs proposal-only Event
discovery. It does not reconstruct Events or materialize Units.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
from pathlib import Path


SCHEMA_VERSION = "mario.batch-scope/v0"
INVENTORY_VERSION = "mario.source-inventory/v0"
UNRESOLVED_VERSION = "mario.unresolved-identities/v0"
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_ROOT = Path(
    os.environ.get("KANBAN_DATA_ROOT") or REPO_ROOT / ".kanban-data"
).expanduser().resolve(strict=False)
DEFAULT_BATCH_ROOT = DEFAULT_DATA_ROOT / "mario-batch-v0"
DEFAULT_LIBRARY_ROOT = Path(
    os.environ.get("KANBAN_LIBRARY_ROOT") or REPO_ROOT / "demo"
).expanduser().resolve(strict=False)
DEFAULT_LEDGER_DIR = DEFAULT_LIBRARY_ROOT / "案例/_事件账"
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def stable_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def batch_hash(value):
    return "sha256:" + hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()


def read_jsonl(path):
    rows = []
    path = Path(path)
    if not path.exists():
        return rows
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if isinstance(row, dict):
                row["_jsonl_line"] = line_number
                rows.append(row)
    return rows


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_jsonl(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
    )
    path.write_text(payload, encoding="utf-8")


def ensure_under(path, root, label):
    path = Path(path).expanduser().resolve()
    root = Path(root).expanduser().resolve()
    if path != root and root not in path.parents:
        raise ValueError(f"{label} must be under {root}: {path}")
    return path


def source_format(path):
    suffix = path.suffix.lower()
    if suffix in {".md", ".txt", ".json", ".jsonl", ".csv"}:
        return suffix.removeprefix(".")
    if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
        return "image"
    if suffix in {".pdf", ".pptx", ".xlsx", ".zip", ".html"}:
        return suffix.removeprefix(".")
    return suffix.removeprefix(".") or "unknown"


def date_hint(path, stat):
    text = str(path)
    match = DATE_RE.search(text)
    if match:
        return {"source": "path", "value": match.group(0)}
    return {"source": "mtime", "value": str(int(stat.st_mtime))}


def inventory_sources(source_roots, *, library_root=DEFAULT_LIBRARY_ROOT):
    rows = []
    seen_hashes = {}
    for root in source_roots:
        root = ensure_under(root, library_root, "source root")
        if not root.exists():
            raise FileNotFoundError(f"source root is missing: {root}")
        files = [root] if root.is_file() else sorted(path for path in root.rglob("*") if path.is_file())
        for path in files:
            stat = path.stat()
            digest = sha256_file(path)
            duplicate_of = seen_hashes.get(digest)
            row = {
                "schema_version": INVENTORY_VERSION,
                "path": str(path),
                "source_root": str(root),
                "sha256": digest,
                "size_bytes": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "format": source_format(path),
                "timeline_hint": date_hint(path, stat),
                "duplicate_of": duplicate_of,
                "content_locator": {"type": "local_file", "path": str(path)},
            }
            if not duplicate_of:
                seen_hashes[digest] = str(path)
            rows.append(row)
    return sorted(rows, key=lambda row: row["path"])


def _manifest_row_date(row):
    value = row.get("event_date_hint")
    if value and DATE_RE.fullmatch(str(value)):
        return str(value)
    for candidate in (
        row.get("source_path"),
        (row.get("source_locator") or {}).get("path"),
    ):
        match = DATE_RE.search(str(candidate or ""))
        if match:
            return match.group(0)
        month = re.search(r"(?P<year>20\d{2})-(?P<month>\d{2})", str(candidate or ""))
        day = re.search(
            r"(?:^|[/_-])(?P<month>\d{2})(?P<day>\d{2})(?:[-_/]|$)",
            str(candidate or ""),
        )
        if month and day and month.group("month") == day.group("month"):
            return f"{month.group('year')}-{day.group('month')}-{day.group('day')}"
    return None


def _manifest_row_matches_people(row, people):
    people = [str(person).casefold() for person in people or [] if str(person).strip()]
    if not people:
        return True
    haystack = " ".join(
        [
            str(row.get("source_path") or ""),
            str((row.get("source_locator") or {}).get("path") or ""),
            " ".join(str(value) for value in row.get("member_mentions") or []),
        ]
    ).casefold()
    return any(person in haystack for person in people)


def inventory_manifests(
    manifest_paths,
    *,
    start,
    end,
    people=None,
    source_ids=None,
    library_root=DEFAULT_LIBRARY_ROOT,
):
    wanted_ids = set(source_ids or [])
    rows = []
    for manifest_path in manifest_paths:
        manifest_path = ensure_under(manifest_path, library_root, "source manifest")
        for source in read_jsonl(manifest_path):
            source_id = source.get("source_id")
            if wanted_ids and source_id not in wanted_ids:
                continue
            if not _manifest_row_matches_people(source, people):
                continue
            event_date = _manifest_row_date(source)
            if event_date and ((start and event_date < start) or (end and event_date > end)):
                continue
            source_locator = source.get("source_locator") or {}
            source_path = str(
                source.get("source_path")
                or source_locator.get("path")
                or source_id
                or ""
            )
            git_blob_oid = source.get("git_blob_oid")
            if source_locator.get("repo") and git_blob_oid:
                content_locator = {
                    "type": "git_blob",
                    "repo": str(Path(source_locator["repo"]).expanduser().resolve()),
                    "blob_oid": git_blob_oid,
                    "ref": source_locator.get("ref"),
                    "path": source_locator.get("path"),
                }
            elif Path(source_path).expanduser().is_file():
                content_locator = {
                    "type": "local_file",
                    "path": str(Path(source_path).expanduser().resolve()),
                }
            else:
                content_locator = {
                    "type": "metadata_only",
                    "path": source_path,
                }
            rows.append({
                "schema_version": INVENTORY_VERSION,
                "source_id": source_id,
                "path": source_path,
                "source_root": str(manifest_path),
                "source_manifest": str(manifest_path),
                "sha256": source.get("sha256"),
                "git_blob_oid": git_blob_oid,
                "size_bytes": source.get("size_bytes"),
                "mtime_ns": None,
                "format": source_format(Path(source_path)),
                "source_kind": source.get("source_kind"),
                "timeline_hint": {
                    "source": "manifest_or_path",
                    "value": event_date,
                },
                "event_date_hint": event_date,
                "member_mentions": list(source.get("member_mentions") or []),
                "sensitivity": source.get("sensitivity"),
                "duplicate_of": None,
                "content_locator": content_locator,
            })
    return rows


def inventory_explicit_files(source_files):
    rows = []
    for value in source_files:
        path = Path(value).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"explicit source file is missing: {path}")
        stat = path.stat()
        rows.append({
            "schema_version": INVENTORY_VERSION,
            "source_id": "source-explicit-" + hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:16],
            "path": str(path),
            "source_root": str(path.parent),
            "sha256": sha256_file(path),
            "git_blob_oid": None,
            "size_bytes": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "format": source_format(path),
            "timeline_hint": date_hint(path, stat),
            "duplicate_of": None,
            "content_locator": {"type": "local_file", "path": str(path)},
            "sensitivity": "inherit_from_source",
        })
    return rows


def deduplicate_inventory(rows):
    seen = {}
    output = []
    for row in sorted(rows, key=lambda item: (str(item.get("path") or ""), str(item.get("source_id") or ""))):
        identity = row.get("sha256") or row.get("git_blob_oid")
        row = dict(row)
        row["duplicate_of"] = seen.get(identity) if identity else None
        if identity and identity not in seen:
            seen[identity] = row.get("path") or row.get("source_id")
        output.append(row)
    return output


def event_date(row):
    match = DATE_RE.search(str(row.get("canonical_time") or ""))
    return match.group(0) if match else ""


def within_window(row, start, end):
    date = event_date(row)
    if not date:
        return False
    return (not start or date >= start) and (not end or date <= end)


def load_event_context(ledger_dir):
    ledger_dir = Path(ledger_dir).expanduser().resolve()
    events = read_jsonl(ledger_dir / "events.jsonl")
    bindings = read_jsonl(ledger_dir / "participant-bindings.jsonl")
    assertions = read_jsonl(ledger_dir / "source-assertions.jsonl")
    return events, bindings, assertions


def select_seed_events(events, *, start, end, event_ids=None):
    explicit = set(event_ids or [])
    selected = []
    for row in events:
        if explicit and row.get("event_id") not in explicit:
            continue
        if not explicit and not within_window(row, start, end):
            continue
        if not explicit and len(row.get("participant_binding_ids") or []) < 2:
            continue
        selected.append(row)
    return sorted(selected, key=lambda row: (event_date(row), str(row.get("event_id") or "")))


def unresolved_identities(bindings, event_ids):
    event_ids = set(event_ids)
    rows = []
    for row in bindings:
        if row.get("event_id") not in event_ids:
            continue
        if row.get("entity_id"):
            continue
        rows.append({
            "schema_version": UNRESOLVED_VERSION,
            "event_id": row.get("event_id"),
            "binding_id": row.get("binding_id"),
            "participant_candidate_id": row.get("participant_candidate_id"),
            "role": row.get("role"),
            "role_label": row.get("role_label"),
            "participation_status": row.get("participation_status"),
            "evidence_refs": list(row.get("evidence_refs") or []),
            "reason": "No stable entity_id; keep as candidate, do not merge identity.",
        })
    return sorted(rows, key=lambda row: (row["event_id"], row["binding_id"] or ""))


def build_scope(
    *,
    source_roots,
    source_manifests=None,
    source_files=None,
    source_ids=None,
    mode="scan_shadow_only",
    batch_root,
    start,
    end,
    people,
    ledger_dir,
    event_ids=None,
    library_root=DEFAULT_LIBRARY_ROOT,
):
    ledger_dir = ensure_under(ledger_dir, library_root, "event ledger dir")
    events, bindings, assertions = load_event_context(ledger_dir)
    seed_events = (
        []
        if mode == "scan_discovery_only"
        else select_seed_events(events, start=start, end=end, event_ids=event_ids)
    )
    binding_by_event = {}
    for row in bindings:
        binding_by_event.setdefault(row.get("event_id"), []).append(row)
    assertion_by_event = {}
    for row in assertions:
        assertion_by_event.setdefault(row.get("event_id"), []).append(row)

    evidence_events = []
    for event in seed_events:
        event_id = event.get("event_id")
        evidence_events.append({
            "event_id": event_id,
            "title": event.get("title"),
            "canonical_time": event.get("canonical_time"),
            "event_type": event.get("event_type"),
            "participant_count": len(binding_by_event.get(event_id) or event.get("participant_binding_ids") or []),
            "participant_binding_ids": list(event.get("participant_binding_ids") or []),
            "source_relation_ids": list(event.get("source_relation_ids") or []),
            "assertion_ids": [
                row.get("assertion_id")
                for row in assertion_by_event.get(event_id, [])
                if row.get("assertion_id")
            ],
        })

    payload = {
        "schema_version": SCHEMA_VERSION,
        "batch_id": "mario-batch-v0-" + hashlib.sha256(
            stable_json({
                "source_roots": [str(Path(root).expanduser().resolve()) for root in source_roots],
                "source_manifests": [str(Path(path).expanduser().resolve()) for path in source_manifests or []],
                "source_files": [str(Path(path).expanduser().resolve()) for path in source_files or []],
                "source_ids": sorted(source_ids or []),
                "start": start,
                "end": end,
                "event_ids": event_ids or [],
            }).encode("utf-8")
        ).hexdigest()[:16],
        "mode": mode,
        "batch_root": str(Path(batch_root).expanduser().resolve()),
        "library_root": str(Path(library_root).expanduser().resolve()),
        "source_roots": [str(ensure_under(root, library_root, "source root")) for root in source_roots],
        "source_manifests": [
            str(ensure_under(path, library_root, "source manifest"))
            for path in source_manifests or []
        ],
        "source_files": [str(Path(path).expanduser().resolve()) for path in source_files or []],
        "source_ids": sorted(source_ids or []),
        "source_inputs": (
            [{"type": "root", "value": str(ensure_under(root, library_root, "source root"))} for root in source_roots]
            + [{"type": "manifest", "value": str(ensure_under(path, library_root, "source manifest"))} for path in source_manifests or []]
            + [{"type": "explicit_file", "value": str(Path(path).expanduser().resolve())} for path in source_files or []]
        ),
        "time_window": {"start": start, "end": end},
        "people": list(people or []),
        "event_ledger_dir": str(ledger_dir),
        "same_event_decision_key": {
            "auto_same_event_allowed_only_with": [
                "same recording or transcript identity",
                "same minutes/source relation identity",
                "explicit time, place, and participant intersection confirmed by source",
            ],
            "weak_similarity_only_creates_review_proposal": [
                "same date",
                "overlapping people",
                "similar topic or project",
            ],
        },
        "explicitly_not_authorized": [
            "promote",
            "event_ledger_write",
            "relationship_card_write",
            "mario_unit_write",
            "project_state_write",
            "identity_merge",
            "same_event_merge",
            "skip_source_verification",
        ],
        "evidence_events": evidence_events,
        "minimum_multiplayer_events_required": (
            0 if mode == "scan_discovery_only" else 3
        ),
    }
    payload["scope_hash"] = batch_hash(payload)
    return payload


def _load_discovery_module():
    module_name = "_mario_event_discovery_runtime"
    if module_name in sys.modules:
        return sys.modules[module_name]
    path = Path(__file__).with_name("discover_event_candidates.py")
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def run_plan(args):
    batch_root = Path(args.batch_root).expanduser().resolve()
    library_root = Path(args.library_root).expanduser().resolve()
    source_roots = [
        ensure_under(root, library_root, "source root")
        for root in getattr(args, "source_root", [])
    ]
    source_manifests = [
        ensure_under(path, library_root, "source manifest")
        for path in getattr(args, "source_manifest", [])
    ]
    source_files = list(getattr(args, "source_file", []))
    source_ids = list(getattr(args, "source_id", []))
    inventory = deduplicate_inventory(
        inventory_sources(source_roots, library_root=library_root)
        + inventory_manifests(
            source_manifests,
            start=args.start,
            end=args.end,
            people=args.person,
            source_ids=source_ids,
            library_root=library_root,
        )
        + inventory_explicit_files(source_files)
    )
    scope = build_scope(
        source_roots=source_roots,
        source_manifests=source_manifests,
        source_files=source_files,
        source_ids=source_ids,
        mode=getattr(args, "mode", "scan_shadow_only"),
        batch_root=batch_root,
        start=args.start,
        end=args.end,
        people=args.person,
        ledger_dir=args.event_ledger_dir,
        event_ids=args.event_id,
        library_root=library_root,
    )
    events, bindings, _ = load_event_context(scope["event_ledger_dir"])
    unresolved = unresolved_identities(
        bindings,
        [row["event_id"] for row in scope["evidence_events"]],
    )
    write_json(batch_root / "batch-scope.json", scope)
    write_jsonl(batch_root / "source-inventory.jsonl", inventory)
    write_jsonl(batch_root / "unresolved-identities.jsonl", unresolved)
    discovery = _load_discovery_module().discover(
        batch_root,
        scope["event_ledger_dir"],
    )
    print(json.dumps({
        "ok": True,
        "batch_root": str(batch_root),
        "scope_hash": scope["scope_hash"],
        "file_count": len(inventory),
        "event_detection_candidate_count": discovery["event_detection_candidate_count"],
        "event_boundary_review_count": discovery["boundary_review_count"],
        "evidence_event_count": len(scope["evidence_events"]),
        "unresolved_identity_count": len(unresolved),
    }, ensure_ascii=False, sort_keys=True))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-root", type=Path, default=DEFAULT_BATCH_ROOT)
    parser.add_argument("--library-root", type=Path, default=DEFAULT_LIBRARY_ROOT)
    parser.add_argument("--event-ledger-dir", type=Path, default=DEFAULT_LEDGER_DIR)
    parser.add_argument(
        "--mode",
        choices=("scan_shadow_only", "scan_discovery_only"),
        default="scan_shadow_only",
    )
    parser.add_argument("--source-root", action="append", default=[])
    parser.add_argument("--source-manifest", action="append", default=[])
    parser.add_argument("--source-file", action="append", default=[])
    parser.add_argument(
        "--source-id",
        action="append",
        default=[],
        help="Optional exact source_id filter for manifest rows",
    )
    parser.add_argument("--start", required=True, help="Inclusive YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="Inclusive YYYY-MM-DD")
    parser.add_argument("--person", action="append", default=[])
    parser.add_argument("--event-id", action="append", default=[])
    args = parser.parse_args(argv)
    if not (args.source_root or args.source_manifest or args.source_file):
        parser.error("at least one --source-root, --source-manifest, or --source-file is required")
    return run_plan(args)


if __name__ == "__main__":
    raise SystemExit(main())
