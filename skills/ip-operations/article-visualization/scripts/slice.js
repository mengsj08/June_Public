// slice.js — cut a long-image page into platform-sized pages, breaking only at natural
// block boundaries (never mid-content). Reuses the CDP pipeline; each page is cropped
// straight from Chrome at the requested render width.
//
// Usage:  node scripts/slice.js <caseDir> [--width 1140] [--target 1700] [--out pages]
//   --width   render (viewport) width in CSS px. 1080 for Rednote/小红书, 1140 for the deck.
//   --target  aim for pages around this tall in CSS px (a single block taller becomes its own page).
//   --out     output subfolder + filename stem under <caseDir>.  e.g. --out xhs → <caseDir>/xhs/xhs-01.png
//
// Examples:
//   node scripts/slice.js <case>                              # deck pages: 1140 wide, ~1700 tall → pages/page-NN.png
//   node scripts/slice.js <case> --width 1080 --target 1440 --out xhs   # 小红书 3:4 cards → xhs/xhs-NN.png
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

function arg(name, def) { const i = process.argv.indexOf('--' + name); return i > -1 ? process.argv[i + 1] : def; }

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const caseDir = path.resolve(process.argv[2] || '.');
const WIDTH = Number(arg('width', 1140));
const TARGET = Number(arg('target', 1700));
const OUT = arg('out', 'pages');
const input = path.join(caseDir, 'longimage.html');
const outDir = path.join(caseDir, OUT);
const URL = 'file://' + input;
const PORT = 9366;
const SCALE = 2;

const sleep = ms => new Promise(r => setTimeout(r, ms));
const guard = setTimeout(() => { console.error('TIMEOUT'); process.exit(2); }, 90000);

if (!fs.existsSync(input)) { console.error('missing', input, '(run build-longimage.js first)'); process.exit(1); }
fs.mkdirSync(outDir, { recursive: true });

const chrome = spawn(CHROME, [
  '--headless=new', '--disable-gpu', '--hide-scrollbars', '--no-first-run',
  '--no-default-browser-check', '--disable-extensions',
  `--remote-debugging-port=${PORT}`, `--window-size=${WIDTH},1400`, 'about:blank'
], { stdio: 'ignore' });

let id = 0;
const pending = new Map();
function attach(ws) {
  ws.addEventListener('message', ev => {
    const m = JSON.parse(typeof ev.data === 'string' ? ev.data : ev.data.toString());
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m.result); pending.delete(m.id); }
    if (m.method === 'Page.loadEventFired' && ws.__onload) ws.__onload();
  });
}
function send(ws, method, params = {}) {
  return new Promise(res => { const mid = ++id; pending.set(mid, res);
    ws.send(JSON.stringify({ id: mid, method, params })); });
}

(async () => {
  let wsUrl;
  for (let i = 0; i < 60; i++) {
    try {
      const targets = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
      const page = targets.find(t => t.type === 'page');
      if (page?.webSocketDebuggerUrl) { wsUrl = page.webSocketDebuggerUrl; break; }
    } catch {}
    await sleep(150);
  }
  if (!wsUrl) throw new Error('no page target');

  const ws = new WebSocket(wsUrl);
  await new Promise(res => ws.addEventListener('open', res, { once: true }));
  attach(ws);
  await send(ws, 'Page.enable');
  await send(ws, 'Runtime.enable');
  // force the layout width so block heights match the export width
  await send(ws, 'Emulation.setDeviceMetricsOverride', { width: WIDTH, height: 1400, deviceScaleFactor: 1, mobile: false });
  const onload = new Promise(res => { ws.__onload = res; });
  await send(ws, 'Page.navigate', { url: URL });
  await onload;
  await sleep(800);

  const lm = await send(ws, 'Page.getLayoutMetrics');
  const size = lm.cssContentSize || lm.contentSize;
  const width = Math.ceil(size.width);
  const totalH = Math.ceil(size.height);

  // candidate cut lines: top-level blocks + one level of major children (so a tall
  // section can break between its components rather than overflowing a card).
  const ev = await send(ws, 'Runtime.evaluate', {
    returnByValue: true,
    expression: `(() => {
      const sel = 'header.hero, section, footer, .bgroup, .grid2, .grid3, .tl, .repbar, .ranks, .mirror, .limit, .cta, .tabs, .panel';
      const tops = [];
      document.querySelectorAll(sel).forEach(e => {
        if (e.tagName !== 'HEADER' && e.offsetParent === null) return;
        tops.push(Math.round(e.getBoundingClientRect().top + window.scrollY));
      });
      return Array.from(new Set(tops)).sort((a,b)=>a-b);
    })()`
  });
  let B = (ev.result.value || []).filter(t => t >= 0);
  if (B[0] !== 0) B.unshift(0);
  B.push(totalH);
  B = Array.from(new Set(B)).sort((a, b) => a - b);

  // greedy pack boundaries into pages near TARGET
  const pages = [];
  let a = 0;
  while (a < B.length - 1) {
    let b = a + 1;
    while (b + 1 < B.length && B[b + 1] - B[a] <= TARGET) b++;
    pages.push([B[a], B[b]]);
    a = b;
  }
  console.log(`${OUT}: ${width}x${totalH} css @${WIDTH}w → ${pages.length} pages (target ${TARGET})`);

  const pad = n => String(n).padStart(2, '0');
  for (let i = 0; i < pages.length; i++) {
    const [y0, y1] = pages[i];
    const { data } = await send(ws, 'Page.captureScreenshot', {
      format: 'png', captureBeyondViewport: true,
      clip: { x: 0, y: y0, width, height: y1 - y0, scale: SCALE }
    });
    const f = path.join(outDir, `${OUT}-${pad(i + 1)}.png`);
    fs.writeFileSync(f, Buffer.from(data, 'base64'));
    console.log(`  ${OUT}-${pad(i + 1)}.png  ${width * SCALE}x${(y1 - y0) * SCALE}px  (css y ${y0}–${y1})`);
  }

  clearTimeout(guard);
  ws.close(); chrome.kill(); process.exit(0);
})().catch(e => { console.error('ERR', e.message); chrome.kill(); process.exit(1); });
