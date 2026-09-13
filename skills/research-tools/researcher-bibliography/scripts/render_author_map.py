#!/usr/bin/env python3
"""Render a single-author literature map to one static HTML file.

The map is drawn ENTIRELY from AUTHOR_MAP.json (see build_author_map_verdict.py),
which is the single source of every count. The renderer never recomputes counts
itself, so the metric cards, the year bars, and the table can never disagree.

If AUTHOR_MAP.json is missing, it is built here first (via the same builder), so
there is exactly one computation path. Before rendering, the recorded input
hashes are re-checked; if the underlying evidence CSVs changed, the page carries
a visible STALE banner telling the user to regenerate the verdict.

Read-only over inputs; writes one HTML file (and, if absent, AUTHOR_MAP.json).

Display rules (see references/method.md):
- Every rendered work carries a visible source label (already guaranteed by the
  builder, which drops source-less rows into an audit count).
- Mainline only; review / excluded / unlabelled are surfaced as audit pointers.
- No internal routing terms; provenance stays in the CSV/JSON audit files.
"""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

import build_author_map_verdict as bv


def esc(value) -> str:
    return html.escape(str(value) if value is not None else "")


def build_html(verdict: dict, stale: list[str]) -> str:
    author = verdict.get("author", "")
    counts = verdict.get("counts", {})
    main_n = counts.get("main", 0)
    review_n = counts.get("review", 0)
    excluded_n = counts.get("excluded", 0)
    supplement_n = counts.get("supplement", 0)
    unlabeled_n = counts.get("unlabeled_dropped", 0)
    works = verdict.get("works", [])
    run_dir = Path(verdict.get("run_dir", "."))
    researcher_profile = run_dir / "researcher_profile.md"
    profile_link = ""
    if researcher_profile.exists():
        profile_link = (
            '<div class="profilelink">'
            '<a href="researcher_profile.md">研究者画像模块</a>'
            '</div>'
        )

    ymin, ymax = (verdict.get("year_range") or [None, None])[:2]
    yr_range = f"{ymin}–{ymax}" if ymin and ymax else "—"

    year_counts = verdict.get("year_histogram") or []
    max_yc = max((c for _, c in year_counts), default=1) or 1
    year_bars = "".join(
        f'<div class="ybar"><span class="yl">{esc(y)}</span>'
        f'<span class="yt" style="width:{max(2, int(100 * c / max_yc))}%"></span>'
        f'<span class="yn">{c}</span></div>'
        for y, c in year_counts
    )
    theme_rows = "".join(
        f"<tr><td>{esc(t)}</td><td class='num'>{c}</td></tr>"
        for t, c in (verdict.get("theme_histogram") or [])
    )

    def work_row(w: dict) -> str:
        title = esc(w.get("title"))
        url = w.get("url") or ""
        title_html = f'<a href="{esc(url)}" target="_blank">{title}</a>' if url else title
        sup = " <span class='tag'>PubMed 补充</span>" if w.get("supplement") else ""
        return (
            f"<tr><td class='yc'>{esc(w.get('year') or '')}</td>"
            f"<td>{title_html}{sup}"
            f"<div class='src'>来源：{esc(w.get('source_label'))}</div></td>"
            f"<td class='th'>{esc(w.get('theme'))}</td></tr>"
        )

    works_sorted = sorted(works, key=lambda w: (w.get("year") or 0), reverse=True)
    work_rows = "".join(work_row(w) for w in works_sorted)

    stale_banner = ""
    if stale:
        stale_banner = (
            f'<div class="stale">⚠ 证据已变更（{esc("、".join(stale))}），'
            f'此图可能过期——请重新生成 AUTHOR_MAP.json 后再渲染。</div>'
        )

    sub_bits = [f"主线文献 {main_n} 条", f"年份 {yr_range}"]
    if supplement_n:
        sub_bits.append(f"含 PubMed 补充 {supplement_n} 条")
    audit_bits = []
    if unlabeled_n:
        audit_bits.append(f"另有 {unlabeled_n} 条无来源，已移入审计")

    return f"""<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(author)} · 文献地图</title>
<style>
 :root{{--ink:#1a1a1a;--mut:#777;--line:#e7e7e7;--bg:#fff;--warn:#8a5a00;}}
 *{{box-sizing:border-box}}
 body{{margin:0;background:var(--bg);color:var(--ink);
   font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",sans-serif;}}
 .wrap{{max-width:880px;margin:0 auto;padding:48px 24px 80px}}
 h1{{font-size:26px;font-weight:650;margin:0 0 4px}}
 .sub{{color:var(--mut);margin:0 0 28px;font-size:13px}}
 .stale{{border:1px solid #e7d3a1;background:#fbf6e9;color:var(--warn);
   font-size:13px;padding:10px 14px;border-radius:5px;margin:0 0 24px}}
 .metrics{{display:flex;gap:28px;flex-wrap:wrap;padding:20px 0;border-top:1px solid var(--line);border-bottom:1px solid var(--line);margin-bottom:28px}}
 .m .n{{font-size:24px;font-weight:650}} .m .l{{color:var(--mut);font-size:12px}}
 h2{{font-size:13px;letter-spacing:.06em;color:var(--mut);text-transform:uppercase;font-weight:600;margin:34px 0 12px}}
 .ybar{{display:flex;align-items:center;gap:10px;margin:3px 0;font-size:12px}}
 .ybar .yl{{width:38px;color:var(--mut)}} .ybar .yt{{height:9px;background:var(--ink);border-radius:2px}}
 .ybar .yn{{color:var(--mut)}}
 table{{width:100%;border-collapse:collapse;font-size:14px}}
 td,th{{text-align:left;padding:9px 8px;border-bottom:1px solid var(--line);vertical-align:top}}
 td.num,.yc{{color:var(--mut);white-space:nowrap}} .yc{{width:48px}}
 td.th,.th{{color:var(--mut);font-size:12px;white-space:nowrap}}
 .src{{color:var(--mut);font-size:12px;margin-top:3px}}
 .tag{{font-size:11px;border:1px solid var(--line);border-radius:3px;padding:0 5px;color:var(--mut)}}
 .profilelink{{border:1px solid var(--line);border-radius:5px;padding:10px 12px;margin:0 0 24px;font-size:13px;background:#fafafa}}
 a{{color:var(--ink)}} .foot{{margin-top:48px;color:var(--mut);font-size:12px;border-top:1px solid var(--line);padding-top:16px}}
 .foot code{{font-size:11px}}
</style></head>
<body><div class="wrap">
 {stale_banner}
 <h1>{esc(author)} · 研究脉络地图</h1>
 <p class="sub">{esc(' · '.join(sub_bits))}{('　·　' + esc('；'.join(audit_bits))) if audit_bits else ''}</p>
 {profile_link}
 <div class="metrics">
   <div class="m"><div class="n">{main_n}</div><div class="l">主线纳入</div></div>
   <div class="m"><div class="n">{review_n}</div><div class="l">待人工复核</div></div>
   <div class="m"><div class="n">{excluded_n}</div><div class="l">同名/排除</div></div>
   <div class="m"><div class="n">{yr_range}</div><div class="l">年份跨度</div></div>
 </div>
 {f'<h2>按主题</h2><table>{theme_rows}</table>' if theme_rows else ''}
 {f'<h2>按年份</h2>{year_bars}' if year_bars else ''}
 <h2>主线文献</h2>
 <table><thead><tr><th class="yc">年</th><th>标题与来源</th><th class="th">主题</th></tr></thead>
 <tbody>{work_rows}</tbody></table>
 <div class="foot">
   主线为身份门控确认后的纳入项；待复核 / 同名排除 / 无来源项保留在审计记录，可追溯。<br>
   证据账本：<code>{esc(str(Path(verdict.get('run_dir', '.')) / 'AUTHOR_MAP.json'))}</code>
 </div>
</div></body></html>"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", type=Path, required=True, help="Full-pass output directory")
    ap.add_argument("--author", required=True, help="Author display name for the page")
    ap.add_argument("--pubmed-supplement", type=Path, default=None,
                    help="Optional pubmed_supplement.csv (used only when building the verdict)")
    ap.add_argument("--profile", type=Path, default=None,
                    help="Optional profile.yaml (used only when building the verdict)")
    ap.add_argument("--verdict", type=Path, default=None,
                    help="AUTHOR_MAP.json to render (default: <run-dir>/AUTHOR_MAP.json)")
    ap.add_argument("--out", type=Path, default=None, help="Output HTML (default: run-dir/index.html)")
    args = ap.parse_args(argv)

    verdict_path = args.verdict or (args.run_dir / "AUTHOR_MAP.json")
    if verdict_path.exists():
        verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
        stale = bv.stale_inputs(verdict)
    else:
        # No verdict yet — build it once, through the single computation path.
        extra = [args.pubmed_supplement] if args.pubmed_supplement else []
        verdict = bv.build_verdict(args.run_dir, args.author, args.profile, extra)
        verdict_path.write_text(json.dumps(verdict, ensure_ascii=False, indent=2), encoding="utf-8")
        stale = []
        print(f"Built {verdict_path}")

    page = build_html(verdict, stale)
    out = args.out or (args.run_dir / "index.html")
    out.write_text(page, encoding="utf-8")
    print(f"Rendered {verdict['counts']['main']} works -> {out}"
          + (f"  [STALE: {', '.join(stale)}]" if stale else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
