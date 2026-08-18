#!/usr/bin/env python3
"""Render a mario.strategy-map/v1 projection as a standalone HTML world map."""

from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path

import mario_strategy_map


def _root_id(projection):
    raw = str(projection.get("map_id") or "mario-strategy-map").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")
    return (slug or "mario-strategy-map") + "-renderer"


def render_document(projection):
    errors = mario_strategy_map.validate_strategy_map(projection)
    if errors:
        raise ValueError("; ".join(errors))
    root_id = _root_id(projection)
    subject = projection["subject"]
    status = projection["status"]
    data_json = json.dumps(projection, ensure_ascii=False, separators=(",", ":")).replace(
        "</",
        "<\\/",
    )
    title = f"{subject['label']}｜Mario 人物战略世界"
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <title>{html.escape(title)}</title>
  <style>
    :root {{
      --ink: #18212c;
      --ink-soft: #4f5965;
      --paper: #f3eddf;
      --paper-deep: #e8deca;
      --panel: rgba(255, 252, 245, .88);
      --line: #b7aa91;
      --navy: #183b52;
      --ochre: #d99732;
      --rust: #b94f38;
      --moss: #4d735c;
      --mist: #d7e2e0;
      --shadow: 0 18px 48px rgba(54, 43, 26, .13);
      --display: "Iowan Old Style", "Baskerville", "Songti SC", "STSong", serif;
      --body: "Avenir Next", "PingFang SC", "Microsoft YaHei", sans-serif;
    }}
    * {{
      box-sizing: border-box;
    }}
    html {{
      min-width: 320px;
      background: var(--paper);
    }}
    body {{
      margin: 0;
      color: var(--ink);
      background:
        linear-gradient(rgba(24, 59, 82, .035) 1px, transparent 1px),
        linear-gradient(90deg, rgba(24, 59, 82, .035) 1px, transparent 1px),
        radial-gradient(circle at 16% 8%, rgba(217, 151, 50, .18), transparent 27%),
        radial-gradient(circle at 88% 18%, rgba(77, 115, 92, .14), transparent 31%),
        var(--paper);
      background-size: 28px 28px, 28px 28px, auto, auto, auto;
      font-family: var(--body);
      font-size: 15px;
      line-height: 1.55;
    }}
    button {{
      font: inherit;
    }}
    #{root_id} {{
      width: min(1240px, calc(100% - 32px));
      margin: 0 auto;
      padding: 40px 0 64px;
    }}
    #{root_id} .atlas-header {{
      position: relative;
      display: grid;
      grid-template-columns: minmax(0, 1.35fr) minmax(260px, .65fr);
      gap: 28px;
      align-items: end;
      padding: 32px 34px;
      overflow: hidden;
      border: 1px solid rgba(24, 59, 82, .22);
      border-radius: 2px 26px 2px 26px;
      color: #f9f3e7;
      background:
        linear-gradient(112deg, rgba(24, 59, 82, .98), rgba(22, 42, 53, .94)),
        var(--navy);
      box-shadow: var(--shadow);
    }}
    #{root_id} .atlas-header::after {{
      content: "";
      position: absolute;
      width: 230px;
      height: 230px;
      right: -66px;
      top: -92px;
      border: 34px solid rgba(217, 151, 50, .24);
      border-radius: 50%;
      box-shadow: 0 0 0 17px rgba(255, 255, 255, .04);
    }}
    #{root_id} .eyebrow {{
      display: inline-flex;
      align-items: center;
      gap: 10px;
      margin-bottom: 12px;
      color: #f2c87d;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: .16em;
      text-transform: uppercase;
    }}
    #{root_id} .eyebrow::before {{
      content: "";
      width: 28px;
      height: 2px;
      background: currentColor;
    }}
    #{root_id} h1 {{
      max-width: 780px;
      margin: 0;
      font: 600 clamp(34px, 5vw, 66px)/.98 var(--display);
      letter-spacing: -.035em;
    }}
    #{root_id} .role-line {{
      max-width: 780px;
      margin: 18px 0 0;
      color: rgba(255, 250, 240, .76);
      font-size: 15px;
    }}
    #{root_id} .avatar-seal {{
      position: relative;
      z-index: 1;
      justify-self: end;
      display: grid;
      place-items: center;
      width: 150px;
      height: 150px;
      border: 1px solid rgba(255, 255, 255, .28);
      border-radius: 50%;
      color: #102c3c;
      background: var(--ochre);
      box-shadow:
        inset 0 0 0 10px rgba(255, 247, 224, .18),
        0 18px 36px rgba(0, 0, 0, .2);
      font: 700 62px/1 var(--display);
    }}
    #{root_id} .hud {{
      display: grid;
      grid-template-columns: 1.25fr 1.5fr .8fr;
      gap: 1px;
      margin: 14px 0 24px;
      border: 1px solid var(--line);
      background: var(--line);
      box-shadow: 0 10px 28px rgba(61, 49, 30, .08);
    }}
    #{root_id} .hud-cell {{
      min-width: 0;
      padding: 17px 19px;
      background: rgba(255, 252, 245, .82);
    }}
    #{root_id} .hud-label {{
      display: block;
      margin-bottom: 4px;
      color: var(--rust);
      font-size: 11px;
      font-weight: 800;
      letter-spacing: .12em;
    }}
    #{root_id} .hud-value {{
      display: block;
      font-family: var(--display);
      font-size: 17px;
      font-weight: 600;
    }}
    #{root_id} .world-overview {{
      margin-bottom: 20px;
      border: 1px solid var(--line);
      background: rgba(255, 252, 245, .56);
    }}
    #{root_id} .world-overview summary {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
      padding: 13px 17px;
      color: var(--navy);
      cursor: pointer;
      font-size: 13px;
      font-weight: 750;
      letter-spacing: .05em;
      list-style: none;
    }}
    #{root_id} .world-overview summary::-webkit-details-marker {{
      display: none;
    }}
    #{root_id} .world-overview summary::after {{
      content: "＋";
      color: var(--rust);
      font-size: 18px;
      line-height: 1;
    }}
    #{root_id} .world-overview[open] summary::after {{
      content: "−";
    }}
    #{root_id} .world-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
      padding: 0 12px 12px;
    }}
    #{root_id} .world-button {{
      position: relative;
      display: grid;
      gap: 10px;
      min-height: 124px;
      padding: 17px;
      text-align: left;
      color: var(--ink);
      border: 1px solid rgba(24, 59, 82, .2);
      border-radius: 2px 16px 2px 16px;
      background: rgba(255, 252, 245, .86);
      cursor: pointer;
      transition: transform 160ms ease, border-color 160ms ease, box-shadow 160ms ease;
    }}
    #{root_id} .world-button:hover {{
      transform: translateY(-2px);
      border-color: var(--navy);
      box-shadow: 0 10px 24px rgba(24, 59, 82, .1);
    }}
    #{root_id} .world-button[aria-pressed="true"] {{
      color: #f8f1e4;
      border-color: var(--navy);
      background: var(--navy);
      box-shadow: 0 12px 28px rgba(24, 59, 82, .2);
    }}
    #{root_id} .world-topline {{
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
    }}
    #{root_id} .world-index {{
      color: var(--rust);
      font: 700 12px/1 var(--body);
      letter-spacing: .12em;
    }}
    #{root_id} .world-button[aria-pressed="true"] .world-index {{
      color: #f2c87d;
    }}
    #{root_id} .world-name {{
      font: 600 20px/1.1 var(--display);
    }}
    #{root_id} .world-summary {{
      color: var(--ink-soft);
      font-size: 12px;
    }}
    #{root_id} .world-button[aria-pressed="true"] .world-summary {{
      color: rgba(255, 250, 240, .67);
    }}
    #{root_id} .badge {{
      display: inline-flex;
      width: max-content;
      max-width: 100%;
      padding: 3px 8px;
      border: 1px solid currentColor;
      border-radius: 999px;
      font-size: 10px;
      font-weight: 750;
      letter-spacing: .04em;
    }}
    #{root_id} .campaign {{
      border: 1px solid rgba(24, 59, 82, .25);
      border-radius: 2px 26px 2px 26px;
      background: var(--panel);
      box-shadow: var(--shadow);
      overflow: hidden;
    }}
    #{root_id} .campaign-head {{
      display: grid;
      grid-template-columns: minmax(0, 1.3fr) minmax(240px, .7fr);
      gap: 20px;
      padding: 22px 24px;
      border-bottom: 1px solid var(--line);
      background:
        linear-gradient(90deg, rgba(24, 59, 82, .06), transparent 55%),
        rgba(255, 252, 245, .72);
    }}
    #{root_id} .campaign-kicker {{
      color: var(--rust);
      font-size: 11px;
      font-weight: 800;
      letter-spacing: .12em;
    }}
    #{root_id} .campaign-title {{
      margin: 4px 0 7px;
      color: var(--navy);
      font: 600 30px/1.1 var(--display);
    }}
    #{root_id} .campaign-state {{
      margin: 0;
      color: var(--ink-soft);
    }}
    #{root_id} .quest-card {{
      align-self: stretch;
      padding: 15px 17px;
      color: #fff7e9;
      border-left: 5px solid var(--ochre);
      background: #233944;
    }}
    #{root_id} .quest-card span {{
      display: block;
      margin-bottom: 5px;
      color: #f2c87d;
      font-size: 10px;
      font-weight: 800;
      letter-spacing: .13em;
    }}
    #{root_id} .quest-card strong {{
      font-family: var(--display);
      font-size: 17px;
      font-weight: 600;
    }}
    #{root_id} .mission-rail {{
      position: relative;
      display: flex;
      gap: 14px;
      padding: 27px 24px 24px;
      overflow-x: auto;
      overscroll-behavior-inline: contain;
      scrollbar-color: var(--line) transparent;
    }}
    #{root_id} .mission-rail::before {{
      content: "";
      position: absolute;
      top: 63px;
      left: 52px;
      right: 52px;
      height: 2px;
      background:
        repeating-linear-gradient(90deg, var(--line) 0 9px, transparent 9px 16px);
    }}
    #{root_id} .mission {{
      position: relative;
      z-index: 1;
      flex: 0 0 174px;
      display: grid;
      grid-template-rows: 26px 68px auto;
      gap: 7px;
      padding: 0;
      color: var(--ink);
      text-align: left;
      border: 0;
      background: transparent;
      cursor: pointer;
    }}
    #{root_id} .mission-code {{
      color: var(--ink-soft);
      font-size: 11px;
      font-weight: 800;
      letter-spacing: .11em;
    }}
    #{root_id} .mission-node {{
      display: grid;
      place-items: center;
      width: 68px;
      height: 68px;
      border: 2px solid var(--navy);
      border-radius: 50%;
      color: var(--navy);
      background: var(--paper);
      box-shadow: inset 0 0 0 6px rgba(24, 59, 82, .06);
      font: 700 20px/1 var(--display);
      transition: transform 150ms ease, color 150ms ease, background 150ms ease;
    }}
    #{root_id} .mission[data-kind="candidate_event"] .mission-node {{
      border-style: dashed;
      color: #815f28;
      border-color: var(--ochre);
    }}
    #{root_id} .mission[data-kind="episode"] .mission-node,
    #{root_id} .mission[data-kind="checkpoint"] .mission-node {{
      border-color: var(--moss);
      color: var(--moss);
      border-radius: 18px;
    }}
    #{root_id} .mission[data-kind="gate"] .mission-node {{
      color: var(--rust);
      border-color: var(--rust);
      border-radius: 8px 8px 2px 2px;
    }}
    #{root_id} .mission[aria-pressed="true"] .mission-node {{
      color: #fff8e9;
      background: var(--rust);
      border-color: var(--rust);
      transform: translateY(-5px) scale(1.04);
      box-shadow: 0 10px 20px rgba(185, 79, 56, .23);
    }}
    #{root_id} .mission-copy {{
      display: grid;
      gap: 5px;
      align-content: start;
    }}
    #{root_id} .mission-label {{
      font-family: var(--display);
      font-weight: 650;
      line-height: 1.2;
    }}
    #{root_id} .mission-meta {{
      color: var(--ink-soft);
      font-size: 11px;
    }}
    #{root_id} .console {{
      display: grid;
      grid-template-columns: 190px minmax(0, 1fr);
      min-height: 320px;
      border-top: 1px solid var(--line);
    }}
    #{root_id} .lens-nav {{
      padding: 18px 12px;
      color: #f8f0e2;
      background: #263943;
    }}
    #{root_id} .lens-nav-title {{
      margin: 0 10px 12px;
      color: #f2c87d;
      font-size: 10px;
      font-weight: 800;
      letter-spacing: .13em;
    }}
    #{root_id} .lens-button {{
      display: grid;
      grid-template-columns: 24px 1fr;
      gap: 8px;
      width: 100%;
      padding: 11px 10px;
      color: rgba(255, 248, 235, .7);
      text-align: left;
      border: 0;
      border-left: 3px solid transparent;
      background: transparent;
      cursor: pointer;
    }}
    #{root_id} .lens-button:hover {{
      color: #fff8eb;
    }}
    #{root_id} .lens-button[aria-pressed="true"] {{
      color: #fff8eb;
      border-left-color: var(--ochre);
      background: rgba(255, 255, 255, .07);
    }}
    #{root_id} .lens-number {{
      color: #f2c87d;
      font-family: var(--display);
    }}
    #{root_id} .console-body {{
      padding: 24px 27px 28px;
      background:
        linear-gradient(135deg, rgba(24, 59, 82, .025), transparent 48%),
        rgba(255, 252, 245, .74);
    }}
    #{root_id} .console-heading {{
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 18px;
    }}
    #{root_id} .console-heading h2 {{
      margin: 0;
      color: var(--navy);
      font: 600 clamp(23px, 3vw, 34px)/1.1 var(--display);
    }}
    #{root_id} .console-heading p {{
      margin: 7px 0 0;
      color: var(--ink-soft);
      font-size: 12px;
    }}
    #{root_id} .move-list,
    #{root_id} .claim-list,
    #{root_id} .evidence-list {{
      display: grid;
      gap: 10px;
    }}
    #{root_id} .move {{
      display: grid;
      grid-template-columns: 88px minmax(0, 1fr) auto;
      gap: 13px;
      align-items: start;
      padding: 14px 0;
      border-bottom: 1px solid rgba(183, 170, 145, .62);
    }}
    #{root_id} .move:last-child {{
      border-bottom: 0;
    }}
    #{root_id} .actor {{
      color: var(--rust);
      font: 650 16px/1.25 var(--display);
    }}
    #{root_id} .claim {{
      display: grid;
      grid-template-columns: 12px minmax(0, 1fr) auto;
      gap: 12px;
      align-items: start;
      padding: 14px 16px;
      border: 1px solid rgba(24, 59, 82, .16);
      background: rgba(255, 255, 255, .46);
    }}
    #{root_id} .claim-mark {{
      width: 8px;
      height: 8px;
      margin-top: 7px;
      border-radius: 50%;
      background: var(--ochre);
    }}
    #{root_id} .basis {{
      white-space: nowrap;
      padding: 3px 7px;
      border: 1px solid rgba(24, 59, 82, .25);
      border-radius: 999px;
      color: var(--ink-soft);
      font-size: 9px;
      font-weight: 800;
      letter-spacing: .04em;
    }}
    #{root_id} .basis[data-basis="owner_confirmed"] {{
      color: #8b3c2e;
      border-color: rgba(185, 79, 56, .45);
      background: rgba(185, 79, 56, .07);
    }}
    #{root_id} .basis[data-basis="source_backed"] {{
      color: #285e45;
      border-color: rgba(77, 115, 92, .45);
      background: rgba(77, 115, 92, .08);
    }}
    #{root_id} .basis[data-basis="derived"] {{
      color: #67501e;
      border-color: rgba(217, 151, 50, .55);
      background: rgba(217, 151, 50, .09);
    }}
    #{root_id} .evidence-item {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 12px;
      padding: 12px 14px;
      border-left: 3px solid var(--moss);
      background: rgba(77, 115, 92, .07);
    }}
    #{root_id} .evidence-item code {{
      display: block;
      max-width: 780px;
      margin-top: 4px;
      overflow: hidden;
      color: var(--ink-soft);
      font-family: "SFMono-Regular", "Cascadia Mono", monospace;
      font-size: 10px;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    #{root_id} .boundary-note {{
      margin-top: 15px;
      padding: 14px 16px;
      color: #6d352b;
      border: 1px solid rgba(185, 79, 56, .28);
      background: rgba(185, 79, 56, .07);
    }}
    #{root_id} .boundary-note strong {{
      font-family: var(--display);
    }}
    #{root_id} .map-boundaries {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
      margin-top: 16px;
    }}
    #{root_id} .boundary-card {{
      padding: 14px 16px;
      border-top: 3px solid var(--rust);
      background: rgba(255, 252, 245, .74);
      box-shadow: 0 7px 20px rgba(54, 43, 26, .06);
    }}
    #{root_id} .boundary-card strong {{
      display: block;
      margin-bottom: 5px;
      color: var(--navy);
      font-family: var(--display);
    }}
    #{root_id} .boundary-card span {{
      color: var(--ink-soft);
      font-size: 12px;
    }}
    #{root_id} .atlas-footer {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-top: 14px;
      color: var(--ink-soft);
      font-size: 10px;
    }}
    #{root_id} .atlas-footer code {{
      max-width: 64%;
      font-family: "SFMono-Regular", "Cascadia Mono", monospace;
      overflow-wrap: anywhere;
      text-align: right;
    }}
    @media (max-width: 840px) {{
      #{root_id} .atlas-header {{
        grid-template-columns: 1fr;
      }}
      #{root_id} .avatar-seal {{
        position: absolute;
        right: 24px;
        top: 24px;
        width: 82px;
        height: 82px;
        font-size: 34px;
        opacity: .82;
      }}
      #{root_id} .atlas-header h1 {{
        padding-right: 76px;
      }}
      #{root_id} .hud,
      #{root_id} .campaign-head {{
        grid-template-columns: 1fr;
      }}
      #{root_id} .world-grid,
      #{root_id} .map-boundaries {{
        grid-template-columns: 1fr 1fr;
      }}
    }}
    @media (max-width: 620px) {{
      #{root_id} {{
        width: min(100% - 18px, 1240px);
        padding-top: 12px;
      }}
      #{root_id} .atlas-header {{
        padding: 25px 20px 27px;
        border-radius: 2px 20px 2px 20px;
      }}
      #{root_id} .hud,
      #{root_id} .world-grid,
      #{root_id} .map-boundaries {{
        grid-template-columns: 1fr;
      }}
      #{root_id} .campaign-head {{
        padding: 19px 17px;
      }}
      #{root_id} .mission-rail {{
        padding-inline: 17px;
      }}
      #{root_id} .console {{
        grid-template-columns: 1fr;
      }}
      #{root_id} .lens-nav {{
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        padding: 8px;
      }}
      #{root_id} .lens-nav-title {{
        display: none;
      }}
      #{root_id} .lens-button {{
        grid-template-columns: 1fr;
        gap: 2px;
        padding: 9px 5px;
        text-align: center;
        border-left: 0;
        border-bottom: 3px solid transparent;
        font-size: 11px;
      }}
      #{root_id} .lens-button[aria-pressed="true"] {{
        border-left: 0;
        border-bottom-color: var(--ochre);
      }}
      #{root_id} .console-body {{
        padding: 20px 17px 24px;
      }}
      #{root_id} .move {{
        grid-template-columns: 72px minmax(0, 1fr);
      }}
      #{root_id} .move .basis,
      #{root_id} .claim .basis {{
        grid-column: 2;
        justify-self: start;
      }}
      #{root_id} .claim {{
        grid-template-columns: 10px minmax(0, 1fr);
      }}
      #{root_id} .atlas-footer {{
        align-items: flex-start;
        flex-direction: column;
      }}
      #{root_id} .atlas-footer code {{
        max-width: 100%;
        text-align: left;
      }}
    }}
    @media (prefers-reduced-motion: reduce) {{
      #{root_id} .world-button,
      #{root_id} .mission-node {{
        transition: none;
      }}
    }}
  </style>
</head>
<body>
  <main id="{root_id}">
    <header class="atlas-header">
      <div>
        <span class="eyebrow">Mario / person world atlas</span>
        <h1>{html.escape(subject["label"])}</h1>
        <p class="role-line">{html.escape(subject["role"])}</p>
      </div>
      <div class="avatar-seal" aria-hidden="true">{html.escape(subject["label"][:1])}</div>
    </header>

    <section class="hud" aria-label="人物状态">
      <div class="hud-cell">
        <span class="hud-label">当前检查点</span>
        <span class="hud-value">{html.escape(status["checkpoint"])}</span>
      </div>
      <div class="hud-cell">
        <span class="hud-label">总主线</span>
        <span class="hud-value">{html.escape(status["main_quest"])}</span>
      </div>
      <div class="hud-cell">
        <span class="hud-label">事实口径</span>
        <span class="hud-value">{int(status["confirmed_event_count"])} Event · {int(status["candidate_event_count"])} 候选</span>
      </div>
    </section>

    <details class="world-overview" open>
      <summary>人物世界总览 <span>点击世界切换任务线</span></summary>
      <div class="world-grid" data-world-grid></div>
    </details>

    <section class="campaign" aria-live="polite">
      <div class="campaign-head">
        <div>
          <span class="campaign-kicker" data-world-kind></span>
          <h2 class="campaign-title" data-world-title></h2>
          <p class="campaign-state" data-world-state></p>
        </div>
        <div class="quest-card">
          <span>本世界下一关</span>
          <strong data-world-quest></strong>
        </div>
      </div>

      <div class="mission-rail" data-mission-rail role="group" aria-label="当前世界任务线"></div>

      <section class="console">
        <nav class="lens-nav" aria-label="任务观察镜头">
          <p class="lens-nav-title">四镜头还原</p>
          <button class="lens-button" type="button" data-lens="action" aria-pressed="true">
            <span class="lens-number">01</span><span>真实动作</span>
          </button>
          <button class="lens-button" type="button" data-lens="relationship" aria-pressed="false">
            <span class="lens-number">02</span><span>关系变化</span>
          </button>
          <button class="lens-button" type="button" data-lens="capability" aria-pressed="false">
            <span class="lens-number">03</span><span>能力解锁</span>
          </button>
          <button class="lens-button" type="button" data-lens="evidence" aria-pressed="false">
            <span class="lens-number">04</span><span>证据室</span>
          </button>
        </nav>
        <div class="console-body">
          <header class="console-heading">
            <div>
              <h2 data-mission-title></h2>
              <p data-mission-meta></p>
            </div>
            <span class="badge" data-mission-status></span>
          </header>
          <div data-lens-content></div>
        </div>
      </section>
    </section>

    <section class="map-boundaries" data-boundaries aria-label="地图边界"></section>

    <footer class="atlas-footer">
      <span>Event 是事实单元；录音、纪要、课件与补录只作为证据。</span>
      <code>{html.escape(projection["projection_hash"])}</code>
    </footer>

    <script type="application/json" data-projection>{data_json}</script>
    <script>
      (() => {{
        const root = document.getElementById({json.dumps(root_id)});
        const projection = JSON.parse(root.querySelector("[data-projection]").textContent);
        const sourceByRef = Object.fromEntries(
          projection.sources.map((source) => [source.source_ref, source])
        );
        const basisLabels = {{
          source_backed: "来源支持",
          owner_confirmed: "Owner 已确认",
          derived: "Mario 纵向判断",
          unknown: "待确认"
        }};
        const kindLabels = {{
          event: "真实 Event",
          candidate_event: "候选 Event",
          episode: "Interaction Episode",
          checkpoint: "项目状态 · 不计互动",
          gate: "锁定关"
        }};
        const worldGrid = root.querySelector("[data-world-grid]");
        const rail = root.querySelector("[data-mission-rail]");
        const lensContent = root.querySelector("[data-lens-content]");
        const lensButtons = Array.from(root.querySelectorAll("[data-lens]"));
        let activeWorldId = projection.worlds[0].world_id;
        let activeMissionId = projection.worlds[0].missions[0].mission_id;
        let activeLens = "action";

        function make(tag, className, text) {{
          const element = document.createElement(tag);
          if (className) element.className = className;
          if (text !== undefined) element.textContent = text;
          return element;
        }}

        function activeWorld() {{
          return projection.worlds.find((world) => world.world_id === activeWorldId);
        }}

        function activeMission() {{
          return activeWorld().missions.find(
            (mission) => mission.mission_id === activeMissionId
          );
        }}

        function basisChip(basis) {{
          const chip = make("span", "basis", basisLabels[basis] || basis);
          chip.dataset.basis = basis;
          return chip;
        }}

        function renderWorldGrid() {{
          worldGrid.replaceChildren();
          projection.worlds.forEach((world, index) => {{
            const button = make("button", "world-button");
            button.type = "button";
            button.dataset.world = world.world_id;
            button.setAttribute("aria-pressed", String(world.world_id === activeWorldId));
            const top = make("span", "world-topline");
            top.append(
              make("span", "world-index", `WORLD ${{String(index + 1).padStart(2, "0")}}`),
              make("span", "badge", world.badge)
            );
            button.append(
              top,
              make("span", "world-name", world.title),
              make("span", "world-summary", world.summary)
            );
            button.addEventListener("click", () => selectWorld(world.world_id));
            worldGrid.append(button);
          }});
        }}

        function selectWorld(worldId) {{
          activeWorldId = worldId;
          activeMissionId = activeWorld().missions[0].mission_id;
          root.querySelectorAll("[data-world]").forEach((button) => {{
            button.setAttribute("aria-pressed", String(button.dataset.world === worldId));
          }});
          renderCampaign();
        }}

        function renderCampaign() {{
          const world = activeWorld();
          root.querySelector("[data-world-kind]").textContent = world.kind;
          root.querySelector("[data-world-title]").textContent = world.title;
          root.querySelector("[data-world-state]").textContent = world.state;
          root.querySelector("[data-world-quest]").textContent = world.main_quest;
          rail.replaceChildren();
          world.missions.forEach((mission) => {{
            const button = make("button", "mission");
            button.type = "button";
            button.dataset.mission = mission.mission_id;
            button.dataset.kind = mission.kind;
            button.setAttribute(
              "aria-pressed",
              String(mission.mission_id === activeMissionId)
            );
            button.setAttribute(
              "aria-label",
              `${{mission.code}}，${{mission.label}}，${{mission.status}}`
            );
            button.append(
              make("span", "mission-code", mission.code),
              make(
                "span",
                "mission-node",
                mission.kind === "gate" ? "锁" :
                  mission.kind === "episode" ? "EP" :
                  mission.kind === "checkpoint" ? "ST" :
                  String(world.missions.indexOf(mission) + 1).padStart(2, "0")
              )
            );
            const copy = make("span", "mission-copy");
            copy.append(
              make("span", "mission-label", mission.label),
              make("span", "mission-meta", `${{mission.date || "无事件日期"}} · ${{kindLabels[mission.kind]}}`)
            );
            button.append(copy);
            button.addEventListener("click", () => selectMission(mission.mission_id));
            rail.append(button);
          }});
          renderMission();
        }}

        function selectMission(missionId) {{
          activeMissionId = missionId;
          root.querySelectorAll("[data-mission]").forEach((button) => {{
            const selected = button.dataset.mission === missionId;
            button.setAttribute("aria-pressed", String(selected));
            if (selected) button.scrollIntoView({{ behavior: "smooth", block: "nearest", inline: "center" }});
          }});
          renderMission();
        }}

        function renderMission() {{
          const mission = activeMission();
          root.querySelector("[data-mission-title]").textContent =
            `${{mission.code}} · ${{mission.label}}`;
          const eventText = mission.event_refs.length
            ? `Event: ${{mission.event_refs[0]}}`
            : kindLabels[mission.kind];
          root.querySelector("[data-mission-meta]").textContent =
            `${{mission.date || "无事件日期"}} · ${{eventText}}`;
          root.querySelector("[data-mission-status]").textContent = mission.status;
          renderLens();
        }}

        function renderLens() {{
          lensButtons.forEach((button) => {{
            button.setAttribute("aria-pressed", String(button.dataset.lens === activeLens));
          }});
          const mission = activeMission();
          const lens = mission.lenses[activeLens];
          lensContent.replaceChildren();
          if (activeLens === "action") {{
            const list = make("div", "move-list");
            lens.moves.forEach((move) => {{
              const row = make("div", "move");
              row.append(
                make("strong", "actor", move.actor),
                make("span", "", move.text),
                basisChip(move.basis)
              );
              list.append(row);
            }});
            lensContent.append(list);
            return;
          }}
          if (activeLens === "relationship" || activeLens === "capability") {{
            const list = make("div", "claim-list");
            lens.items.forEach((item) => {{
              const row = make("div", "claim");
              row.append(
                make("span", "claim-mark"),
                make("span", "", item.text),
                basisChip(item.basis)
              );
              list.append(row);
            }});
            lensContent.append(list);
            return;
          }}
          const evidenceList = make("div", "evidence-list");
          lens.source_refs.forEach((sourceRef) => {{
            const source = sourceByRef[sourceRef];
            if (!source) return;
            const item = make("div", "evidence-item");
            const copy = make("div");
            copy.append(
              make("strong", "", source.label),
              make("code", "", source.path)
            );
            item.append(copy, make("span", "badge", source.kind));
            evidenceList.append(item);
          }});
          lensContent.append(evidenceList);
          const boundary = make("div", "boundary-note");
          boundary.append(
            make("strong", "", "证据边界："),
            document.createTextNode(lens.boundary)
          );
          lensContent.append(boundary);
        }}

        function renderBoundaries() {{
          const container = root.querySelector("[data-boundaries]");
          container.replaceChildren();
          projection.boundaries.forEach((boundary) => {{
            const card = make("article", "boundary-card");
            card.append(
              make("strong", "", boundary.label),
              make("span", "", boundary.detail)
            );
            container.append(card);
          }});
        }}

        lensButtons.forEach((button) => {{
          button.addEventListener("click", () => {{
            activeLens = button.dataset.lens;
            renderLens();
          }});
        }});
        renderWorldGrid();
        renderCampaign();
        renderBoundaries();
      }})();
    </script>
  </main>
</body>
</html>
"""


def validate_embedded_projection(document, projection):
    match = re.search(
        r'<script type="application/json" data-projection>(.*?)</script>',
        document,
        flags=re.DOTALL,
    )
    if not match:
        return ["Rendered HTML is missing data-projection JSON"]
    try:
        embedded = json.loads(match.group(1).replace("<\\/", "</"))
    except json.JSONDecodeError as exc:
        return [f"Rendered data-projection JSON is unreadable: {exc}"]
    if embedded != projection:
        return ["Rendered data-projection JSON does not match disk projection"]
    return []


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--projection-output", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    projection = mario_strategy_map.build_strategy_map(spec)
    document = render_document(projection)
    embed_errors = validate_embedded_projection(document, projection)
    if embed_errors:
        raise ValueError("; ".join(embed_errors))
    if args.projection_output:
        args.projection_output.parent.mkdir(parents=True, exist_ok=True)
        args.projection_output.write_text(
            json.dumps(projection, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        disk_projection = json.loads(args.projection_output.read_text(encoding="utf-8"))
        if disk_projection != projection:
            raise ValueError("Disk projection output does not match built projection")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(document, encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "spec": str(args.spec.resolve()),
                "projection_output": (
                    str(args.projection_output.resolve()) if args.projection_output else None
                ),
                "output": str(args.output.resolve()),
                "projection_hash": projection["projection_hash"],
                "world_count": len(projection["worlds"]),
                "mission_count": sum(len(world["missions"]) for world in projection["worlds"]),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
