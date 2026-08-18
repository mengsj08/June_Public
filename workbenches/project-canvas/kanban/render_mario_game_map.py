#!/usr/bin/env python3
"""Render a mario.game-projection/v1 JSON file as a Codex HTML fragment."""

from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path

import mario_game_projection


def _root_id(projection):
    raw = str(projection.get("projection_id") or "mario-game-map").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")
    return (slug or "mario-game-map") + "-renderer"


def render_fragment(projection):
    errors = mario_game_projection.validate_game_projection(projection)
    if errors:
        raise ValueError("; ".join(errors))
    root_id = _root_id(projection)
    subject = projection.get("subject") or {}
    status = projection.get("status") or {}
    data_json = json.dumps(projection, ensure_ascii=False, separators=(",", ":")).replace(
        "</",
        "<\\/",
    )
    controls = [
        '<button class="btn btn-primary" type="button" data-stage="all" '
        'aria-pressed="true">全地图</button>'
    ]
    for level in projection.get("levels") or []:
        date = html.escape(str(level.get("canonical_time") or ""))
        raw_label = str(level.get("title") or level.get("level_id") or "")
        label = html.escape(raw_label.split("｜", 1)[-1])
        controls.append(
            '<button class="btn" type="button" '
            f'data-stage="{html.escape(str(level.get("level_id") or ""), quote=True)}" '
            f'aria-pressed="false">{date} · {label}</button>'
        )
    if projection.get("excluded_signals"):
        controls.append(
            '<button class="btn btn-ghost" type="button" data-stage="excluded" '
            'aria-pressed="false">不计互动的边界</button>'
        )
    return f"""<div id="{root_id}">
  <style>
    #{root_id} {{
      --mario-fg: var(--foreground, #172033);
      --mario-muted-fg: var(--muted-foreground, #667085);
      --mario-bg: var(--background, #f7f9fc);
      --mario-card: var(--card, #ffffff);
      --mario-muted: var(--muted, #e9eef5);
      --mario-border: var(--border, #cfd8e6);
      --mario-primary: var(--primary, #e34b32);
      --mario-primary-fg: var(--primary-foreground, #ffffff);
      --mario-series-1: var(--viz-series-1, #2f80ed);
      --mario-series-2: var(--viz-series-2, #27ae60);
      --mario-series-3: var(--viz-series-3, #f2994a);
      --mario-series-4: var(--viz-series-4, #9b51e0);
      width: 100%;
      box-sizing: border-box;
      padding: 18px;
      color: var(--mario-fg);
      background: var(--mario-bg);
      font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    #{root_id},
    #{root_id} * {{
      box-sizing: border-box;
    }}
    #{root_id} .viz-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
    }}
    #{root_id} .card {{
      padding: 14px 16px;
      border: 1px solid var(--mario-border);
      border-radius: 12px;
      background: var(--mario-card);
      box-shadow: 0 4px 14px rgba(23, 32, 51, .06);
    }}
    #{root_id} .viz-stat-value {{
      margin: 3px 0;
      color: var(--mario-fg);
      font-size: 18px;
      font-weight: 700;
    }}
    #{root_id} .text-muted {{
      color: var(--mario-muted-fg);
    }}
    #{root_id} .text-small {{
      font-size: 12px;
    }}
    #{root_id} .viz-controls {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}
    #{root_id} .btn {{
      appearance: none;
      padding: 7px 11px;
      border: 1px solid var(--mario-border);
      border-radius: 8px;
      color: var(--mario-fg);
      background: var(--mario-card);
      font: inherit;
      cursor: pointer;
    }}
    #{root_id} .btn:hover {{
      border-color: var(--mario-series-1);
    }}
    #{root_id} .btn-primary {{
      border-color: var(--mario-series-1);
      color: #ffffff;
      background: var(--mario-series-1);
    }}
    #{root_id} .btn-ghost {{
      background: transparent;
    }}
    #{root_id} .game-hud {{
      margin-bottom: 12px;
    }}
    #{root_id} .game-controls {{
      margin-bottom: 8px;
    }}
    #{root_id} .game-map {{
      display: block;
      width: 100%;
      height: auto;
      min-height: 360px;
    }}
    #{root_id} .sky {{
      fill: color-mix(in srgb, var(--mario-series-1) 7%, transparent);
    }}
    #{root_id} .road {{
      fill: color-mix(in srgb, var(--mario-fg) 8%, transparent);
    }}
    #{root_id} .road-line,
    #{root_id} .link {{
      stroke: var(--mario-border);
      stroke-width: 2;
      fill: none;
    }}
    #{root_id} .link.upstream {{
      stroke-dasharray: 7 6;
    }}
    #{root_id} .link.quest {{
      stroke: var(--mario-series-3);
      stroke-dasharray: 4 5;
    }}
    #{root_id} .world-block {{
      fill: color-mix(in srgb, var(--mario-series-2) 16%, var(--mario-card));
      stroke: var(--mario-series-2);
      stroke-width: 2;
    }}
    #{root_id} .world-block.scene {{
      fill: color-mix(in srgb, var(--mario-series-4) 16%, var(--mario-card));
      stroke: var(--mario-series-4);
    }}
    #{root_id} .level-block {{
      fill: color-mix(in srgb, var(--mario-series-1) 18%, var(--mario-card));
      stroke: var(--mario-series-1);
      stroke-width: 2;
    }}
    #{root_id} .level-node {{
      transition: opacity 180ms ease, transform 180ms ease;
      transform-box: fill-box;
      transform-origin: center;
    }}
    #{root_id} .level-node.is-dimmed {{
      opacity: .28;
    }}
    #{root_id} .level-node.is-selected {{
      transform: translateY(-7px);
    }}
    #{root_id} .level-node.is-selected .level-block {{
      fill: color-mix(in srgb, var(--mario-series-1) 30%, var(--mario-card));
      stroke-width: 4;
    }}
    #{root_id} .drop-block {{
      fill: color-mix(in srgb, var(--mario-series-3) 22%, var(--mario-card));
      stroke: var(--mario-series-3);
      stroke-width: 1.5;
    }}
    #{root_id} .asset-block {{
      fill: color-mix(in srgb, var(--mario-series-4) 24%, var(--mario-card));
      stroke: var(--mario-series-4);
      stroke-width: 1.5;
    }}
    #{root_id} .quest-block {{
      fill: color-mix(in srgb, var(--mario-series-3) 16%, var(--mario-card));
      stroke: var(--mario-series-3);
      stroke-width: 2;
    }}
    #{root_id} .gate-block,
    #{root_id} .excluded-block {{
      fill: color-mix(in srgb, var(--mario-muted) 78%, transparent);
      stroke: var(--mario-muted-fg);
      stroke-width: 1.5;
    }}
    #{root_id} .avatar {{
      fill: var(--mario-primary);
      stroke: var(--mario-primary-fg);
      stroke-width: 2;
    }}
    #{root_id} .avatar-text {{
      fill: var(--mario-primary-fg);
      font-weight: 500;
    }}
    #{root_id} .map-label,
    #{root_id} .map-sub,
    #{root_id} .map-mini {{
      fill: var(--mario-fg);
      text-anchor: middle;
      font-weight: 500;
    }}
    #{root_id} .map-sub,
    #{root_id} .map-mini {{
      fill: var(--mario-muted-fg);
      font-weight: 400;
    }}
    #{root_id} .map-label {{
      font-size: calc(var(--font-size-base, 14px) * .84);
    }}
    #{root_id} .map-sub {{
      font-size: calc(var(--font-size-base, 14px) * .71);
    }}
    #{root_id} .map-mini {{
      font-size: calc(var(--font-size-base, 14px) * .64);
    }}
    #{root_id} .detail-card {{
      margin-top: 10px;
    }}
    #{root_id} .detail-grid {{
      display: grid;
      grid-template-columns: minmax(0, 1.35fr) minmax(0, 1fr);
      gap: 16px;
      align-items: start;
    }}
    #{root_id} .detail-title {{
      margin: 0 0 8px;
      font-weight: 500;
    }}
    #{root_id} .detail-list {{
      margin: 0;
      padding-left: 18px;
    }}
    #{root_id} .detail-list li + li {{
      margin-top: 4px;
    }}
    #{root_id} .source-line {{
      margin: 0;
    }}
    #{root_id} .legend {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px 14px;
      margin-top: 10px;
      color: var(--mario-muted-fg);
    }}
    #{root_id} .legend-item {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }}
    #{root_id} .legend-swatch {{
      width: 12px;
      height: 12px;
      display: inline-block;
    }}
    #{root_id} .legend-event {{
      background: color-mix(in srgb, var(--mario-series-1) 28%, var(--mario-card));
      border: 1px solid var(--mario-series-1);
    }}
    #{root_id} .legend-world {{
      background: color-mix(in srgb, var(--mario-series-2) 24%, var(--mario-card));
      border: 1px solid var(--mario-series-2);
    }}
    #{root_id} .legend-quest {{
      background: color-mix(in srgb, var(--mario-series-3) 24%, var(--mario-card));
      border: 1px solid var(--mario-series-3);
    }}
    #{root_id} .legend-asset {{
      background: color-mix(in srgb, var(--mario-series-4) 24%, var(--mario-card));
      border: 1px solid var(--mario-series-4);
    }}
    #{root_id} .legend-lock {{
      background: var(--mario-muted);
      border: 1px solid var(--mario-muted-fg);
    }}
    @media (max-width: 560px) {{
      #{root_id} .viz-grid,
      #{root_id} .detail-grid {{
        grid-template-columns: 1fr;
      }}
      #{root_id} .game-map {{
        min-height: 300px;
      }}
    }}
    @media (prefers-reduced-motion: reduce) {{
      #{root_id} .level-node {{
        transition: none;
      }}
    }}
  </style>

  <div class="viz-grid game-hud" aria-label="{html.escape(str(subject.get("label") or ""))} Mario 世界状态">
    <div class="card viz-stat">
      <div class="text-muted">主角</div>
      <div class="viz-stat-value">{html.escape(str(subject.get("label") or ""))}</div>
      <div>{html.escape(str(subject.get("role") or ""))}</div>
    </div>
    <div class="card viz-stat">
      <div class="text-muted">确认互动 Event</div>
      <div class="viz-stat-value">{int(status.get("confirmed_interaction_count") or 0)} 次</div>
      <div>{html.escape(str(status.get("interaction_count_basis") or ""))}</div>
    </div>
    <div class="card viz-stat">
      <div class="text-muted">当前检查点</div>
      <div class="viz-stat-value">{html.escape(str(status.get("label") or ""))}</div>
      <div>{len(projection.get("worlds") or [])} 个世界 · {sum(len(level.get("asset_drops") or []) for level in projection.get("levels") or [])} 个道具 · {len(projection.get("gates") or [])} 扇锁门</div>
    </div>
  </div>

  <div class="viz-controls game-controls" aria-label="选择地图关卡">
    {"".join(controls)}
  </div>

  <svg class="game-map" viewBox="0 0 1000 580" role="img" data-map
       aria-label="{html.escape(str(subject.get("label") or ""))}的人物关系 Mario 世界地图"></svg>

  <div class="card detail-card" aria-live="polite">
    <div class="detail-grid">
      <div>
        <p class="detail-title" data-detail-title></p>
        <ul class="detail-list" data-detail-facts></ul>
      </div>
      <div>
        <p class="detail-title">事实资料</p>
        <p class="source-line text-muted" data-detail-sources></p>
      </div>
    </div>
    <div class="legend text-small" aria-label="地图图例">
      <span class="legend-item"><span class="legend-swatch legend-event"></span>真实互动 Event</span>
      <span class="legend-item"><span class="legend-swatch legend-world"></span>项目 / 场景世界</span>
      <span class="legend-item"><span class="legend-swatch legend-quest"></span>机会支线</span>
      <span class="legend-item"><span class="legend-swatch legend-asset"></span>Event Asset / 关卡道具</span>
      <span class="legend-item"><span class="legend-swatch legend-lock"></span>未知项或不计互动边界</span>
    </div>
  </div>

  <script type="application/json" data-projection>{data_json}</script>
  <script>
    (() => {{
      const root = document.getElementById('{root_id}');
      const projection = JSON.parse(root.querySelector('[data-projection]').textContent);
      const svg = root.querySelector('[data-map]');
      const title = root.querySelector('[data-detail-title]');
      const facts = root.querySelector('[data-detail-facts]');
      const sources = root.querySelector('[data-detail-sources]');
      const buttons = Array.from(root.querySelectorAll('[data-stage]'));
      const ns = 'http://www.w3.org/2000/svg';
      const sourceByRole = Object.fromEntries(projection.sources.map((source) => [source.role, source]));
      const levelById = Object.fromEntries(projection.levels.map((level) => [level.level_id, level]));

      function element(name, attrs = {{}}, text = '') {{
        const node = document.createElementNS(ns, name);
        Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, String(value)));
        if (text) node.textContent = text;
        return node;
      }}

      function clip(value, max = 24) {{
        const text = String(value || '');
        return text.length > max ? text.slice(0, max - 1) + '…' : text;
      }}

      function displayTitle(value) {{
        return String(value || '').split('｜').slice(-1)[0];
      }}

      function label(group, x, y, value, className = 'map-label') {{
        group.appendChild(element('text', {{ x, y, class: className }}, clip(value)));
      }}

      function path(d, className = 'link') {{
        svg.appendChild(element('path', {{ d, class: className }}));
      }}

      function drawMap() {{
        svg.replaceChildren();
        svg.appendChild(element('rect', {{ x: 0, y: 0, width: 1000, height: 430, class: 'sky' }}));
        svg.appendChild(element('rect', {{ x: 0, y: 276, width: 1000, height: 58, class: 'road' }}));
        path('M 55 276 H 945', 'road-line');

        const worldCount = Math.max(projection.worlds.length, 1);
        const worldGap = 930 / worldCount;
        const worldPos = {{}};
        projection.worlds.forEach((world, index) => {{
          const x = 35 + index * worldGap;
          const width = Math.min(190, worldGap - 14);
          const center = x + width / 2;
          worldPos[world.world_ref] = {{ x: center, y: 126 }};
          const group = element('g', {{
            'aria-label': `${{world.title}}，${{world.state}}`,
          }});
          group.appendChild(element('rect', {{
            x, y: 46, width, height: 80, rx: 8,
            class: `world-block ${{world.world_type === 'scene' ? 'scene' : ''}}`,
          }}));
          label(group, center, 72, world.title);
          label(group, center, 94, world.world_type === 'scene' ? '场景世界' : '持续关系世界', 'map-sub');
          label(group, center, 114, world.latest_update || world.state, 'map-mini');
          svg.appendChild(group);
        }});

        const levelCount = Math.max(projection.levels.length, 1);
        const levelGap = 780 / levelCount;
        const levelPos = {{}};
        projection.levels.forEach((level, index) => {{
          const center = 150 + index * levelGap + levelGap / 2;
          levelPos[level.level_id] = {{ x: center, y: 276 }};
          level.world_links.forEach((link) => {{
            const target = worldPos[link.target_ref];
            if (!target || link.relation === 'opportunity_projection') return;
            const className = link.relation === 'upstream_discovery' ? 'link upstream' : 'link';
            path(`M ${{center}} 276 C ${{center}} 205, ${{target.x}} 190, ${{target.x}} ${{target.y}}`, className);
          }});
        }});

        projection.levels.forEach((level) => {{
          const center = levelPos[level.level_id].x;
          const group = element('g', {{
            class: 'level-node',
            'data-map-stage': level.level_id,
            'aria-label': `${{level.canonical_time}}，${{level.title}}`,
          }});
          group.appendChild(element('rect', {{
            x: center - 82, y: 235, width: 164, height: 72, rx: 8, class: 'level-block',
          }}));
          label(group, center, 259, `${{level.canonical_time}} · 关卡 ${{level.level_number}}`);
          label(group, center, 280, displayTitle(level.title), 'map-sub');
          label(group, center, 299, `${{level.participants.length}} 位玩家 · ${{level.fact_drops.length}} 事实 · ${{level.asset_drops.length}} 道具`, 'map-mini');
          const dropCount = Math.min(level.fact_drops.length, 4);
          const startX = center - ((dropCount - 1) * 38) / 2;
          for (let index = 0; index < dropCount; index += 1) {{
            const x = startX + index * 38;
            group.appendChild(element('rect', {{
              x: x - 14, y: 197, width: 28, height: 26, rx: 4, class: 'drop-block',
            }}));
            label(group, x, 216, String(index + 1), 'map-mini');
          }}
          const assetCount = Math.min(level.asset_drops.length, 3);
          const assetStartX = center - ((assetCount - 1) * 42) / 2;
          for (let index = 0; index < assetCount; index += 1) {{
            const x = assetStartX + index * 42;
            group.appendChild(element('rect', {{
              x: x - 17, y: 316, width: 34, height: 27, rx: 5, class: 'asset-block',
            }}));
            label(group, x, 335, '道具', 'map-mini');
          }}
          svg.appendChild(group);
        }});

        const avatar = element('g', {{ 'aria-label': `主角：${{projection.subject.label}}` }});
        avatar.appendChild(element('circle', {{ cx: 70, cy: 285, r: 25, class: 'avatar' }}));
        label(avatar, 70, 292, String(projection.subject.label || '').slice(0, 1), 'avatar-text');
        label(avatar, 70, 326, '关系主线', 'map-mini');
        svg.appendChild(avatar);

        projection.quests.forEach((quest, index) => {{
          const sourceId = quest.linked_event_ids[0];
          const source = levelPos[sourceId] || {{ x: 800, y: 307 }};
          const center = Math.min(850, Math.max(170, source.x + index * 120));
          path(`M ${{source.x}} 307 C ${{source.x}} 345, ${{center}} 350, ${{center}} 376`, 'link quest');
          const group = element('g', {{ 'aria-label': `机会支线：${{quest.title}}` }});
          group.appendChild(element('rect', {{
            x: center - 105, y: 376, width: 210, height: 58, rx: 8, class: 'quest-block',
          }}));
          label(group, center, 399, `支线 · ${{quest.title}}`);
          label(group, center, 420, quest.state, 'map-mini');
          svg.appendChild(group);
        }});

        if (projection.excluded_signals.length) {{
          const group = element('g', {{ 'aria-label': '不计为真实互动的边界' }});
          group.appendChild(element('rect', {{
            x: 45, y: 382, width: 205, height: 52, rx: 8, class: 'excluded-block',
          }}));
          label(group, 147, 403, '不计互动');
          label(group, 147, 423, `${{projection.excluded_signals.length}} 个内部动作 / 仅被提及`, 'map-mini');
          svg.appendChild(group);
        }}

        const gateCount = Math.max(projection.gates.length, 1);
        const gateGap = 900 / gateCount;
        projection.gates.forEach((gate, index) => {{
          const center = 50 + index * gateGap + gateGap / 2;
          const width = Math.min(260, gateGap - 18);
          const group = element('g', {{ 'aria-label': `锁定条件：${{gate.unlock_condition}}` }});
          group.appendChild(element('rect', {{
            x: center - width / 2, y: 486, width, height: 54, rx: 8, class: 'gate-block',
          }}));
          label(group, center, 509, `🔒 ${{gate.title}}`);
          label(group, center, 529, gate.unlock_condition, 'map-mini');
          svg.appendChild(group);
        }});
      }}

      function setDetail(detailTitle, detailFacts, sourceRefs) {{
        title.textContent = detailTitle;
        facts.replaceChildren(...detailFacts.map((fact) => {{
          const item = document.createElement('li');
          item.textContent = fact;
          return item;
        }}));
        const labels = sourceRefs
          .map((role) => sourceByRole[role])
          .filter(Boolean)
          .map((source) => source.label);
        sources.textContent = labels.length ? [...new Set(labels)].join(' · ') : '当前投影中的已核准来源';
      }}

      function selectStage(stageId) {{
        buttons.forEach((button) => {{
          const selected = button.dataset.stage === stageId;
          button.setAttribute('aria-pressed', String(selected));
          button.classList.toggle('btn-primary', selected);
        }});
        root.querySelectorAll('[data-map-stage]').forEach((node) => {{
          const selected = node.getAttribute('data-map-stage') === stageId;
          node.classList.toggle('is-selected', selected);
          node.classList.toggle('is-dimmed', stageId !== 'all' && stageId !== 'excluded' && !selected);
        }});

        if (stageId === 'all') {{
          setDetail(
            `全地图｜${{projection.subject.label}} Relationship Unit`,
            [
              `当前官方状态：${{projection.status.label}}。`,
              `${{projection.levels.length}} 个确认 Event，连接 ${{projection.worlds.length}} 个项目/场景世界和 ${{projection.quests.length}} 条机会支线。`,
              `${{projection.levels.reduce((count, level) => count + level.asset_drops.length, 0)}} 个 Event Asset 已作为关卡道具呈现，不增加互动次数。`,
              `${{projection.gates.length}} 个未知项仍锁定；${{projection.excluded_signals.length}} 个内部动作或仅被提及的信号没有被冒充互动。`,
            ],
            ['task_state', 'relationship_boundary', 'event_facts', 'project_identity'],
          );
          return;
        }}
        if (stageId === 'excluded') {{
          setDetail(
            '地图边界｜这些不计为双方真实互动',
            projection.excluded_signals.map((item) => item.statement),
            ['task_state', 'relationship_boundary'],
          );
          return;
        }}
        const level = levelById[stageId];
        if (!level) return;
        const roleFacts = level.participants.map((person) => `玩家角色：${{person.role_label || person.entity_ref}}`);
        const dropFacts = level.fact_drops.map((drop) => `事实掉落：${{drop.text}}`);
        const assetFacts = level.asset_drops.map((asset) =>
          `道具掉落：${{asset.label}}（${{asset.stage}} · ${{asset.origin}} · 不新增互动）`
        );
        const linkFacts = level.world_links.map((link) => `世界去向：${{link.label}} → ${{link.target_ref}}`);
        setDetail(
          `关卡 ${{level.level_number}}｜${{level.canonical_time}} · ${{displayTitle(level.title)}}`,
          [...roleFacts, ...dropFacts, ...assetFacts, ...linkFacts],
          [...level.source_refs, ...level.asset_drops.map((asset) => asset.source_role)],
        );
      }}

      buttons.forEach((button) => {{
        button.addEventListener('click', () => selectStage(button.dataset.stage));
      }});
      drawMap();
      selectStage('all');
    }})();
  </script>
</div>
"""


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--projection", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    projection = json.loads(args.projection.read_text(encoding="utf-8"))
    fragment = render_fragment(projection)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(fragment, encoding="utf-8")
    print(json.dumps({
        "ok": True,
        "projection": str(args.projection.resolve()),
        "output": str(args.output.resolve()),
        "projection_hash": projection.get("projection_hash"),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
