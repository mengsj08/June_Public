"""Deterministic Markdown and self-contained HTML projections."""

from __future__ import annotations

import html
import json
from typing import Any, Mapping, Sequence

from .core import text


TIER_LABELS = {
    "must_read": "Priority",
    "skim": "Scan",
    "collapsed": "Hold",
    "archive": "Archive",
}


def render_markdown(
    items: Sequence[Mapping[str, Any]],
    health: Mapping[str, Any],
    *,
    as_of: str,
) -> str:
    """Render a source-faithful daily briefing."""
    lines = [
        f"# Scientific Information Brief · {as_of}",
        "",
        f"> Daily status: **{health.get('daily_status', 'unknown')}** · "
        f"sources {health.get('loaded_source_count', 0)}/{health.get('source_count', 0)} · "
        f"items {len(items)}",
        "",
        "Reading tiers are configurable attention hints, not scientific-quality grades.",
        "",
    ]
    for tier in ("must_read", "skim", "collapsed", "archive"):
        tier_items = [item for item in items if item.get("reading_tier") == tier]
        lines.extend([f"## {TIER_LABELS[tier]} · {len(tier_items)}", ""])
        if not tier_items:
            lines.extend(["No items.", ""])
            continue
        for item in tier_items:
            title = text(item.get("title"))
            url = text(item.get("url"))
            heading = f"[{title}]({url})" if url else title
            source = text(item.get("source_id"))
            published = text(item.get("published_at")) or "undated"
            summary = text(item.get("summary")) or "No summary supplied by the source."
            lines.extend(
                [
                    f"### {heading}",
                    "",
                    f"- Source: `{source}` · published `{published}` · freshness `{item.get('freshness_gate')}`",
                    f"- Topic relevance: `{item.get('topic_relevance')}` · novelty hint: `{item.get('method_novelty_hint')}`",
                    f"- Event: `{item.get('event_type')}` · identity: `{item.get('item_id')}`",
                    "",
                    summary,
                    "",
                ]
            )
            if item.get("llm_triage"):
                triage = item["llm_triage"]
                lines.extend(
                    [
                        f"LLM triage: `{triage.get('decision')}` ({triage.get('confidence')}) — {text(triage.get('reason'))}",
                        "",
                    ]
                )
    lines.extend(["---", "", "Generated from `daily_items.jsonl`; verify consequential claims against the original source.", ""])
    return "\n".join(lines)


def _safe_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def render_site(
    items: Sequence[Mapping[str, Any]],
    health: Mapping[str, Any],
    *,
    as_of: str,
    synthetic_demo: bool,
) -> str:
    """Render an industrial field-notebook interface with no external assets."""
    payload = {"items": list(items), "health": health, "as_of": as_of, "synthetic_demo": synthetic_demo}
    demo_label = "SYNTHETIC DEMO · NO PERSONAL DATA" if synthetic_demo else "LOCAL PRIVATE OUTPUT"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <title>Scientific Information Hub · {html.escape(as_of)}</title>
  <style>
    :root {{
      --paper: #eee9dc; --paper-raised: #f7f3e8; --ink: #18201c; --muted: #687069;
      --moss: #425d4a; --moss-deep: #263a2d; --signal: #d55a2a; --gold: #b48a3c;
      --line: rgba(24,32,28,.18); --shadow: 0 20px 55px rgba(34,43,37,.13);
      --serif: "Iowan Old Style", "Baskerville", "Palatino Linotype", serif;
      --sans: "Avenir Next", "Gill Sans", "Trebuchet MS", sans-serif;
      --mono: "SFMono-Regular", "IBM Plex Mono", Menlo, monospace;
    }}
    * {{ box-sizing: border-box; }}
    html {{ scroll-behavior: smooth; }}
    body {{ margin: 0; color: var(--ink); background: var(--paper); font-family: var(--sans); }}
    body::before {{ content:""; position: fixed; inset: 0; pointer-events:none; opacity:.34; background-image: radial-gradient(rgba(24,32,28,.16) .55px, transparent .55px); background-size: 5px 5px; mix-blend-mode:multiply; }}
    button,input {{ font: inherit; }}
    .shell {{ min-height:100vh; display:grid; grid-template-columns: 310px minmax(0,1fr); }}
    .rail {{ position:sticky; top:0; height:100vh; padding:32px 28px; background:var(--moss-deep); color:#f3eddf; overflow:auto; }}
    .rail::after {{ content:""; position:absolute; right:-26px; top:88px; width:52px; height:140px; background:var(--signal); clip-path:polygon(0 0,100% 12%,100% 88%,0 100%); }}
    .stamp {{ display:inline-block; padding:6px 9px; border:1px solid rgba(255,255,255,.32); color:#e1c995; font:700 .62rem/1 var(--mono); letter-spacing:.14em; transform:rotate(-1.5deg); }}
    .brand {{ margin:32px 0 4px; font:600 2.4rem/.92 var(--serif); letter-spacing:-.04em; }}
    .brand span {{ display:block; color:#e99a72; font-style:italic; }}
    .rail-copy {{ color:#b9c5bb; font-size:.82rem; line-height:1.65; max-width:220px; }}
    .health-block {{ margin-top:30px; padding-top:22px; border-top:1px solid rgba(255,255,255,.16); }}
    .health-label {{ color:#8fa796; font:700 .61rem/1 var(--mono); letter-spacing:.15em; text-transform:uppercase; }}
    .health-value {{ margin:7px 0 0; font:600 1.22rem/1.2 var(--serif); }}
    .health-meta {{ margin:7px 0 0; color:#a8b5aa; font-size:.72rem; line-height:1.6; }}
    .filters {{ display:grid; gap:7px; margin-top:28px; }}
    .filter {{ border:0; border-left:2px solid transparent; background:transparent; color:#bdc8bf; text-align:left; padding:8px 10px; cursor:pointer; font-weight:650; }}
    .filter:hover,.filter.active {{ color:white; border-left-color:#e7885f; background:rgba(255,255,255,.06); }}
    .main {{ min-width:0; padding:0 clamp(24px,5vw,78px) 90px; }}
    .mast {{ position:sticky; top:0; z-index:3; padding:34px 0 22px; background:linear-gradient(var(--paper) 76%,rgba(238,233,220,0)); backdrop-filter:blur(10px); }}
    .kicker {{ color:var(--signal); font:800 .66rem/1 var(--mono); letter-spacing:.17em; text-transform:uppercase; }}
    h1 {{ margin:9px 0 0; font:600 clamp(2.5rem,6vw,5.7rem)/.86 var(--serif); letter-spacing:-.055em; }}
    .mast-row {{ margin-top:18px; display:grid; grid-template-columns:minmax(0,1fr) minmax(240px,420px); align-items:end; gap:26px; }}
    .date-note {{ color:var(--muted); font-size:.82rem; line-height:1.55; }}
    .search {{ width:100%; border:0; border-bottom:1px solid var(--ink); background:transparent; color:var(--ink); padding:11px 2px; outline:none; }}
    .search:focus {{ border-bottom-color:var(--signal); }}
    .ledger {{ margin-top:8px; border-top:1px solid var(--line); }}
    .ledger-head {{ display:grid; grid-template-columns:70px minmax(0,1fr) 130px; gap:18px; padding:13px 0; color:var(--muted); font:700 .62rem/1 var(--mono); letter-spacing:.12em; text-transform:uppercase; }}
    .card {{ position:relative; display:grid; grid-template-columns:70px minmax(0,1fr) 130px; gap:18px; padding:25px 0 28px; border-top:1px solid var(--line); animation:reveal .55s both; }}
    @keyframes reveal {{ from {{opacity:0; transform:translateY(10px)}} to {{opacity:1; transform:none}} }}
    .card:hover .title a {{ color:var(--signal); }}
    .index {{ font:600 1.5rem/1 var(--serif); color:var(--gold); }}
    .meta {{ display:flex; flex-wrap:wrap; gap:6px 12px; color:var(--muted); font:.69rem/1.35 var(--mono); }}
    .tier {{ padding:3px 7px; border:1px solid currentColor; color:var(--moss); font-weight:800; text-transform:uppercase; }}
    .tier.must_read {{ color:var(--signal); }}
    .title {{ margin:11px 0 0; font:600 clamp(1.2rem,2.3vw,1.82rem)/1.13 var(--serif); letter-spacing:-.02em; }}
    .title a {{ color:var(--ink); text-decoration:none; transition:color .15s ease; }}
    .summary {{ max-width:830px; margin:10px 0 0; color:#4e5851; font-size:.84rem; line-height:1.72; }}
    .llm {{ margin-top:11px; padding-left:11px; border-left:2px solid var(--gold); color:#5d604e; font-size:.74rem; line-height:1.55; }}
    .score {{ text-align:right; }}
    .score strong {{ display:block; font:600 2rem/1 var(--serif); }}
    .score span {{ color:var(--muted); font:.6rem/1.3 var(--mono); text-transform:uppercase; }}
    .empty {{ padding:60px 0; color:var(--muted); font:italic 1.4rem/1.4 var(--serif); }}
    .footer {{ margin-top:48px; padding-top:18px; border-top:1px solid var(--line); color:var(--muted); font-size:.72rem; line-height:1.6; }}
    @media (max-width:860px) {{
      .shell {{ grid-template-columns:1fr; }} .rail {{ position:relative; height:auto; padding:24px; }} .rail::after {{ display:none; }}
      .brand {{ font-size:2rem; }} .health-block {{ display:none; }} .filters {{ grid-template-columns:repeat(4,1fr); }}
      .main {{ padding:0 20px 60px; }} .mast-row {{ grid-template-columns:1fr; gap:10px; }}
      .ledger-head {{ display:none; }} .card {{ grid-template-columns:42px minmax(0,1fr); }} .score {{ grid-column:2; text-align:left; display:flex; gap:8px; align-items:baseline; }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    <aside class="rail">
      <span class="stamp">{html.escape(demo_label)}</span>
      <h2 class="brand">Scientific<span>Information Hub</span></h2>
      <p class="rail-copy">A field ledger for traceable source intake, explainable triage, and controlled delivery.</p>
      <div class="health-block">
        <div class="health-label">Daily condition</div>
        <p class="health-value" id="health-value"></p>
        <p class="health-meta" id="health-meta"></p>
      </div>
      <div class="filters" aria-label="Reading tier filters">
        <button class="filter active" data-tier="all">All signals</button>
        <button class="filter" data-tier="must_read">Priority</button>
        <button class="filter" data-tier="skim">Scan</button>
        <button class="filter" data-tier="collapsed">Hold</button>
        <button class="filter" data-tier="archive">Archive</button>
      </div>
    </aside>
    <main class="main">
      <header class="mast">
        <div class="kicker">Evidence before interface · {html.escape(as_of)}</div>
        <h1>Signal ledger.</h1>
        <div class="mast-row">
          <div class="date-note">One fact pool. Multiple sources. Every priority remains traceable to its origin and policy.</div>
          <input class="search" id="search" type="search" aria-label="Search records" placeholder="Search title, summary, source, tag…" autocomplete="off">
        </div>
      </header>
      <section class="ledger">
        <div class="ledger-head"><span>No.</span><span>Source record</span><span>Profile match</span></div>
        <div id="records"></div>
        <div class="empty" id="empty" hidden>No records match this view.</div>
      </section>
      <footer class="footer">Reading tiers are attention hints, not scientific-quality grades. Verify consequential claims against the original source.</footer>
    </main>
  </div>
  <script id="payload" type="application/json">{_safe_json(payload)}</script>
  <script>
    const DATA = JSON.parse(document.getElementById('payload').textContent);
    const state = {{ tier: 'all', query: '' }};
    const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
    const tierLabel = {{must_read:'Priority',skim:'Scan',collapsed:'Hold',archive:'Archive'}};
    const records = document.getElementById('records');
    const health = DATA.health || {{}};
    document.getElementById('health-value').textContent = String(health.daily_status || 'unknown').replaceAll('_',' ');
    document.getElementById('health-meta').textContent = `${{health.loaded_source_count || 0}}/${{health.source_count || 0}} sources loaded · ${{DATA.items.length}} assembled records`;
    function matches(item) {{
      if (state.tier !== 'all' && item.reading_tier !== state.tier) return false;
      const haystack = [item.title,item.summary,item.source_id,...(item.tags||[])].join(' ').toLowerCase();
      return !state.query || haystack.includes(state.query);
    }}
    function card(item, index) {{
      const triage = item.llm_triage ? `<div class="llm"><strong>LLM ${{esc(item.llm_triage.decision)}}:</strong> ${{esc(item.llm_triage.reason)}}</div>` : '';
      const linkedTitle = item.url ? `<a href="${{esc(item.url)}}" target="_blank" rel="noreferrer">${{esc(item.title)}}</a>` : `<span>${{esc(item.title)}}</span>`;
      return `<article class="card" style="animation-delay:${{Math.min(index,12)*35}}ms">
        <div class="index">${{String(index+1).padStart(2,'0')}}</div>
        <div><div class="meta"><span class="tier ${{esc(item.reading_tier)}}">${{esc(tierLabel[item.reading_tier]||item.reading_tier)}}</span><span>${{esc(item.source_id)}}</span><span>${{esc(item.published_at||'undated')}}</span><span>${{esc(item.freshness_gate)}}</span></div>
        <h2 class="title">${{linkedTitle}}</h2><p class="summary">${{esc(item.summary||'No source summary supplied.')}}</p>${{triage}}</div>
        <div class="score"><strong>${{Math.round((item.topic_relevance||0)*100)}}</strong><span>topic match</span></div></article>`;
    }}
    function render() {{
      const visible = DATA.items.filter(matches);
      records.innerHTML = visible.map(card).join('');
      document.getElementById('empty').hidden = visible.length > 0;
    }}
    document.querySelectorAll('[data-tier]').forEach(button => button.addEventListener('click', () => {{
      state.tier = button.dataset.tier; document.querySelectorAll('[data-tier]').forEach(b => b.classList.toggle('active', b === button)); render();
    }}));
    document.getElementById('search').addEventListener('input', event => {{ state.query = event.target.value.trim().toLowerCase(); render(); }});
    render();
  </script>
</body>
</html>"""
