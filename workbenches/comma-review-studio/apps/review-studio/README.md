# Comma Review Studio

Comma Review Studio is the complete local reference host for Comma Editor Kit. It owns the capabilities that intentionally stay outside editor-core: filesystem persistence, local Codex or Claude execution, review-session ledgers, multi-turn finding updates, revision-locked comment writeback, conflict recovery, document history, and portable exports.

It also owns quote-scoped conversations. Selecting source text exposes `添加批注 / 快速解释 / 深入讨论`: quick explanations are transient; deep discussions are persisted as parent-linked message trees with comments, explicit forks, and message-level comment writeback.

## Run

```bash
COMMA_REVIEW_PORT=8891 python3 server.py
```

Open `http://127.0.0.1:8891/?doc=paper.md`.

For a private document directory, set an explicit data root:

```bash
COMMA_REVIEW_DATA_ROOT=/absolute/private/directory COMMA_REVIEW_PORT=8891 python3 server.py
```

The server binds only to `127.0.0.1`. It accepts Markdown files only and confines document access to the selected data root. Private documents, comment sidecars, review sessions, quote conversation ledgers, event ledgers, logs, screenshots, and raw model traces must not be committed.

`--host` is intentionally restricted before bind to `127.0.0.1` or
`localhost`. v0 does not support `::1`, wildcard binds, LAN addresses, or a
remote Review Studio mode.

## Version and export center

Every successful immediate save records a content-addressed snapshot under
`<data-root>/.comma-review/versions/`. A named checkpoint points at the same
immutable blob. Restoring a checkpoint writes a new timeline entry instead of
deleting later history. If a save loses its optimistic-revision race, the
attempted body is retained under `.comma-review/drafts/`; the page reloads the
newest disk revision and offers diff, revision-checked recovery, or dismissal.

The export center provides exact Markdown, Markdown with appended review
comments, and a Review Package ZIP containing the selected manuscript,
document-relative image assets, native comments, matching review/conversation
ledgers, the per-document hash-only `CommentEvent` ledger, and version
snapshots. The global event ledger and raw AI traces are
excluded. DOCX and PDF use a detected local LibreOffice executable; set
`COMMA_REVIEW_SOFFICE_BIN=/absolute/path/to/soffice` when auto-detection is not
appropriate.

## Local CLI capability

`GET /api/runtime/capabilities` reports Codex and Claude installation, version,
and login readiness. The header badge uses the same resolver as quick explain,
quote-scoped discussions, and structured review, so a missing provider is
disabled before invocation instead of returning a successful stub.

The resolver augments a minimal launchd `PATH` with conventional macOS CLI
locations and passes that path to child processes (important for the Node-based
Codex launcher). Explicit installations can be pinned without changing global
shell state:

```bash
COMMA_REVIEW_CODEX_BIN=/absolute/path/to/codex \
COMMA_REVIEW_CLAUDE_BIN=/absolute/path/to/claude \
python3 server.py
```

Capability detection runs only `--version` and read-only login-status commands;
their authentication output is discarded and page load never starts a model
task.

Structured review runs use the local asynchronous executor. Run state includes
`queued`, `running`, `cancelling`, `cancelled`, `completed`, and `failed`.
Cancelling a controlled provider run terminates its process tree and records a
receipt. The queue and active thread registry are in memory: host restart does
not resume a model call. On startup, persisted active runs are marked failed
with a host-restart recovery reason.

## Comment lifecycle migration

Legacy comment sidecars remain readable without a write. Inspect a copied data
root with the Slice A migration in dry-run mode:

```bash
python3 migrate_slice_a.py --data-root /absolute/path/to/copied-data
```

`--apply` is reserved for an explicitly authorized migration. It verifies all
records first and creates byte-identical sidecar/session backups under
`.comma-review/migration-backups/` before the first normalized write. The
command reports counts and field names only; it does not print comment or
manuscript content.

## Store audit

Inspect a data root without writing, reconciling, migrating, or printing private
body/comment/evidence/trace text:

```bash
python3 review_store_audit.py --data-root /absolute/path/to/data
python3 review_store_audit.py --data-root /absolute/path/to/data --json
```

Exit codes are stable: `0` clean, `1` warnings such as old schemas, orphaned
sidecars, missing documents, missing version/evidence pairings, or unfinished
operation journal entries, and `2` errors for data that cannot be safely read
or parsed. The JSON output carries the same counts, redacted paths, warning
codes, and error codes as the human output.

## Verify

From the repository root:

```bash
npm run test:review
CI=true python3 -m pytest apps/review-studio/ -q
```

Use any Python 3.10+ interpreter with the test dependencies installed.

`pytest apps/review-studio/` collects the API, orchestrator, and Slice A
contract tests. It does not run `test_headless.py`: that file is an
executable Playwright acceptance script with a `main()` entrypoint, not a pytest
test function.

The Review Studio browser regressions require a running server and the kanban
Playwright environment. Start the server from the repository root in one
terminal:

```bash
COMMA_REVIEW_PORT=8891 python3 apps/review-studio/server.py
```

The service remains restricted to the loopback interface.

Then run both executable browser acceptance scripts from a second terminal:

```bash
CI=true COMMA_REVIEW_PORT=8891 python3 apps/review-studio/test_headless.py
CI=true COMMA_REVIEW_PORT=8891 python3 apps/review-studio/test_blocks.py
```

These browser checks require Playwright and a compatible Chromium installation.

See `REVIEW_WORKFLOW.md` for the API and writeback contract. `SPIKE_REPORT.md` is retained only as migration provenance.
