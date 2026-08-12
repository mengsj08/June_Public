#!/usr/bin/env python3
"""Read-only health audit for a Comma Review Studio data root."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any


KNOWN_SCHEMA_VERSIONS = {
    "comma-comments-view/v1.1",
    "comma-review-session/v1",
    "comma-review-run/v1",
    "comma-review-run-receipt/v1",
    "comma-review-conversation/v1",
    "comma-review-versions/v1",
    "comma-review-evidence-source/v1",
    "comma-review-import-receipt/v1",
    "comma-review-conflict-draft/v1",
    "comma-document-summary/v1",
    "comma-document-summary-ledger/v1",
    "comma-operation-journal/v1",
    "comma-operation-journal-entry/v1",
}

ACTIVE_RUN_STATES = {"queued", "running", "cancelling"}
EXIT_CLEAN = 0
EXIT_WARNING = 1
EXIT_ERROR = 2


def _sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _doc_store_key(path: str) -> str:
    return hashlib.sha256(path.encode("utf-8")).hexdigest()[:16]


def _rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _is_inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


class StoreAudit:
    def __init__(self, data_root: str | Path):
        self.root = Path(data_root).expanduser().resolve()
        self.counts: dict[str, int] = {
            "json_files": 0,
            "jsonl_files": 0,
            "documents": 0,
            "comments_sidecars": 0,
            "comment_event_ledgers": 0,
            "sessions": 0,
            "runs": 0,
            "conversations": 0,
            "version_indexes": 0,
            "version_blobs": 0,
            "evidence_sources": 0,
            "operation_journal_pending": 0,
            "operation_journal_finalized": 0,
            "operation_journal_inconsistent": 0,
        }
        self.warnings: list[dict[str, str]] = []
        self.errors: list[dict[str, str]] = []

    def warning(self, code: str, path: Path, detail: str) -> None:
        self.warnings.append({"code": code, "path": self._display_path(path), "detail": detail})

    def error(self, code: str, path: Path, detail: str) -> None:
        self.errors.append({"code": code, "path": self._display_path(path), "detail": detail})

    def _display_path(self, path: Path) -> str:
        try:
            return _rel(path.resolve(), self.root)
        except Exception:
            return str(path)

    def read_json(self, path: Path) -> Any | None:
        self.counts["json_files"] += 1
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            self.error("json_read_error", path, exc.__class__.__name__)
        except json.JSONDecodeError as exc:
            self.error("json_parse_error", path, f"line {exc.lineno} column {exc.colno}")
        return None

    def scan_jsonl(self, path: Path) -> list[dict[str, Any]]:
        self.counts["jsonl_files"] += 1
        rows: list[dict[str, Any]] = []
        try:
            with path.open(encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, 1):
                    if not line.strip():
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError as exc:
                        self.error("jsonl_parse_error", path, f"line {line_number} column {exc.colno}")
                        continue
                    if isinstance(row, dict):
                        rows.append(row)
                    else:
                        self.warning("jsonl_non_object", path, f"line {line_number}")
        except OSError as exc:
            self.error("jsonl_read_error", path, exc.__class__.__name__)
        return rows

    def check_schema(self, payload: Any, path: Path) -> None:
        if not isinstance(payload, dict):
            self.error("json_not_object", path, "top-level JSON is not an object")
            return
        schema = payload.get("schema_version")
        if schema is None:
            self.warning("schema_missing", path, "schema_version missing")
        elif schema not in KNOWN_SCHEMA_VERSIONS:
            self.warning("schema_unknown", path, str(schema))

    def doc_path(self, value: Any, owner: Path) -> Path | None:
        if not isinstance(value, str) or not value.strip():
            self.warning("doc_path_missing", owner, "doc_path is absent")
            return None
        candidate = (self.root / value).resolve()
        if not _is_inside(candidate, self.root):
            self.error("doc_path_outside_data_root", owner, value)
            return None
        if not candidate.is_file():
            self.warning("doc_path_missing_file", owner, value)
            return None
        return candidate

    def run(self) -> dict[str, Any]:
        if not self.root.is_dir():
            self.error("data_root_missing", self.root, "data root is not a directory")
            return self.summary()
        self.scan_documents()
        self.scan_comment_sidecars()
        self.scan_sessions()
        self.scan_conversations()
        self.scan_versions()
        self.scan_evidence()
        self.scan_operation_journal()
        return self.summary()

    def scan_documents(self) -> None:
        for path in self.root.rglob("*.md"):
            if ".comma-review" in path.parts:
                continue
            self.counts["documents"] += 1

    def scan_comment_sidecars(self) -> None:
        sidecars = {path for path in self.root.rglob("*.comments.json")}
        ledgers = {path for path in self.root.rglob("*.comment-events.jsonl")}
        self.counts["comments_sidecars"] = len(sidecars)
        self.counts["comment_event_ledgers"] = len(ledgers)
        for path in sorted(sidecars):
            payload = self.read_json(path)
            self.check_schema(payload, path)
            doc = Path(str(path)[:-len(".comments.json")])
            if not doc.is_file():
                self.warning("orphan_comments_sidecar", path, "matching Markdown document missing")
        for path in sorted(ledgers):
            self.scan_jsonl(path)
            doc = Path(str(path)[:-len(".comment-events.jsonl")])
            if not doc.is_file():
                self.warning("orphan_comment_event_ledger", path, "matching Markdown document missing")
            if doc.with_suffix(doc.suffix + ".comments.json") not in sidecars:
                self.warning("comment_event_without_sidecar", path, "matching comments sidecar missing")

    def scan_sessions(self) -> None:
        root = self.root / "review-sessions"
        if not root.is_dir():
            return
        for path in sorted(root.glob("*.json")):
            payload = self.read_json(path)
            self.check_schema(payload, path)
            if not isinstance(payload, dict):
                continue
            self.counts["sessions"] += 1
            self.doc_path(payload.get("doc_path"), path)
            runs = [payload.get("run"), *(payload.get("runs") or [])]
            for run in runs:
                if isinstance(run, dict):
                    self.counts["runs"] += 1
                    if run.get("schema_version") and run.get("schema_version") not in KNOWN_SCHEMA_VERSIONS:
                        self.warning("schema_unknown", path, str(run.get("schema_version")))

    def scan_conversations(self) -> None:
        root = self.root / "conversations"
        if not root.is_dir():
            return
        for path in sorted(root.glob("*.json")):
            payload = self.read_json(path)
            self.check_schema(payload, path)
            if isinstance(payload, dict):
                self.counts["conversations"] += 1
                self.doc_path(payload.get("doc_path"), path)

    def scan_versions(self) -> None:
        root = self.root / ".comma-review" / "versions"
        if not root.is_dir():
            return
        for index_path in sorted(root.glob("*/index.json")):
            payload = self.read_json(index_path)
            self.check_schema(payload, index_path)
            if not isinstance(payload, dict):
                continue
            self.counts["version_indexes"] += 1
            doc = self.doc_path(payload.get("doc_path"), index_path)
            expected_key = _doc_store_key(_rel(doc, self.root)) if doc else ""
            if expected_key and index_path.parent.name != expected_key:
                self.warning("version_doc_key_mismatch", index_path, "index directory does not match doc_path")
            blobs = index_path.parent / "blobs"
            for entry in payload.get("versions") or []:
                if not isinstance(entry, dict):
                    self.warning("version_entry_invalid", index_path, "non-object version entry")
                    continue
                rev = entry.get("rev")
                if isinstance(rev, str):
                    blob = blobs / f"{rev}.md"
                    if not blob.is_file():
                        self.warning("version_blob_missing", index_path, rev)
            if blobs.is_dir():
                known = {f"{item.get('rev')}.md" for item in payload.get("versions") or [] if isinstance(item, dict)}
                for blob in blobs.glob("*.md"):
                    self.counts["version_blobs"] += 1
                    if blob.name not in known:
                        self.warning("orphan_version_blob", blob, "blob not referenced by index")

    def scan_evidence(self) -> None:
        root = self.root / ".comma-review" / "evidence-sources"
        if not root.is_dir():
            return
        for record_path in sorted(root.glob("*/*/record.json")):
            payload = self.read_json(record_path)
            self.check_schema(payload, record_path)
            if not isinstance(payload, dict):
                continue
            self.counts["evidence_sources"] += 1
            evidence_root = record_path.parent
            if not (evidence_root / "source.pdf").is_file():
                self.warning("evidence_pdf_missing", record_path, "source.pdf missing")
            pages_path = evidence_root / "pages.json"
            if not pages_path.is_file():
                self.warning("evidence_pages_missing", record_path, "pages.json missing")
            else:
                pages = self.read_json(pages_path)
                if not isinstance(pages, list):
                    self.warning("evidence_pages_invalid", pages_path, "pages JSON is not a list")

    def scan_operation_journal(self) -> None:
        journal = self.root / ".comma-review" / "operation-journal.json"
        if not journal.is_file():
            return
        payload = self.read_json(journal)
        self.check_schema(payload, journal)
        rows = payload.get("entries") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            self.error("operation_journal_invalid", journal, "entries is not a list")
            return
        for row in rows:
            if not isinstance(row, dict):
                self.warning("operation_journal_entry_invalid", journal, "non-object entry")
                continue
            if row.get("schema_version") and row.get("schema_version") not in KNOWN_SCHEMA_VERSIONS:
                self.warning("schema_unknown", journal, str(row.get("schema_version")))
            status = str(row.get("status") or "pending")
            if status in {"finalized", "completed"}:
                self.counts["operation_journal_finalized"] += 1
            elif status == "inconsistent":
                self.counts["operation_journal_inconsistent"] += 1
                self.warning("operation_journal_inconsistent", journal, "inconsistent entry present")
            else:
                self.counts["operation_journal_pending"] += 1
                self.warning("operation_journal_pending", journal, "unfinished entry present")

    def summary(self) -> dict[str, Any]:
        if self.errors:
            exit_code = EXIT_ERROR
            status = "error"
        elif self.warnings:
            exit_code = EXIT_WARNING
            status = "warning"
        else:
            exit_code = EXIT_CLEAN
            status = "clean"
        return {
            "schema_version": "comma-review-store-audit/v1",
            "status": status,
            "exit_code": exit_code,
            "data_root": str(self.root),
            "counts": dict(self.counts),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


def print_human(summary: dict[str, Any]) -> None:
    print(f"Comma Review Store Audit: {summary['status']}")
    print(f"data_root: {summary['data_root']}")
    for key in sorted(summary["counts"]):
        print(f"{key}: {summary['counts'][key]}")
    for severity in ("warnings", "errors"):
        rows = summary[severity]
        if not rows:
            continue
        print(f"{severity}: {len(rows)}")
        for item in rows:
            print(f"- {item['code']} {item['path']} ({item['detail']})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only audit for a Comma Review Studio data root.")
    parser.add_argument("--data-root", required=True, help="explicit Review Studio data root to scan")
    parser.add_argument("--json", action="store_true", help="print a structured summary")
    args = parser.parse_args(argv)
    summary = StoreAudit(args.data_root).run()
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print_human(summary)
    return int(summary["exit_code"])


if __name__ == "__main__":
    sys.exit(main())
