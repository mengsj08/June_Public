# June Public

Public workbench and skill collection, plus the AI4LifeScience site.

## Site

Published via GitHub Pages from [`docs/`](docs/): **https://mengsj08.github.io/June_Public/**

- **Source Atlas** ([`docs/index.html`](docs/index.html)) — curated, browsable map of
  AI4LifeScience information sources.
- **Author Literature Map** ([`docs/author-map.html`](docs/author-map.html)) — landing page
  for the evidence-gated per-author literature map toolkit.

## Workbenches

Workbenches are runnable local applications with their own browser interface. They live at
the repository root rather than under `skills/`, even when a package also contains a
`SKILL.md` launcher contract.

- [`workbenches/comma-review-studio/`](workbenches/comma-review-studio/)
  Local-first Markdown and scientific-manuscript review workspace: Word/Markdown intake,
  structured Codex/Claude review, anchored comments, version recovery and portable exports.

- [`workbenches/scientific-pdf-bilingual-reader/`](workbenches/scientific-pdf-bilingual-reader/)
  Scientific long-PDF translation workspace for macOS: native text extraction, optional
  PaddleOCR for scanned pages, Chinese PDF output, side-by-side bilingual reading, Comment /
  Agent review and human-gated batch repair.

See [`workbenches/README.md`](workbenches/README.md) for the classification rule and
snapshot boundaries.

## Skills

- `skills/research-tools/author-literature-map/`
  Per-author literature maps with evidence-gated identity resolution and traceable claims.

- `skills/ip-operations/xiaohongshu-skills/`
  Xiaohongshu authentication, search, publishing, interaction and Feishu Base collection.

- `skills/ip-operations/article-visualization/`
  Article and paper visualization for long images, social cards and public explainers.

## Safety

This repository contains only public code, instructions, tests, synthetic fixtures and
selected public evidence. It does not contain local account state, cookies, tokens, private
documents, customer PDFs, model traces or runtime workspaces.

Each workbench keeps user data outside the published source boundary. Read the workbench's
own README before importing private material or enabling a local AI provider.
