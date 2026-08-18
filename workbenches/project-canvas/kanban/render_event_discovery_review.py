#!/usr/bin/env python3
"""Render a self-contained human review page for Event Discovery output."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path


VERDICTS = [
    ("correct", "正确"),
    ("merge", "应合并"),
    ("split", "应拆分"),
    ("not_event", "不是 Event"),
    ("wrong_date", "日期不对"),
]


def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _read_jsonl(path):
    path = Path(path)
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _semantic_map(semantic_briefs):
    if not semantic_briefs:
        return {}
    payload = _read_json(semantic_briefs)
    events = payload.get("events") or {}
    if isinstance(events, list):
        return {
            row["candidate_id"]: row
            for row in events
            if isinstance(row, dict) and row.get("candidate_id")
        }
    if isinstance(events, dict):
        return events
    raise ValueError("semantic briefs events must be an object or list")


def _atomic_scene_map(atomic_scenes):
    if not atomic_scenes:
        return {}
    path = Path(atomic_scenes)
    rows = (
        _read_jsonl(path)
        if path.suffix == ".jsonl"
        else (_read_json(path).get("scenes") or [])
    )
    grouped = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        event_candidate_id = row.get("source_event_candidate_id")
        if not event_candidate_id:
            continue
        grouped.setdefault(event_candidate_id, []).append(row)
    for event_candidate_id in grouped:
        grouped[event_candidate_id].sort(
            key=lambda row: (
                row.get("candidate_order", 9999),
                row.get("candidate_id") or "",
            )
        )
    return grouped


def _event_cards(
    batch_root,
    gold_spec,
    validation,
    semantic_briefs=None,
    atomic_scenes=None,
):
    candidates = {
        row["candidate_id"]: row
        for row in _read_jsonl(Path(batch_root) / "event-detection-candidates.jsonl")
    }
    expected = {
        row["gold_event_id"]: row
        for row in gold_spec.get("expected_events") or []
    }
    cards = []
    matched_ids = set()
    for result in validation.get("event_results") or []:
        candidate = candidates.get(result.get("candidate_id")) or {}
        gold = expected.get(result.get("gold_event_id")) or {}
        candidate_id = result.get("candidate_id")
        if candidate_id:
            matched_ids.add(candidate_id)
        evidence = []
        for source in candidate.get("source_refs") or []:
            source_path = Path(source.get("source_path") or "")
            evidence.append({
                "name": source_path.name,
                "parent": source_path.parent.name,
                "role": source.get("source_role") or "unknown",
                "relation": source.get("relation_proposal") or "supporting_candidate",
            })
        boundary = candidate.get("boundary") or {}
        cards.append({
            "gold_event_id": result.get("gold_event_id"),
            "candidate_id": candidate_id,
            "matched": bool(result.get("matched")),
            "match_count": result.get("match_count", 0),
            "title": candidate.get("proposed_title") or gold.get("title_regex") or "未命名 Event",
            "expected_date": gold.get("date"),
            "actual_date": result.get("actual_date"),
            "date_status": result.get("date_status"),
            "event_type": candidate.get("event_type_hint") or gold.get("event_type_hint"),
            "boundary_status": boundary.get("status") or result.get("boundary_status"),
            "boundary_basis": boundary.get("basis") or gold.get("boundary_basis"),
            "primary_episode_count": boundary.get("primary_episode_count", 0),
            "segment_review_recommended": bool(
                boundary.get("segment_review_recommended")
            ),
            "evidence": evidence,
            "semantic": (semantic_briefs or {}).get(candidate_id),
            "atomic_scenes": (atomic_scenes or {}).get(candidate_id, []),
            "is_extra": False,
        })
    for candidate_id, candidate in candidates.items():
        if candidate_id in matched_ids:
            continue
        boundary = candidate.get("boundary") or {}
        evidence = []
        for source in candidate.get("source_refs") or []:
            source_path = Path(source.get("source_path") or "")
            evidence.append({
                "name": source_path.name,
                "parent": source_path.parent.name,
                "role": source.get("source_role") or "unknown",
                "relation": source.get("relation_proposal") or "supporting_candidate",
            })
        cards.append({
            "gold_event_id": None,
            "candidate_id": candidate_id,
            "matched": False,
            "match_count": 0,
            "title": candidate.get("proposed_title") or "额外候选",
            "expected_date": None,
            "actual_date": (candidate.get("time_hint") or {}).get("date"),
            "date_status": "extra",
            "event_type": candidate.get("event_type_hint"),
            "boundary_status": boundary.get("status"),
            "boundary_basis": boundary.get("basis"),
            "primary_episode_count": boundary.get("primary_episode_count", 0),
            "segment_review_recommended": bool(
                boundary.get("segment_review_recommended")
            ),
            "evidence": evidence,
            "semantic": (semantic_briefs or {}).get(candidate_id),
            "atomic_scenes": (atomic_scenes or {}).get(candidate_id, []),
            "is_extra": True,
        })
    return sorted(
        cards,
        key=lambda row: (
            row.get("actual_date") or row.get("expected_date") or "",
            row.get("title") or "",
        ),
    )


def _list_html(items, *, css_class):
    return (
        f'<ul class="{css_class}">'
        + "".join(f"<li>{html.escape(str(item))}</li>" for item in items)
        + "</ul>"
    )


def _semantic_html(brief):
    if not brief:
        return """
        <section class="semantic-brief semantic-missing">
          <div class="semantic-label">内容层未运行</div>
          <p>当前只能核对文件结构，尚未读取逐字转录与 AI Notes。</p>
        </section>
        """
    segments = "".join(
        (
            "<li>"
            f"<b>{html.escape(segment.get('label') or '片段')}</b>"
            f"<span>{html.escape(segment.get('window') or '')}</span>"
            f"<p>{html.escape(segment.get('content') or '')}</p>"
            "</li>"
        )
        for segment in brief.get("segments") or []
    )
    rounds = "".join(
        (
            "<tr>"
            f"<th>{html.escape(str(round_.get('round') or ''))}</th>"
            f"<td>{html.escape(round_.get('other_party') or '')}</td>"
            f"<td>{html.escape(round_.get('our_side') or '')}</td>"
            f"<td>{html.escape(round_.get('world_change') or '')}</td>"
            f"<td>{html.escape(round_.get('evidence') or '')}</td>"
            "</tr>"
        )
        for round_ in brief.get("interaction_rounds") or []
    )
    crosschecks = "".join(
        (
            "<li>"
            f"<span class=\"check-status {html.escape(check.get('status') or 'note')}\">"
            f"{html.escape(check.get('label') or '核对')}</span>"
            f"<p>{html.escape(check.get('text') or '')}</p>"
            "</li>"
        )
        for check in brief.get("evidence_crosscheck") or []
    )
    unknowns = brief.get("boundary_questions") or []
    unknowns_html = (
        _list_html(unknowns, css_class="boundary-questions")
        if unknowns
        else "<p class=\"no-question\">无需补问：现有证据足以判断 Event 边界。</p>"
    )
    content_title = brief.get("content_title")
    title_html = (
        f"<h3>{html.escape(content_title)}</h3>"
        if content_title
        else ""
    )
    return f"""
    <section class="semantic-brief">
      <div class="semantic-label">已读逐字转录 · AI Notes 交叉核对</div>
      {title_html}
      <p class="event-summary">{html.escape(brief.get('summary') or '')}</p>
      <div class="semantic-grid">
        <div>
          <h4>证据覆盖的内容</h4>
          <ol class="segments">{segments}</ol>
        </div>
        <div class="boundary-box">
          <h4>为什么这样归成 Event</h4>
          <p>{html.escape(brief.get('boundary_rationale') or '')}</p>
        </div>
      </div>
      <div class="rounds-wrap">
        <h4>对方做了什么 → 我们做了什么 → 世界状态变化</h4>
        <table class="rounds">
          <thead><tr><th>轮次</th><th>对方</th><th>我们</th><th>状态变化</th><th>逐字证据</th></tr></thead>
          <tbody>{rounds}</tbody>
        </table>
      </div>
      <div class="crosscheck">
        <h4>证据核对</h4>
        <ul>{crosschecks}</ul>
      </div>
      <div class="boundary-review-question">
        <h4>只问会改变边界的事实</h4>
        {unknowns_html}
      </div>
    </section>
    """


def _atomic_scene_html(scenes):
    if not scenes:
        return """
        <section class="atomic-scenes atomic-scenes-missing">
          <div class="atomic-heading">
            <div>
              <span class="atomic-kicker">Atomic Scene Census</span>
              <h3>尚未抽取业务原子场景</h3>
            </div>
          </div>
        </section>
        """
    scene_rows = []
    for index, scene in enumerate(scenes, 1):
        inputs = _list_html(scene.get("input") or [], css_class="atomic-list")
        actions = _list_html(scene.get("ai_action") or [], css_class="atomic-list")
        unknowns = scene.get("unknowns") or []
        unknowns_html = (
            _list_html(unknowns, css_class="atomic-unknowns")
            if unknowns
            else '<p class="atomic-none">当前没有额外未知项。</p>'
        )
        evidence_refs = "".join(
            (
                "<li>"
                f"<b>{html.escape(ref.get('source_role') or 'evidence')}</b>"
                f"<span>{html.escape(ref.get('source_name') or '')}</span>"
                f"<em>{html.escape(ref.get('locator') or '')}</em>"
                f"<p>{html.escape(ref.get('support') or '')}</p>"
                "</li>"
            )
            for ref in scene.get("source_refs") or []
        )
        disposition = scene.get("disposition") or "unreviewed_candidate"
        confidence = scene.get("confidence") or "unknown"
        scene_rows.append(
            f"""
            <details class="atomic-scene">
              <summary>
                <span class="atomic-number">{index:02d}</span>
                <span class="atomic-title">{html.escape(scene.get('title') or '未命名原子场景')}</span>
                <span class="atomic-badge">{html.escape(disposition)}</span>
                <span class="atomic-confidence">{html.escape(confidence)}</span>
              </summary>
              <div class="atomic-body">
                <p class="source-expression">{html.escape(scene.get('source_expression') or '')}</p>
                <div class="current-work">
                  <b>现在怎么做</b>
                  <span>{html.escape(scene.get('current_work') or '')}</span>
                </div>
                <div class="atomic-flow">
                  <div><b>给什么</b>{inputs}</div>
                  <div><b>AI 只做哪一步</b>{actions}</div>
                  <div><b>拿到什么</b><p>{html.escape(scene.get('output') or '')}</p></div>
                  <div><b>马上拿去干什么</b><p>{html.escape(scene.get('next_use') or '')}</p></div>
                </div>
                <div class="atomic-stop">
                  <b>人在哪停</b>
                  <p>{html.escape(scene.get('human_stop') or '')}</p>
                </div>
                <div class="atomic-evidence">
                  <b>证据定位</b>
                  <ul>{evidence_refs}</ul>
                </div>
                <div class="atomic-foot">
                  <div>
                    <b>边界说明</b>
                    <p>{html.escape(scene.get('boundary_note') or '')}</p>
                  </div>
                  <div>
                    <b>仍未知</b>
                    {unknowns_html}
                  </div>
                </div>
              </div>
            </details>
            """
        )
    return f"""
    <section class="atomic-scenes">
      <div class="atomic-heading">
        <div>
          <span class="atomic-kicker">Atomic Scene Census</span>
          <h3>{len(scenes)} 个业务原子场景候选</h3>
        </div>
        <p>不是产品包，也不是会议主题；每条止于一个可交付、可验收的工作转换。当前均为候选，尚未晋升。</p>
      </div>
      <div class="atomic-stack">{''.join(scene_rows)}</div>
    </section>
    """


def _card_html(card, index):
    candidate_id = html.escape(card.get("candidate_id") or f"missing-{index}")
    status = "命中" if card.get("matched") else "额外候选" if card.get("is_extra") else "未命中"
    status_class = "hit" if card.get("matched") else "warn"
    evidence_items = "".join(
        (
            "<li>"
            f"<span class=\"role role-{html.escape(source['role'])}\">"
            f"{html.escape(source['role'])}</span>"
            f"<span class=\"evidence-name\">{html.escape(source['name'])}</span>"
            f"<span class=\"relation\">{html.escape(source['relation'])}</span>"
            "</li>"
        )
        for source in card.get("evidence") or []
    )
    atomic_html = _atomic_scene_html(card.get("atomic_scenes") or [])
    semantic_html = _semantic_html(card.get("semantic"))
    verdicts = "".join(
        (
            f"<label><input type=\"radio\" name=\"verdict-{candidate_id}\" "
            f"value=\"{value}\"><span>{label}</span></label>"
        )
        for value, label in VERDICTS
    )
    segment_note = (
        f"检测到 {card.get('primary_episode_count')} 个主片段；当前作为同一 Event 的片段保留。"
        if card.get("segment_review_recommended")
        else f"{card.get('primary_episode_count')} 个主证据片段。"
    )
    return f"""
    <article class="event-card" data-candidate-id="{candidate_id}" style="--order:{index}">
      <div class="event-index">{index:02d}</div>
      <div class="event-main">
        <div class="event-kicker">
          <span class="date">{html.escape(card.get('actual_date') or card.get('expected_date') or '日期待定')}</span>
          <span class="status {status_class}">{status}</span>
        </div>
        <h2>{html.escape(card.get('title') or '')}</h2>
        <div class="machine-strip">
          <span>日期 <b>{html.escape(card.get('date_status') or 'unknown')}</b></span>
          <span>边界 <b>{html.escape(card.get('boundary_status') or 'unknown')}</b></span>
          <span>依据 <b>{html.escape(card.get('boundary_basis') or 'unknown')}</b></span>
        </div>
        <p class="segment-note">{html.escape(segment_note)}</p>
        {atomic_html}
        <details class="event-context">
          <summary>展开 Event 内容、交互轮次与边界依据</summary>
          {semantic_html}
        </details>
        <details>
          <summary>展开 {len(card.get('evidence') or [])} 份证据</summary>
          <ul class="evidence-list">{evidence_items}</ul>
        </details>
        <fieldset class="verdicts">
          <legend>Owner 判断</legend>
          {verdicts}
        </fieldset>
        <textarea class="review-note" rows="2" placeholder="只在需要合并、拆分或改日期时补一句"></textarea>
      </div>
    </article>
    """


def render_review_page(
    *,
    batch_root,
    gold_spec_path,
    output,
    baseline_validation_path=None,
    semantic_briefs_path=None,
    atomic_scenes_path=None,
):
    batch_root = Path(batch_root).expanduser().resolve()
    gold_spec_path = Path(gold_spec_path).expanduser().resolve()
    validation_path = batch_root / "gold-validation.json"
    gold_spec = _read_json(gold_spec_path)
    validation = _read_json(validation_path)
    baseline = (
        _read_json(Path(baseline_validation_path).expanduser().resolve())
        if baseline_validation_path
        else None
    )
    semantic_briefs = _semantic_map(
        Path(semantic_briefs_path).expanduser().resolve()
        if semantic_briefs_path
        else None
    )
    atomic_scenes = _atomic_scene_map(
        Path(atomic_scenes_path).expanduser().resolve()
        if atomic_scenes_path
        else None
    )
    cards = _event_cards(
        batch_root,
        gold_spec,
        validation,
        semantic_briefs=semantic_briefs,
        atomic_scenes=atomic_scenes,
    )
    metrics = validation.get("metrics") or {}
    baseline_metrics = (baseline or {}).get("metrics") or {}
    page_data = {
        "schema_version": "mario.event-discovery-human-review/v0",
        "gold_standard_id": validation.get("gold_standard_id"),
        "batch_root_name": batch_root.name,
        "evaluation_hash": validation.get("evaluation_hash"),
        "cards": [
            {
                "candidate_id": row.get("candidate_id"),
                "gold_event_id": row.get("gold_event_id"),
                "title": row.get("title"),
                "date": row.get("actual_date") or row.get("expected_date"),
                "is_extra": row.get("is_extra"),
                "semantic_status": (
                    (row.get("semantic") or {}).get("analysis_status")
                    or "not_run"
                ),
                "atomic_scene_count": len(row.get("atomic_scenes") or []),
            }
            for row in cards
        ],
    }
    atomic_scene_count = sum(len(row.get("atomic_scenes") or []) for row in cards)
    cards_html = "".join(_card_html(card, index) for index, card in enumerate(cards, 1))
    baseline_html = ""
    if baseline:
        baseline_html = (
            "<div class=\"baseline-stamp\">"
            f"<small>失败基线</small><strong>{baseline_metrics.get('unmatched_candidate_count', 0)} 候选</strong>"
            f"<span>{baseline_metrics.get('matched_event_count', 0)}/{baseline_metrics.get('expected_event_count', 0)} 命中</span>"
            "</div>"
        )
    data_json = json.dumps(page_data, ensure_ascii=False).replace("</", "<\\/")
    page = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>BNI · Event 边界验收</title>
  <style>
    :root {{
      --paper:#f4eedf; --paper-deep:#e7dcc1; --ink:#17212b; --navy:#173955;
      --red:#d94a32; --green:#33785a; --amber:#c88724; --line:#b8aa8b;
      --shadow:0 18px 45px rgba(38,42,39,.14);
    }}
    * {{ box-sizing:border-box; }}
    body {{
      margin:0; color:var(--ink); background:
        radial-gradient(circle at 15% 0%, rgba(217,74,50,.09), transparent 28rem),
        repeating-linear-gradient(0deg, transparent 0 27px, rgba(23,57,85,.035) 28px),
        var(--paper);
      font-family:"Songti SC","STSong","Noto Serif CJK SC",serif;
    }}
    body::before {{
      content:""; position:fixed; inset:0; pointer-events:none; opacity:.18;
      background-image:url("data:image/svg+xml,%3Csvg viewBox='0 0 180 180' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.8' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='.18'/%3E%3C/svg%3E");
    }}
    .shell {{ width:min(1120px,calc(100% - 32px)); margin:0 auto; padding:42px 0 80px; position:relative; }}
    header {{ display:grid; grid-template-columns:1fr auto; gap:28px; align-items:end; border-bottom:3px solid var(--ink); padding-bottom:24px; }}
    .eyebrow {{ font:700 12px/1 "PingFang SC",sans-serif; letter-spacing:.24em; color:var(--red); text-transform:uppercase; }}
    h1 {{ font-size:clamp(42px,7vw,86px); line-height:.9; margin:14px 0 12px; letter-spacing:-.055em; }}
    .subtitle {{ max-width:680px; font-size:16px; line-height:1.8; margin:0; }}
    .baseline-stamp {{ width:150px; height:150px; border:2px solid var(--red); color:var(--red); border-radius:50%; display:grid; place-content:center; text-align:center; transform:rotate(7deg); }}
    .baseline-stamp small,.baseline-stamp span {{ font:700 12px/1.4 "PingFang SC",sans-serif; }}
    .baseline-stamp strong {{ font-size:24px; margin:5px 0; }}
    .scoreboard {{ display:grid; grid-template-columns:repeat(5,1fr); gap:1px; margin:24px 0 14px; background:var(--ink); border:1px solid var(--ink); box-shadow:var(--shadow); }}
    .metric {{ background:#fffaf0; padding:18px; min-height:104px; }}
    .metric b {{ display:block; font-size:34px; color:var(--navy); }}
    .metric span {{ font:700 12px/1.5 "PingFang SC",sans-serif; color:#5c615e; }}
    .track {{ display:flex; align-items:center; gap:0; padding:24px 8px 30px; }}
    .track-node {{ width:38px; height:38px; display:grid; place-items:center; border-radius:50%; background:var(--green); color:white; font:800 13px "PingFang SC",sans-serif; box-shadow:0 0 0 6px var(--paper), 0 0 0 8px var(--green); }}
    .track-line {{ height:4px; flex:1; background:linear-gradient(90deg,var(--green),var(--amber)); }}
    .review-toolbar {{ position:sticky; top:10px; z-index:4; display:flex; flex-wrap:wrap; gap:10px; align-items:center; margin:0 0 18px; padding:12px 14px; background:rgba(23,33,43,.94); color:white; box-shadow:var(--shadow); backdrop-filter:blur(8px); }}
    .progress {{ margin-right:auto; font:700 13px "PingFang SC",sans-serif; }}
    button {{ border:0; padding:10px 14px; cursor:pointer; background:var(--paper); color:var(--ink); font:700 13px "PingFang SC",sans-serif; }}
    button.primary {{ background:var(--red); color:white; }}
    .event-card {{ position:relative; display:grid; grid-template-columns:86px 1fr; border-top:1px solid var(--line); padding:26px 0; animation:rise .45s both; animation-delay:calc(var(--order) * 45ms); }}
    @keyframes rise {{ from {{ opacity:0; transform:translateY(16px); }} }}
    .event-index {{ font:900 46px/1 "Bodoni 72","Didot",serif; color:var(--paper-deep); text-shadow:1px 1px 0 var(--line); }}
    .event-kicker {{ display:flex; gap:10px; align-items:center; font:800 12px "PingFang SC",sans-serif; letter-spacing:.08em; }}
    .date {{ color:var(--navy); }}
    .status {{ padding:4px 8px; border-radius:20px; }} .status.hit {{ color:var(--green); background:#dcecdf; }} .status.warn {{ color:#7c4d08; background:#f3dfb6; }}
    h2 {{ margin:8px 0 12px; font-size:clamp(24px,3vw,38px); line-height:1.1; }}
    .machine-strip {{ display:flex; flex-wrap:wrap; gap:8px; }}
    .machine-strip span {{ border:1px solid var(--line); padding:6px 9px; font:12px "PingFang SC",sans-serif; background:rgba(255,250,240,.6); }}
    .machine-strip b {{ color:var(--navy); }}
    .segment-note {{ margin:12px 0; color:#575a56; font-size:14px; }}
    .atomic-scenes {{ margin:20px 0; padding:18px; border:2px solid var(--ink); background:#fffaf0; box-shadow:8px 8px 0 var(--amber); }}
    .atomic-scenes-missing {{ border-style:dashed; box-shadow:none; color:#686b66; }}
    .atomic-heading {{ display:grid; grid-template-columns:minmax(220px,.7fr) minmax(280px,1.3fr); gap:20px; align-items:end; margin-bottom:14px; }}
    .atomic-kicker {{ font:800 10px "PingFang SC",sans-serif; color:var(--red); letter-spacing:.14em; text-transform:uppercase; }}
    .atomic-heading h3 {{ margin:4px 0 0; font-size:24px; color:var(--ink); }}
    .atomic-heading p {{ margin:0; font:12px/1.65 "PingFang SC",sans-serif; color:#666b66; }}
    .atomic-stack {{ display:grid; gap:8px; }}
    details.atomic-scene {{ border:1px solid var(--line); border-left:5px solid var(--navy); padding:0; background:rgba(244,238,223,.58); }}
    details.atomic-scene[open] {{ background:#fff; border-left-color:var(--red); }}
    .atomic-scene summary {{ display:grid; grid-template-columns:38px minmax(0,1fr) auto auto; gap:9px; align-items:center; padding:10px 12px; }}
    .atomic-number {{ font:900 17px "Bodoni 72","Didot",serif; color:var(--red); }}
    .atomic-title {{ font:800 14px/1.45 "PingFang SC",sans-serif; }}
    .atomic-badge,.atomic-confidence {{ padding:3px 6px; font:700 9px "PingFang SC",sans-serif; color:white; background:var(--navy); }}
    .atomic-confidence {{ background:var(--green); }}
    .atomic-body {{ padding:2px 14px 14px; font-family:"PingFang SC",sans-serif; }}
    .source-expression {{ margin:8px 0 12px; color:#575b58; font:12px/1.65 "PingFang SC",sans-serif; }}
    .current-work {{ display:grid; grid-template-columns:92px 1fr; gap:8px; padding:9px 11px; background:#fff6e7; font:12px/1.6 "PingFang SC",sans-serif; }}
    .current-work b,.atomic-stop b,.atomic-evidence>b,.atomic-foot b {{ color:var(--navy); }}
    .atomic-flow {{ display:grid; grid-template-columns:repeat(4,1fr); gap:1px; margin:10px 0; background:var(--line); border:1px solid var(--line); }}
    .atomic-flow>div {{ padding:10px; background:#fffdf7; min-height:128px; }}
    .atomic-flow b {{ display:block; margin-bottom:7px; color:var(--red); font-size:11px; }}
    .atomic-flow p,.atomic-list {{ margin:0; font:11px/1.6 "PingFang SC",sans-serif; }}
    .atomic-list {{ padding-left:16px; }}
    .atomic-stop {{ padding:10px 12px; border-left:4px solid var(--amber); background:#fbf3df; }}
    .atomic-stop p {{ margin:4px 0 0; font:11px/1.6 "PingFang SC",sans-serif; }}
    .atomic-evidence {{ margin-top:11px; }}
    .atomic-evidence ul {{ list-style:none; padding:0; margin:6px 0 0; display:grid; gap:5px; }}
    .atomic-evidence li {{ display:grid; grid-template-columns:72px minmax(180px,1fr) auto; gap:7px; align-items:start; padding:7px 9px; background:#f4eedf; font:10px/1.5 "PingFang SC",sans-serif; }}
    .atomic-evidence em {{ color:#6c706b; font-style:normal; }}
    .atomic-evidence li p {{ grid-column:2 / -1; margin:0; color:#50544f; }}
    .atomic-foot {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-top:11px; }}
    .atomic-foot>div {{ padding:10px 12px; border:1px dashed var(--line); }}
    .atomic-foot p,.atomic-unknowns,.atomic-none {{ margin:4px 0 0; font:10px/1.6 "PingFang SC",sans-serif; }}
    .atomic-unknowns {{ padding-left:16px; }}
    .event-context {{ margin:18px 0; border-left:3px solid var(--green); padding:5px 0 5px 14px; }}
    .event-context>.semantic-brief {{ margin:14px 14px 6px 0; }}
    .semantic-brief {{ margin:18px 0; padding:18px; border:1px solid var(--line); background:rgba(255,250,240,.72); box-shadow:5px 5px 0 var(--paper-deep); }}
    .semantic-missing {{ border-style:dashed; box-shadow:none; color:#686b66; }}
    .semantic-label {{ display:inline-block; padding:5px 8px; color:white; background:var(--green); font:800 11px "PingFang SC",sans-serif; letter-spacing:.06em; }}
    .semantic-brief h3 {{ margin:12px 0 7px; font-size:22px; color:var(--navy); }}
    .semantic-brief h4 {{ margin:0 0 8px; font:800 13px "PingFang SC",sans-serif; color:var(--navy); }}
    .event-summary {{ margin:12px 0 16px; font:15px/1.85 "PingFang SC",sans-serif; }}
    .semantic-grid {{ display:grid; grid-template-columns:minmax(0,1.35fr) minmax(240px,.65fr); gap:16px; }}
    .segments {{ margin:0; padding-left:22px; display:grid; gap:10px; }}
    .segments li {{ padding-left:4px; font:13px/1.65 "PingFang SC",sans-serif; }}
    .segments b {{ display:inline-block; margin-right:8px; }}
    .segments span {{ color:#74776f; font-size:11px; }}
    .segments p {{ margin:2px 0 0; }}
    .boundary-box {{ padding:14px; border-left:4px solid var(--red); background:#fff6e7; }}
    .boundary-box p {{ margin:0; font:13px/1.75 "PingFang SC",sans-serif; }}
    .rounds-wrap {{ margin-top:18px; overflow-x:auto; }}
    .rounds {{ width:100%; border-collapse:collapse; min-width:780px; font:12px/1.65 "PingFang SC",sans-serif; }}
    .rounds th,.rounds td {{ border:1px solid var(--line); padding:9px; text-align:left; vertical-align:top; }}
    .rounds thead th {{ background:var(--navy); color:white; }}
    .rounds tbody th {{ width:54px; color:var(--red); background:#fff6e7; }}
    .rounds td:last-child {{ width:140px; color:#666b66; }}
    .crosscheck,.boundary-review-question {{ margin-top:16px; }}
    .crosscheck ul {{ list-style:none; padding:0; margin:0; display:grid; gap:7px; }}
    .crosscheck li {{ display:grid; grid-template-columns:80px 1fr; gap:9px; align-items:start; }}
    .crosscheck p {{ margin:1px 0 0; font:12px/1.65 "PingFang SC",sans-serif; }}
    .check-status {{ padding:4px 6px; text-align:center; background:var(--navy); color:white; font:700 11px "PingFang SC",sans-serif; }}
    .check-status.match {{ background:var(--green); }} .check-status.caution {{ background:var(--amber); }} .check-status.mismatch {{ background:var(--red); }}
    .boundary-questions {{ margin:0; padding-left:20px; font:12px/1.7 "PingFang SC",sans-serif; }}
    .no-question {{ margin:0; color:var(--green); font:700 12px/1.6 "PingFang SC",sans-serif; }}
    details {{ border-left:3px solid var(--amber); padding:4px 0 4px 14px; }}
    summary {{ cursor:pointer; font:800 13px "PingFang SC",sans-serif; }}
    .evidence-list {{ list-style:none; padding:8px 0 0; margin:0; display:grid; gap:7px; }}
    .evidence-list li {{ display:grid; grid-template-columns:86px 1fr auto; align-items:center; gap:8px; font:12px "PingFang SC",sans-serif; }}
    .role {{ text-align:center; padding:3px 6px; color:white; background:var(--navy); }}
    .role-recording {{ background:var(--red); }} .role-transcript {{ background:var(--green); }} .role-minutes {{ background:var(--amber); }}
    .relation {{ color:#73766f; }}
    .verdicts {{ border:0; padding:0; margin:18px 0 10px; display:flex; flex-wrap:wrap; gap:8px; }}
    .verdicts legend {{ width:100%; font:800 13px "PingFang SC",sans-serif; margin-bottom:7px; }}
    .verdicts input {{ position:absolute; opacity:0; }}
    .verdicts span {{ display:block; padding:9px 13px; border:1px solid var(--ink); font:700 13px "PingFang SC",sans-serif; cursor:pointer; transition:.16s ease; }}
    .verdicts input:checked + span {{ background:var(--ink); color:white; transform:translateY(-2px); box-shadow:3px 3px 0 var(--red); }}
    .review-note {{ width:100%; resize:vertical; border:1px solid var(--line); background:rgba(255,250,240,.7); padding:10px; font:14px "PingFang SC",sans-serif; }}
    .reviewed {{ background:linear-gradient(90deg,rgba(51,120,90,.08),transparent 70%); }}
    footer {{ border-top:3px solid var(--ink); margin-top:24px; padding-top:18px; font:12px/1.7 "PingFang SC",sans-serif; color:#5f625e; }}
    @media(max-width:760px) {{
      header {{ grid-template-columns:1fr; }} .baseline-stamp {{ width:110px;height:110px; }}
      .scoreboard {{ grid-template-columns:repeat(2,1fr); }} .event-card {{ grid-template-columns:48px 1fr; }}
      .event-index {{ font-size:28px; }} .evidence-list li {{ grid-template-columns:76px 1fr; }} .relation {{ display:none; }}
      .semantic-grid {{ grid-template-columns:1fr; }}
      .atomic-heading {{ grid-template-columns:1fr; }}
      .atomic-scene summary {{ grid-template-columns:32px minmax(0,1fr); }}
      .atomic-badge,.atomic-confidence {{ justify-self:start; }}
      .atomic-flow {{ grid-template-columns:1fr; }}
      .atomic-flow>div {{ min-height:0; }}
      .atomic-foot {{ grid-template-columns:1fr; }}
      .atomic-evidence li {{ grid-template-columns:66px 1fr; }}
      .atomic-evidence em {{ grid-column:2; }}
      .atomic-evidence li p {{ grid-column:2; }}
    }}
  </style>
</head>
<body>
  <main class="shell">
    <header>
      <div>
        <div class="eyebrow">Event Boundary Review · Gold Run</div>
        <h1>BNI<br>事件边界验收</h1>
        <p class="subtitle">机器已先按真实互动收成 Event，再从逐字转录里抽出业务原子场景候选。原子场景不是产品或课程，而是“已有输入 → 单一 AI 动作 → 可见输出 → 下一用途”。</p>
      </div>
      {baseline_html}
    </header>
    <section class="scoreboard" aria-label="自动评分">
      <div class="metric"><b>{metrics.get('matched_event_count', 0)}/{metrics.get('expected_event_count', 0)}</b><span>Event 命中</span></div>
      <div class="metric"><b>{metrics.get('exact_date_count', 0)}/{metrics.get('expected_date_count', 0)}</b><span>日期精确</span></div>
      <div class="metric"><b>{metrics.get('unmatched_candidate_count', 0)}</b><span>额外候选</span></div>
      <div class="metric"><b>{metrics.get('canonical_write_count', 0)}</b><span>正式区写入</span></div>
      <div class="metric"><b>{atomic_scene_count}</b><span>原子候选 · 未晋升</span></div>
    </section>
    <div class="track" aria-hidden="true">
      {''.join(f'<span class="track-node">{i}</span>' + ('<span class="track-line"></span>' if i < len(cards) else '') for i in range(1, len(cards)+1))}
    </div>
    <div class="review-toolbar">
      <span class="progress">已确认 <b id="doneCount">0</b> / {len(cards)}</span>
      <button id="copyBtn">复制确认摘要</button>
      <button id="exportBtn" class="primary">导出判断 JSON</button>
      <button id="resetBtn">清空</button>
    </div>
    <section>{cards_html}</section>
    <footer>
      本页先展示逐字转录支持的原子场景候选，再把 Event 内容、交互轮次与边界依据折叠为上下文。候选不等于已实现、客户验收或正式晋升；本页不写 Event Ledger、人物卡、Mario Unit 或场景正本。
    </footer>
  </main>
  <script>
    const REVIEW_DATA = {data_json};
    const storageKey = `mario-event-review:${{REVIEW_DATA.gold_standard_id}}:${{REVIEW_DATA.evaluation_hash}}`;
    const state = JSON.parse(localStorage.getItem(storageKey) || '{{}}');
    const cards = [...document.querySelectorAll('.event-card')];
    function save() {{
      localStorage.setItem(storageKey, JSON.stringify(state));
      renderProgress();
    }}
    function renderProgress() {{
      let done = 0;
      cards.forEach(card => {{
        const id = card.dataset.candidateId;
        const row = state[id] || {{}};
        const radio = card.querySelector(`input[value="${{row.verdict || ''}}"]`);
        if (radio) radio.checked = true;
        card.querySelector('.review-note').value = row.note || '';
        card.classList.toggle('reviewed', Boolean(row.verdict));
        if (row.verdict) done += 1;
      }});
      document.getElementById('doneCount').textContent = done;
    }}
    cards.forEach(card => {{
      const id = card.dataset.candidateId;
      card.querySelectorAll('input[type=radio]').forEach(input => input.addEventListener('change', () => {{
        state[id] = {{ ...(state[id] || {{}}), verdict: input.value }};
        save();
      }}));
      card.querySelector('.review-note').addEventListener('input', event => {{
        state[id] = {{ ...(state[id] || {{}}), note: event.target.value.trim() }};
        save();
      }});
    }});
    function payload() {{
      return {{
        schema_version: REVIEW_DATA.schema_version,
        gold_standard_id: REVIEW_DATA.gold_standard_id,
        evaluation_hash: REVIEW_DATA.evaluation_hash,
        reviewed_at: new Date().toISOString(),
        reviews: REVIEW_DATA.cards.map(card => ({{
          candidate_id: card.candidate_id,
          gold_event_id: card.gold_event_id,
          title: card.title,
          date: card.date,
          verdict: (state[card.candidate_id] || {{}}).verdict || 'unreviewed',
          note: (state[card.candidate_id] || {{}}).note || ''
        }}))
      }};
    }}
    document.getElementById('exportBtn').addEventListener('click', () => {{
      const blob = new Blob([JSON.stringify(payload(), null, 2)], {{type:'application/json'}});
      const link = document.createElement('a');
      link.href = URL.createObjectURL(blob);
      link.download = 'bni-event-boundary-review.json';
      link.click();
      URL.revokeObjectURL(link.href);
    }});
    document.getElementById('copyBtn').addEventListener('click', async () => {{
      const rows = payload().reviews;
      const summary = rows.map((row, index) => `${{index+1}}. ${{row.date}} ${{row.title}}：${{row.verdict}}${{row.note ? '（'+row.note+'）' : ''}}`).join('\\n');
      await navigator.clipboard.writeText(summary);
      const button = document.getElementById('copyBtn');
      button.textContent = '已复制';
      setTimeout(() => button.textContent = '复制确认摘要', 1200);
    }});
    document.getElementById('resetBtn').addEventListener('click', () => {{
      if (!confirm('清空本页全部判断？')) return;
      Object.keys(state).forEach(key => delete state[key]);
      localStorage.removeItem(storageKey);
      cards.forEach(card => {{
        card.querySelectorAll('input').forEach(input => input.checked = false);
        card.querySelector('.review-note').value = '';
      }});
      renderProgress();
    }});
    renderProgress();
  </script>
</body>
</html>
"""
    output = Path(output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(page, encoding="utf-8")
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-root", type=Path, required=True)
    parser.add_argument("--gold-spec", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--baseline-validation", type=Path)
    parser.add_argument("--semantic-briefs", type=Path)
    parser.add_argument("--atomic-scenes", type=Path)
    args = parser.parse_args(argv)
    output = args.output or (args.batch_root / "event-boundary-review.html")
    rendered = render_review_page(
        batch_root=args.batch_root,
        gold_spec_path=args.gold_spec,
        output=output,
        baseline_validation_path=args.baseline_validation,
        semantic_briefs_path=args.semantic_briefs,
        atomic_scenes_path=args.atomic_scenes,
    )
    print(json.dumps({"ok": True, "output": str(rendered)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
