// shoot.js — full-page screenshot of a long-image HTML via Chrome DevTools Protocol.
// No npm deps; uses Node globals (WebSocket/fetch, Node >= 21) and the system Chrome.
//
// Usage:  node scripts/shoot.js <caseDir> [inputHtml] [outPng]
//   defaults: inputHtml = <caseDir>/longimage.html
//             outPng    = <caseDir>/<caseDirName>-longimage.png
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const caseDir = path.resolve(process.argv[2] || '.');
const input = path.resolve(caseDir, process.argv[3] || 'longimage.html');
const out = path.resolve(caseDir, process.argv[4] || (path.basename(caseDir) + '-longimage.png'));
const URL = 'file://' + input;
const PORT = 9355;
const SCALE = 2;     // retina crispness
const WIDTH = 1140;  // css px

const log = (...a) => console.log(...a);
const sleep = ms => new Promise(r => setTimeout(r, ms));
const guard = setTimeout(() => { console.error('TIMEOUT'); process.exit(2); }, 60000);

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
  const onload = new Promise(res => { ws.__onload = res; });
  await send(ws, 'Page.navigate', { url: URL });
  await onload;
  await sleep(800); // fonts/layout settle

  const lm = await send(ws, 'Page.getLayoutMetrics');
  const size = lm.cssContentSize || lm.contentSize;
  const width = Math.ceil(size.width);
  const height = Math.ceil(size.height);
  log('content size', width, 'x', height);

  const { data } = await send(ws, 'Page.captureScreenshot', {
    format: 'png', captureBeyondViewport: true,
    clip: { x: 0, y: 0, width, height, scale: SCALE }
  });
  fs.writeFileSync(out, Buffer.from(data, 'base64'));
  log('wrote', out, '(' + width * SCALE + ' x ' + height * SCALE + ' px)');

  clearTimeout(guard);
  ws.close(); chrome.kill(); process.exit(0);
})().catch(e => { console.error('ERR', e.message); chrome.kill(); process.exit(1); });
