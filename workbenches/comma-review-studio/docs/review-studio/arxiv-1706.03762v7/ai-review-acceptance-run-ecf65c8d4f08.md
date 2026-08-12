# arXiv 1706.03762v7 AI Review Acceptance - run-ecf65c8d4f08

This redacted summary intentionally excludes paper body text and finding quotes. Full private record: `apps/review-studio/data/arxiv-1706.03762v7/acceptance-record-run-ecf65c8d4f08.json`. Ground-truth table: `apps/review-studio/data/arxiv-1706.03762v7/ground-truth-run-ecf65c8d4f08.md`.

## Run

- Document: `arxiv-1706.03762v7/converted/attention-is-all-you-need-source.md`
- Source rev: `bc28cdaa78e60e3d`
- Source SHA-256: `bc28cdaa78e60e3dea30a09e876ec8f82321a14437dd9e2d771eb442067710e3`
- AI tool/model surface: Claude Code CLI `2.1.206`; server receipt `{"tool": "claude", "elapsed_ms": 369294, "returncode": 0}`
- Completed ReviewRun: `run-ecf65c8d4f08`; ReviewSession: `review-f3b482727c30`
- Note: an earlier Codex CLI attempt failed before producing a completed run; one failed Claude attempt is retained only in the ignored private data directory.

## Metrics

- Finding total: 8
- Evidence total: 19
- Evidence verification: verified 19/19, ambiguous-downgraded 0/19, missing 0/19
- Placement distribution: `{"document": 0, "evidence_unverified": 0, "no_quote_required": 0, "quote_context": 0, "quote_exact": 8, "quote_normalized_unique": 0, "section": 0}`
- Duplicate compression: 8 raw normalized model findings -> 8 user-visible main findings; compressed duplicates 0
- Active attention load after flow regression: pending 8, evidence_unverified 0, muted 0
- Downgrade reason distribution: `{"none": 8}`
- Ground-truth audit: 8/8 consistent; wrong-anchor 0; wrong-section 0

## Export/Reimport

- Package: `apps/review-studio/data/arxiv-1706.03762v7/ai-review-acceptance-package-run-ecf65c8d4f08.zip`
- Package SHA-256: `cf8ae007ac912ab164263292bb298a7c0bf5cb2f598cbe8739cc08a9af354f71`
- Manuscript exact source match: True
- Images: 8 Markdown refs, 8 packaged assets, missing assets 0
- Formula markers: package 20 vs source 20
- Table lines: package 57 vs source 57

## Flow Regression

- Save generated version: `version-a72efe1599be4998` rev `8c06962564ac3601`
- Refresh saw saved marker: True
- Restore generated version: `version-872c62edb5c3451b`; restored original body: True
- Temporary comment writeback/withdraw: `c-d72da53d8f` -> lifecycle `withdrawn`

## Resolver Fixes

- Fixed Review AI invocation timeout for long scientific manuscripts by adding `REVIEW_STUDIO_AI_TIMEOUT_SECONDS` with a default of 900 seconds.
- Fixed quote placement anchoring so primary `quote_text` controls the visible card anchor; supplemental `evidence_quotes` remain independently verified evidence occurrences.
