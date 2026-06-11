// build-xhs.js — turn the long-image page into FIXED 1080×1440 (3:4) 小红书 cards.
// Writes <caseDir>/xhs.html. When loaded at any width, an injected script repacks the
// top-level blocks into fixed cards: content vertically centered, background matched,
// and any single section taller than one card scaled down to fit exactly one card.
// Then screenshot with: node scripts/shoot-cards.js <caseDir>/xhs.html <caseDir>/xhs
const fs = require('fs');
const path = require('path');

const caseDir = path.resolve(process.argv[2] || '.');
const src = path.join(caseDir, 'longimage.html');
const out = path.join(caseDir, 'xhs.html');
if (!fs.existsSync(src)) { console.error('missing', src, '(run build-longimage.js first)'); process.exit(1); }
let html = fs.readFileSync(src, 'utf8');

const CARD_W = 1080, CARD_H = 1440;

const script = `
<script>
(function(){
  var CARD_W=${CARD_W}, CARD_H=${CARD_H};
  function bgOf(el){ var c=getComputedStyle(el).backgroundColor;
    return (c && c!=='rgba(0, 0, 0, 0)' && c!=='transparent') ? c : getComputedStyle(document.body).backgroundColor; }
  function build(){
    var body=document.body;
    // 1) collect top-level blocks and reflow them at a fixed 1080 width (viewport-independent)
    var root=document.createElement('div');
    root.style.cssText='width:'+CARD_W+'px;margin:0 auto;';
    var blocks=[].slice.call(body.children).filter(function(e){
      return e.matches('header.hero, section, footer');
    });
    blocks.forEach(function(b){ root.appendChild(b); });
    body.appendChild(root);
    var measured=blocks.map(function(b){ return { el:b, h:Math.round(b.getBoundingClientRect().height) }; });
    // 2) greedily group blocks into cards <= CARD_H (an oversized block gets its own card)
    var groups=[], cur=[], used=0;
    measured.forEach(function(m){
      if(m.h>CARD_H){ if(cur.length){groups.push(cur);cur=[];used=0;} groups.push([m]); return; }
      if(used>0 && used+m.h>CARD_H){ groups.push(cur); cur=[]; used=0; }
      cur.push(m); used+=m.h;
    });
    if(cur.length) groups.push(cur);
    // 3) build fixed cards
    var cards=document.createElement('div');
    groups.forEach(function(g,i){
      var n=(i+1<10?'0':'')+(i+1);
      var oversized=g.length===1 && g[0].h>CARD_H;
      var card=document.createElement('div');
      card.className='shot xhs-card';
      card.setAttribute('data-name','xhs-'+n);
      card.style.cssText='position:relative;width:'+CARD_W+'px;height:'+CARD_H+'px;overflow:hidden;'
        +'display:flex;flex-direction:column;justify-content:'+(oversized?'flex-start':'center')+';'
        +'margin:0 auto 30px;background:'+bgOf(g[0].el)+';';
      var inner=document.createElement('div');
      inner.style.width=CARD_W+'px';
      g.forEach(function(m){ inner.appendChild(m.el); });
      card.appendChild(inner);
      cards.appendChild(card);
      card._inner=inner;
    });
    root.remove();
    body.appendChild(cards);
    // 4) scale any oversized inner to fit exactly one card (counter-scale width to keep full bleed)
    [].slice.call(cards.children).forEach(function(card){
      var inner=card._inner, ih=inner.getBoundingClientRect().height;
      if(ih>CARD_H){
        var s=CARD_H/ih;
        inner.style.transformOrigin='top center';
        inner.style.width=(CARD_W/s)+'px';
        inner.style.marginLeft='auto'; inner.style.marginRight='auto';
        inner.style.transform='scale('+s+')';
      }
    });
    window.__cardsReady=true;
  }
  if(document.fonts && document.fonts.ready){ document.fonts.ready.then(function(){ setTimeout(build,120); }); }
  else { window.addEventListener('load', function(){ setTimeout(build,150); }); }
})();
</script>`;

html = html.replace('</body>', script + '\n</body>');
fs.writeFileSync(out, html);
console.log('wrote', out, `(fixed ${CARD_W}×${CARD_H} cards)`);
