// measure-cards.js — TEXT-ONLY density check for fixed 小红书 cards. Renders nothing visual.
// For each .shot.xhs-card it measures the NATURAL content height (clone, top-aligned, auto
// margins zeroed) and reports fill% of the usable area (card minus padding). Flags cards that
// fall below the density target so they can be enriched from the source — see xhs-recipes.md.
//
// Usage:  node scripts/measure-cards.js <caseDir> [--target 78]
//   reads <caseDir>/xhs-cards.html
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
function arg(n, d){ const i = process.argv.indexOf('--' + n); return i > -1 ? process.argv[i+1] : d; }

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const caseDir = path.resolve(process.argv[2] || '.');
const TARGET = Number(arg('target', 78));
const input = path.join(caseDir, 'xhs-cards.html');
const URL = 'file://' + input;
const PORT = 9399;
const PAD = 172; // 86px top + 86px bottom (.xhs-card padding); usable = 1440 - 172 = 1268
const sleep = ms => new Promise(r => setTimeout(r, ms));
const guard = setTimeout(() => { console.error('TIMEOUT'); process.exit(2); }, 60000);
if (!fs.existsSync(input)) { console.error('missing', input); process.exit(1); }

const chrome = spawn(CHROME, ['--headless=new','--disable-gpu','--hide-scrollbars','--no-first-run',
  '--no-default-browser-check','--disable-extensions',`--remote-debugging-port=${PORT}`,
  '--window-size=1080,1400','about:blank'], { stdio: 'ignore' });

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
  await send(ws,'Emulation.setDeviceMetricsOverride',{width:1080,height:1400,deviceScaleFactor:1,mobile:false});
  const onload = new Promise(r => { ws.__onload = r; });
  await send(ws,'Page.navigate',{url:URL}); await onload; await sleep(700);

  const ev = await send(ws,'Runtime.evaluate',{ returnByValue:true, expression:`(() => {
    const PAD=${PAD}, USABLE=1440-PAD;
    return Array.from(document.querySelectorAll('.shot.xhs-card')).map(card => {
      const exempt = card.classList.contains('quote') || !!card.querySelector('.c-hook');
      const clone = card.cloneNode(true);
      clone.style.height='auto'; clone.style.justifyContent='flex-start';
      clone.style.position='absolute'; clone.style.left='-9999px'; clone.style.top='0';
      Array.from(clone.children).forEach(ch => { ch.style.margin='0'; });
      clone.querySelectorAll('.foot,.bigstat').forEach(e => e.style.marginTop='0');
      document.body.appendChild(clone);
      const total = clone.getBoundingClientRect().height;
      document.body.removeChild(clone);
      const contentH = Math.round(total - PAD);
      return { name: card.getAttribute('data-name'), exempt,
        contentH, pct: Math.round(contentH / USABLE * 100) };
    });
  })()`});
  const cards = ev.result.value || [];
  ws.close(); chrome.kill(); clearTimeout(guard);

  console.log(`\n密度检查 ${path.basename(caseDir)}  (可用区 1268px;目标 ≥${TARGET}%)\n`);
  let probs = 0;
  cards.forEach(c => {
    let flag = '';
    if (c.pct > 100) { flag = '  ⚠️ 溢出(裁切!需精简或拆分)'; probs++; }
    else if (c.exempt) { flag = '  ·豁免(封面/金句)'; }
    else if (c.pct < TARGET) { flag = '  ⚠️ 偏空 → 回原文补细节'; probs++; }
    console.log(`${c.name}  fill ${String(c.pct).padStart(3)}%  内容${c.contentH}px${flag}`);
  });
  console.log(`\n需处理:${probs} / ${cards.length}\n`);
  process.exit(0);
})().catch(e => { console.error('ERR', e.message); chrome.kill(); process.exit(1); });
