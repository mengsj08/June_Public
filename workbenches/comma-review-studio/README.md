# Comma Review Studio

Comma Review Studio is a local-first browser workbench for Markdown and scientific
manuscripts. It combines the reusable Comma Editor Kit with a Python reference host for
document intake, structured AI review, anchored comments, version recovery and exports.

## Included surfaces

- `apps/review-studio/` — the complete local review workbench.
- `src/` — host-neutral editor core and `<comma-editor>` Web Component.
- `standalone/` — browser-local editor demo.
- `chrome-extension/` — user-initiated Chrome Side Panel wrapper.
- `tests/` — editor, browser and extension contracts.

For the editor component boundary, see [`EDITOR_KIT.md`](EDITOR_KIT.md) and
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Quick start

Requirements: Node.js 20+, npm and Python 3.10+.

```bash
npm ci
npm run check
./start-review-studio.sh
```

The launcher starts a loopback-only service and prints the local URL, normally
`http://127.0.0.1:8891/`.

The bundled `apps/review-studio/data/paper.md` is synthetic. To keep private documents in
an explicit local directory:

```bash
COMMA_REVIEW_DATA_ROOT=/absolute/private/directory ./start-review-studio.sh
```

Codex and Claude integrations use the user's existing local CLI installation and login
state. Editing, import, comments and version history remain available when neither CLI is
configured.

## Public snapshot boundary

This package was exported from `mengsj08/comma-editor-kit` commit
`73e39d7b7719578a384cb9346e07b440ad5b0a20`. Uncommitted development changes, private
manuscripts, comments, review ledgers, screenshots, logs, model traces, generated builds and
tool-state directories are not included.

See [`PROVENANCE.md`](PROVENANCE.md) for the exact source and verification record.

## License

The June-authored source is currently published for source review and evaluation without an
open-source reuse grant; see [`LICENSE`](LICENSE). Third-party dependencies and the bundled
MIT-licensed review rubric retain their own licenses; see
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
