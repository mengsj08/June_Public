// build-longimage.js — turn an interactive article-viz page into a static "long image" source.
//
// Usage:  node scripts/build-longimage.js <caseDir>
//   <caseDir> must contain index.html  ->  writes <caseDir>/longimage.html
//
// Content-agnostic: it injects an override <style> + a finalize <script> that, at load time,
//   - forces every .reveal block visible (no scroll needed for a static shot)
//   - fills every .fill[data-w] bar to its final width
//   - sets every .num[data-to] counter to its final value
//   - EXPANDS every tab .panel and labels it from its controlling .tab (.k + .h),
//     so all tabbed abilities show stacked in one image — no per-article surgery.
const fs = require('fs');
const path = require('path');

const caseDir = path.resolve(process.argv[2] || '.');
const src = path.join(caseDir, 'index.html');
const out = path.join(caseDir, 'longimage.html');
if (!fs.existsSync(src)) { console.error('missing', src); process.exit(1); }
let html = fs.readFileSync(src, 'utf8');

const overrideCss = `
<style id="longimg-override">
  html{scroll-behavior:auto}
  nav{display:none !important}
  .reveal{opacity:1 !important;transform:none !important}
  .fill{transition:none !important}
  .tab{cursor:default}
  .panel{display:block !important;border:1px solid var(--line) !important;border-radius:18px !important;
    margin-top:14px;box-shadow:var(--shadow)}
  .panel-head{font-size:19px;font-weight:850;color:var(--ink);margin:-4px 0 18px;
    padding-bottom:14px;border-bottom:1px dashed var(--line);display:flex;align-items:center;gap:12px}
  .panel-head .pk{font-size:12px;font-weight:800;letter-spacing:1px;text-transform:uppercase;
    color:#fff;background:var(--clay);padding:5px 12px;border-radius:999px;flex:0 0 auto}
  .tabs{margin-bottom:4px}
  .tab,.tab.on{border-radius:14px !important;border-bottom:1px solid var(--line) !important}
  section{padding:64px 0}
  @keyframes fade{from{opacity:1}to{opacity:1}}
</style>`;
html = html.replace('</head>', overrideCss + '\n</head>');

const finalizeJs = `
<script>
  document.querySelectorAll('.reveal').forEach(e=>e.classList.add('show'));
  document.querySelectorAll('.fill[data-w]').forEach(f=>{f.style.width=f.dataset.w+'%';});
  document.querySelectorAll('.num[data-to]').forEach(el=>{
    el.textContent=(el.dataset.prefix||'')+el.dataset.to+(el.dataset.suffix||'');
  });
  document.querySelectorAll('.panel').forEach(p=>{
    if(p.querySelector('.panel-head')) return;
    var key=p.id.replace(/^panel-/,'');
    var tab=document.querySelector('.tab[data-tab="'+key+'"]');
    if(!tab) return;
    var k=tab.querySelector('.k'), h=tab.querySelector('.h');
    var head=document.createElement('div'); head.className='panel-head';
    head.innerHTML=(k?'<span class="pk">'+k.textContent+'</span>':'')+(h?h.textContent:'');
    p.insertBefore(head, p.firstChild);
  });
  window.__ready=true;
</script>`;
html = html.replace('</body>', finalizeJs + '\n</body>');

fs.writeFileSync(out, html);
console.log('wrote', out);
