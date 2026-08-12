# Architecture

## Boundary

```text
Host application / Chrome Side Panel / future desktop shell
                         |
                  <comma-editor>
                         |
      capability-declared DocumentAdapter + host events
                         |
       file / HTTP / localStorage / chrome.storage
```

The component consumes a document contract. It does not know where a document lives and it does not invoke an AI provider directly.

`apps/review-studio/` is a composed reference host above this boundary. It may invoke a guarded local provider and persist files because those capabilities remain outside `src/core/` and `src/element/`.

## Core invariants

1. Markdown is the canonical body. Rendered HTML is disposable.
2. An edit replaces a known source range; unedited source remains byte-identical.
3. Saves carry `baseRev`. A stale revision is rejected, never overwritten.
4. Comments store a quote snapshot and a source locator. Ambiguity is reported instead of guessed.
5. AI-proposed comments are previewed against a fixed revision and confirmed as one atomic batch.
6. Mutations append an actor-labelled event through the adapter.
7. Rendered HTML is sanitized before entering the shadow DOM.
8. Chrome permissions stay in the Chrome wrapper.
9. The default save policy is explicit; immediate persistence requires an
   adapter or host to opt in.
10. Capability discovery is truthful. A document-only host does not gain fake
    comments or event history merely because the UI supports them elsewhere.
11. A stale host save may preserve the attempted body as a recoverable draft,
    but recovery still carries the current `baseRev` and creates a new history
    entry. Conflict preservation never weakens the adapter revision boundary.

## Extension points

- `DocumentAdapter`: persistence and revision boundary.
- `capabilities`: host-declared load/save/comment/event surface plus
  `explicit | immediate` save policy.
- `comma-ai-request`: host decides whether Codex, Claude, another model, or no AI handles a request.
- `selectionActions` + `comma-selection-action`: the component renders a
  host-declared selection command and emits a revision-scoped quote snapshot;
  provider execution and conversation state stay outside editor-core.
- `toolbarActions` / `commentActions` + composed action events: hosts declare
  labels and ordered commands while the component enforces adapter capability
  boundaries. A document-only host receives no comment count or comment menu.
- Reading-mode pointer gestures never imply mutation. Block editing starts only
  from the editor-owned explicit affordance, so native text selection remains
  available to comments and host-declared quote actions.
- Native selections inside the component's Shadow DOM are recovered through
  composed ranges. Chromium can expose selected text while reporting the outer
  document range as collapsed, so ordinary `getRangeAt(0)` is not an adequate
  acceptance test for real pointer selections.
- `previewCommentBatch`: validates a structured response and opens a human confirmation queue; it never writes by itself.
- CSS custom properties: host-level visual tuning without DOM coupling.
- `resolveAsset`: optional adapter capability for turning document-relative
  image references into host-authorized URLs; editor-core never reads files.
- Future MCP: maps semantic document tools to an adapter/service, not to UI clicks.

## Promotion gate

Before `1.0`:

- the standalone, Review Studio, and ResearchLab hosts consume the package rather than copied files;
- the kanban document-only adapter graduates from a controlled contract test to a bounded detail-page pilot;
- schemas receive explicit migration rules;
- browser and long-document tests run in CI;
- a private/public distribution and licensing decision is made.

## Validated host profiles (v0.3)

| Host | Save policy | Comments | Host-owned behavior |
|---|---|---|---|
| Comma Review Studio | immediate | full + atomic batch | provider execution, review sessions, finding decisions, multi-turn writeback, version/draft service, exports |
| ResearchLab Markdown Studio | explicit | full + atomic batch | RLP directory confinement, SHA-256 guard, 2 MB limit, project-local state |
| kanban-personal controlled Adapter | immediate | deliberately disabled | frontmatter, acceptance criteria, AI thread/queue, handoff, task state and three-way merge |

## Conversation boundary

Review findings and quote-scoped conversations are separate native objects:

```text
selected Markdown quote
        -> host ConversationSession
              -> linear turns + branch lineage + reply notes
                    -> explicit writeback receipt
                          -> anchored Comment
```

`ConversationSession` records a quote snapshot, source locator, document
revision, provider, parent-linked messages, branch identity, reply notes, and
writeback receipts. It never duplicates the whole Markdown document. A branch
is dialogue lineage, not a fork of the Markdown source. A host may implement the
same contract with Codex, Claude, or no provider at all.
