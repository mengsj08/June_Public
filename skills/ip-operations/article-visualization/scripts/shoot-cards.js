// shoot-cards.js — screenshot individual fixed-size elements (covers, square cards, etc.)
// from an HTML file. Every element with class "shot" and a data-name is exported at 2×
// to <outDir>/<data-name>.png. The element's own CSS sets its exact px size.
//
// Usage:  node scripts/shoot-cards.js <htmlFile> [outDir]
//   outDir defaults to the html file's directory.
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const htmlFile = path.resolve(process.argv[2]);
const outDir = path.resolve(process.argv[3] || path.dirname(htmlFile));
const URL = 'file://' + htmlFile;
const PORT = 9377;
const SCALE = 2;

const sleep = ms => new Promise(r => setTimeout(r, ms));
const guard = setTimeout(() => { console.error('TIMEOUT'); process.exit(2); }, 60000);
if (!fs.existsSync(htmlFile)) { console.error('missing', htmlFile); process.exit(1); }
fs.mkdirSync(outDir, { recursive: true });

const chrome = spawn(CHROME, [
  '--headless=new', '--disable-gpu', '--hide-scrollbars', '--no-first-run',
  '--no-default-browser-check', '--disable-extensions',
  `--remote-debugging-port=${PORT}`, '--window-size=2200,1400', 'about:blank'
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
  const onload = new Promise(res => { ws.__onload = res; });
  await send(ws, 'Page.navigate', { url: URL });
  await onload;
  await sleep(700);

  // pages that build cards asynchronously (build-xhs) signal __cardsReady; retry until present
  const probe = `Array.from(document.querySelectorAll('.shot[data-name]')).map(e => {
      const r = e.getBoundingClientRect();
      return { name: e.getAttribute('data-name'),
        x: r.left + window.scrollX, y: r.top + window.scrollY,
        w: Math.round(r.width), h: Math.round(r.height) };
    })`;
  let shots = [];
  for (let i = 0; i < 8; i++) {
    shots = (await send(ws, 'Runtime.evaluate', { returnByValue: true, expression: probe })).result.value || [];
    const ready = (await send(ws, 'Runtime.evaluate', { returnByValue: true, expression: 'window.__cardsReady!==false' })).result.value;
    if (shots.length && ready) break;
    await sleep(400);
  }
  if (!shots.length) { console.error('no .shot[data-name] elements found'); }
  console.log(`${shots.length} cards from ${path.basename(htmlFile)}`);

  for (const s of shots) {
    const { data } = await send(ws, 'Page.captureScreenshot', {
      format: 'png', captureBeyondViewport: true,
      clip: { x: s.x, y: s.y, width: s.w, height: s.h, scale: SCALE }
    });
    const f = path.join(outDir, `${s.name}.png`);
    fs.writeFileSync(f, Buffer.from(data, 'base64'));
    console.log(`  ${s.name}.png  ${s.w * SCALE}x${s.h * SCALE}px`);
  }

  clearTimeout(guard);
  ws.close(); chrome.kill(); process.exit(0);
})().catch(e => { console.error('ERR', e.message); chrome.kill(); process.exit(1); });
