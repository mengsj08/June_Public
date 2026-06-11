// plan-xhs.js — TEXT-ONLY pagination planner for fixed 小红书 cards. Renders nothing.
// Measures each top-level block's height at the target width, simulates packing into
// fixed cards of CARD_H, and prints which blocks land on each card + fill% + warnings.
// Cheap to review (no image tokens) — tune content/packing here BEFORE rendering.
//
// Usage:  node scripts/plan-xhs.js <caseDir> [--width 1080] [--card 1440]
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
function arg(n, d){ const i = process.argv.indexOf('--' + n); return i > -1 ? process.argv[i+1] : d; }

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const caseDir = path.resolve(process.argv[2] || '.');
const WIDTH = Number(arg('width', 1080));
const CARD_H = Number(arg('card', 1440));
const input = path.join(caseDir, 'longimage.html');
const URL = 'file://' + input;
const PORT = 9388;
const sleep = ms => new Promise(r => setTimeout(r, ms));
const guard = setTimeout(() => { console.error('TIMEOUT'); process.exit(2); }, 60000);
if (!fs.existsSync(input)) { console.error('missing', input); process.exit(1); }

const chrome = spawn(CHROME, ['--headless=new','--disable-gpu','--hide-scrollbars','--no-first-run',
  '--no-default-browser-check','--disable-extensions',`--remote-debugging-port=${PORT}`,
  `--window-size=${WIDTH},1400`,'about:blank'], { stdio: 'ignore' });

let id = 0; const pending = new Map();
function attach(ws){ ws.addEventListener('message', ev => {
  const m = JSON.parse(typeof ev.data==='string'?ev.data:ev.data.toString());
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m.result); pending.delete(m.id); }
  if (m.method==='Page.loadEventFired' && ws.__onload) ws.__onload();
}); }
function send(ws, method, params={}){ return new Promise(res => { const mid=++id; pending.set(mid,res);
  ws.send(JSON.stringify({id:mid, method, params})); }); }

(async () => {
  let wsUrl;
  for (let i=0;i<60;i++){ try {
    const t = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
    const p = t.find(x=>x.type==='page'); if (p?.webSocketDebuggerUrl){ wsUrl=p.webSocketDebuggerUrl; break; }
  } catch {} await sleep(150); }
  if (!wsUrl) throw new Error('no page target');
  const ws = new WebSocket(wsUrl);
  await new Promise(r => ws.addEventListener('open', r, { once:true }));
  attach(ws);
  await send(ws,'Page.enable'); await send(ws,'Runtime.enable');
  await send(ws,'Emulation.setDeviceMetricsOverride',{width:WIDTH,height:1400,deviceScaleFactor:1,mobile:false});
  const onload = new Promise(r => { ws.__onload = r; });
  await send(ws,'Page.navigate',{url:URL}); await onload; await sleep(800);

  const ev = await send(ws,'Runtime.evaluate',{ returnByValue:true, expression:`(() => {
    const blocks = [];
    document.querySelectorAll('header.hero, section, footer').forEach(e => {
      if (e.tagName!=='HEADER' && e.offsetParent===null) return;
      const r = e.getBoundingClientRect();
      // a short label = the eyebrow or h1/h2 text, for human-readable plan
      const lab = (e.querySelector('.eyebrow,h1,h2')||{}).textContent || e.tagName;
      const kids = [];
      e.querySelectorAll(':scope .bgroup, :scope .grid2, :scope .grid3, :scope .tl, :scope .repbar, :scope .tabs, :scope .panel, :scope .mirror, :scope .limit, :scope .cta').forEach(k=>{
        kids.push(Math.round(k.getBoundingClientRect().height));
      });
      blocks.push({ label: lab.trim().slice(0,28), h: Math.round(r.height), kids });
    });
    return blocks;
  })()`});
  const blocks = ev.result.value || [];
  ws.close(); chrome.kill(); clearTimeout(guard);

  // pack consecutive blocks into cards <= CARD_H
  const cards = []; let cur = { items: [], h: 0 };
  for (const b of blocks) {
    if (b.h > CARD_H) { // oversized single block — own card, will overflow
      if (cur.items.length) { cards.push(cur); cur = { items: [], h: 0 }; }
      cards.push({ items: [b], h: b.h, over: true });
      continue;
    }
    if (cur.h + b.h > CARD_H) { cards.push(cur); cur = { items: [], h: 0 }; }
    cur.items.push(b); cur.h += b.h;
  }
  if (cur.items.length) cards.push(cur);

  console.log(`\n小红书分页方案  @${WIDTH}w  固定卡 ${WIDTH}×${CARD_H} (3:4)  —  ${cards.length} 张\n`);
  cards.forEach((c, i) => {
    const fill = Math.round(c.h / CARD_H * 100);
    const flag = c.over ? '  ⚠️ 溢出(单段超高,需拆分)' : fill < 50 ? '  ⚠️ 偏空' : fill > 96 ? '  ⚠️ 偏挤' : '';
    console.log(`卡 ${String(i+1).padStart(2,'0')}  填充 ${String(fill).padStart(3)}%  内容${c.h}px${flag}`);
    c.items.forEach(b => console.log(`        · ${b.label}  (${b.h}px${b.kids.length?', 子块 '+b.kids.join('/')+'px':''})`));
  });
  const probs = cards.filter(c => c.over || c.h/CARD_H<0.5 || c.h/CARD_H>0.96).length;
  console.log(`\n问题卡:${probs} / ${cards.length}。理想:每张 50–96% 填充、无溢出。\n`);
  process.exit(0);
})().catch(e => { console.error('ERR', e.message); chrome.kill(); process.exit(1); });
