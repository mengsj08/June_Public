# Architecture

The reference implementation separates facts, policy, projection, and delivery so that an attractive page can never become the hidden source of truth.

```text
public API / feed ─┐
author watch ──────┤
email / Feishu ────┤
Stork ─────────────┼─> source adapter -> raw artifact + manifest
browser snapshot ──┤                         |
legacy export ─────┘                         v
                              normalize -> identity -> incremental event
                                         -> freshness -> dedup
                                         -> deterministic profile score
                                         -> optional LLM triage
                                                   |
                                                   v
                                          daily_items.jsonl
                                      ┌────────────┼─────────────┐
                                      v            v             v
                                  briefing      static site   content candidates
                                                                  |
                                                       human gate + explicit sink
```

## Ownership boundaries

- Source adapters own retrieval only. They do not decide importance.
- The core owns identity, event semantics, deduplication and deterministic tiers.
- LLM triage is a parallel annotation. It cannot replace `reading_tier` or source facts.
- `daily_items.jsonl` owns the assembled public item contract.
- Renderers are replaceable projections of the same fact pool.
- A delivery sink cannot authenticate itself from repository content; it reads an endpoint or credential reference from the environment.

Every source writes a local `manifest.json` and `items.raw.jsonl`. These outputs may contain private data during a real local run and therefore belong outside the public repository.

## Health semantics

| State | Meaning |
|---|---|
| `complete` | All active required sources succeeded or had no updates. |
| `complete_with_warning` | Required intake completed, but an optional stage reported a warning. |
| `degraded` | Some required intake failed while another required source succeeded. |
| `failed` | Every active required source failed. |

An inactive optional connector is not a failure. An enabled network source without `--live` is inactive and visible, not silently treated as loaded.
