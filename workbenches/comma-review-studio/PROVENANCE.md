# Provenance

- Public package: `workbenches/comma-review-studio`
- Canonical repository: `https://github.com/mengsj08/comma-editor-kit`
- Exported commit: `73e39d7b7719578a384cb9346e07b440ad5b0a20`
- Export date: 2026-08-12
- Package version: `0.3.0`

The public package was produced from the committed Git tree, not from the canonical working
directory. Development changes that had not reached a source commit were intentionally not
published.

Publication-only edits are limited to the new public README, provenance/license notices,
removal of private migration documents, replacement of June-local absolute paths in public
instructions, public-safe wording in the synthetic sample, minor whitespace cleanup, and the
corresponding bundled-rubric checksum update. Product implementation otherwise follows the
exported commit.

Excluded from the public package:

- repository-specific agent instructions and private migration notes;
- real manuscripts, comments, evidence files and review/session ledgers;
- screenshots, raw AI traces, logs, caches, generated builds and `node_modules`;
- local tool-state directories and credentials.

Verification of the exported commit:

- editor-core Node tests: 25 passed;
- Review Studio unit/API suite: 109 tests run (108 passed, 1 optional-provider check skipped);
- Chrome extension build and manifest validation: passed;
- standalone browser smoke: passed;
- Chrome Side Panel smoke: passed.

These checks establish software runnability for the exported snapshot. They do not claim
that every scientific review is correct or that every private document format is lossless.
