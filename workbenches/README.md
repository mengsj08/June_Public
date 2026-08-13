# Workbenches

This directory contains runnable local applications with a real browser workspace.

The classification rule is product shape, not implementation language:

- a **workbench** owns an interactive UI, local service or launcher, and durable user task
  state;
- a **skill** primarily teaches an AI tool when and how to execute a workflow;
- a workbench may still carry `SKILL.md` as one launch surface, but its public home remains
  under `workbenches/`.

| Workbench | Primary interface | Public snapshot |
| --- | --- | --- |
| [Comma Review Studio](comma-review-studio/) | Markdown/manuscript review workspace | `comma-editor-kit` commit `73e39d7` |
| [Scientific PDF Bilingual Reader](scientific-pdf-bilingual-reader/) | Long-PDF translation, bilingual reading and human-gated repair | main · 2026-08-13 Stage 0–3 |

Runtime documents, comments, PDFs, task state, credentials, logs, caches and generated
outputs must remain outside this public repository.
