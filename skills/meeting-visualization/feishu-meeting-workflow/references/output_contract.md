# Meeting Workflow Output Contract

This is the source of truth for what the meeting workflow may create. Other docs should link here instead of restating route and artifact rules.

## Default Rule

One meeting source, minutes source, transcript, or meeting-note link produces one formal Feishu archive document by default.

- Formal Feishu document body: `analysis/feishu_meeting_document.md`
- Formal Feishu parent: the configured 智回 `【内部】脑回路实验室 / 6.AI自动化流水线 / 01_会议分析流水线`
- Local working files may be many. They are traceability, review, or rendering artifacts, not separate Feishu archive documents.
- Do not create separate Feishu documents such as `客户档案`, `纪要`, `作战手册`, `成果诊断`, or `展示页` unless the user explicitly confirms legacy multi-artifact upload or a one-off split-document delivery.
- The legacy fanout buckets `01_会议成果索引`, `02_内部会议分析`, `03_合作方会议分析`, `04_客户会议分析`, `05_客户展示页`, `06_补资料与背景包`, `90_运行记录`, and `99_附件库` are diagnostic/recovery targets only. Use `--allow-multi-artifact-upload` only after explicit confirmation.

## Responsibility Split

| Layer | Owner | What it may do | What it must not do |
| --- | --- | --- | --- |
| Program | resolver, pipeline, route helper, finalizer, return scripts | Fetch readable sources, scaffold case files, record route state, copy declared outputs, build manifests, run dry-runs, create/update the single Feishu archive document after approval | Invent analysis, decide customer-facing wording, silently split one meeting into multiple Feishu documents |
| AI / Agent | current Agent or selected Skill | Read transcript/notes, judge ambiguous route intent, write analysis, collect context, design customer copy, prepare visual Prompt, classify audience when evidence is clear | Skip the route gate, treat local artifacts as Feishu archive nodes, send customer-facing material without review |
| Human | June or requesting user | Choose route when absent, confirm output contract exceptions, approve CRM/customer-facing HTML, approve real Feishu send, approve deletion/cleanup of existing online docs | Be bypassed for customer-visible or split-document delivery |

## Archive Audience Contract

Audience is separate from route. A default Agent route can still produce an internal, partner, or customer archive depending on the meeting.

| Audience | Meeting type values | Meaning | Legacy diagnostic bucket |
| --- | --- | --- | --- |
| `internal` | `internal`, `team`, `ops` | Internal team work, planning, review, research, or operations | `02_内部会议分析` |
| `partner` | `partner` | External cooperation with a strategic, ecosystem, school, channel, or technical partner. This is not a sales/customer case by default. | `03_合作方会议分析` |
| `customer` | `presales`, `customer_collaboration`, `customer`, `client` | Customer, sales, presales, delivery, or customer-facing analysis | `04_客户会议分析`; customer HTML diagnostic bucket is `05_客户展示页` |

Set `meeting_type: "partner"` or `archive_audience: "partner"` in case metadata when a cooperation meeting should not be treated as customer analysis.

## Route Contract

| Route | Route id | Final route? | AI work | Required local outputs | Feishu output | Required pause |
| --- | --- | --- | --- | --- | --- | --- |
| `1` / `默认` / `内部分析` | `agent_default` | Yes | Current Agent reads transcript and writes internal or customer analysis based on the case | `analysis/meeting_analysis.md`; optional reviewed HTML under `html/` | One archive document from `analysis/feishu_meeting_document.md` | Pause only when audience or target is ambiguous |
| `2` / `补资料` | `supplement` | No, unless user explicitly stops there | Agent gathers named local/team/customer/web context and cites sources | `analysis/context_materials.md`; optional snippets under `source/context_materials/` | No formal Feishu archive until a final route is chosen | Ask what to search if unclear; then ask which final route to enter |
| `3` / `客户展示HTML` | `customer_html_prompt` | Yes after Prompt approval | Use `meeting-visual-report`: produce structured Prompt first, then final HTML after confirmation | Confirmed HTML under `html/`; related Markdown if any | One archive document that references reviewed HTML path/status | Always pause for Prompt confirmation and final send approval |
| `4` / `WOW-Claude` | `wow_claude` | Yes after remote result returns | Prepare handoff; user works interactively on WOW; Agent copies returned outputs into case | Markdown under `analysis/remote_outputs/`; HTML under `html/` if produced | One archive document from reviewed returned outputs | Pause for interactive WOW work and final send approval |
| `5` / `WOW-Codex` | `wow_codex` | Yes after remote result returns | Same as WOW-Claude, but with Codex on WOW | Markdown under `analysis/remote_outputs/`; HTML under `html/` if produced | One archive document from reviewed returned outputs | Pause for interactive WOW work and final send approval |
| `6` / `客户洽谈Skill` / `crm` | `crm_skill` | Yes after CRM outputs are reviewed | Use `crm` / `skill_客户洽谈` only when explicitly selected; copy generated files back into this case | CRM Markdown under `analysis/crm/`; customer HTML under `html/`; optional source copy from `agent_output/` | One archive document bundling/referencing reviewed CRM outputs | Always pause for review and send approval |

## Canonical Case Files

These files are expected inside the local case package. They do not imply separate Feishu documents.

- `source/meeting_transcript.md`
- `source/ai_notes.md`, when available
- `source/source_resolution.json`
- `analysis/route_decision.json`
- `analysis/agent_handoff.md`
- `analysis/meeting_analysis.md`
- `analysis/context_materials.md`
- `analysis/remote_outputs/`
- `analysis/crm/`
- `html/`
- `analysis/route_done.json`
- `analysis/feishu_meeting_document.md`
- `analysis/feishu_index_entry.md`
- `analysis/source_paths_for_feishu.md`
- `analysis/feishu_return_message.md`
- `analysis/feishu_return_manifest.json`
- `case.json` / `case.yaml`

## Feishu Return Checklist

Before a real Feishu write:

1. Confirm `source/meeting_transcript.md` is present and non-empty. A negative `source_resolution.json` is a stop record, not permission to approve or return.
2. Confirm the selected route has reached a final route, not only `补资料`.
3. Confirm CRM and customer-facing HTML outputs were reviewed by the user.
4. Confirm no split-document delivery is requested unless explicitly stated.
5. Run `finalize_route.py` to normalize outputs and build the return package.
6. Use `--send --dry-run` when enabling or changing a Wiki/Drive target.
7. If writing to an existing Feishu document or index page, read the current document first and preserve existing reviewed entries.
8. Send or create only the single archive document unless the user approved legacy multi-artifact upload.

## Index Policy

`analysis/feishu_index_entry.md` is a local draft for maintaining `01_会议成果索引`; it is not a separate archive document. When an index entry is maintained, it should point to the single formal archive document for the meeting. It must not point to a local-only artifact or to a duplicated `客户档案` / `作战手册` document unless the user approved split-document delivery.
