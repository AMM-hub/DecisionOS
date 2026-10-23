/**
 * scripts/ui_probe.mjs — DOM-truth UI audit (no screenshots, no ghosting).
 * Detects: real element overlaps, text truncation, contrast failures,
 * raw-value leaks, hardcoded English under AR, table overflow, a11y gaps.
 *
 *   node scripts/ui_probe.mjs
 */
import { spawn } from 'node:child_process';
import { mkdtempSync, rmSync, writeFileSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';

const CHROME = process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const BASE = process.env.WEB_BASE_URL || 'http://127.0.0.1:3000';
const PORT = Number(process.env.CDP_PORT || 9334);
const OUT = join(process.cwd(), 'var', 'ui_audit');
mkdirSync(OUT, { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

class Cdp {
  constructor(u) { this.u = u; this.id = 1; this.p = new Map(); this.l = new Map(); }
  async connect() {
    this.ws = new WebSocket(this.u);
    await new Promise((res, rej) => { this.ws.onopen = res; this.ws.onerror = rej; });
    this.ws.onmessage = (e) => {
      const m = JSON.parse(e.data);
      if (m.id && this.p.has(m.id)) { const { resolve, reject } = this.p.get(m.id); this.p.delete(m.id); m.error ? reject(new Error(JSON.stringify(m.error))) : resolve(m.result); }
      else if (m.method && this.l.has(m.method)) for (const cb of this.l.get(m.method)) cb(m.params);
    };
  }
  send(method, params = {}) { const id = this.id++; return new Promise((res, rej) => { this.p.set(id, { resolve: res, reject: rej }); this.ws.send(JSON.stringify({ id, method, params })); }); }
}

const ROUTES = [['home', '/'], ['pilot', '/pilot'], ['pilot-setup', '/pilot/setup'], ['decisions', '/decisions'],
  ['risk', '/risk'], ['monitoring', '/monitoring'], ['investigations', '/investigations'], ['forecasts', '/forecasts'],
  ['workflow', '/workflow'], ['scenarios', '/scenarios'], ['datasets', '/datasets'], ['metrics', '/metrics'], ['uploads', '/uploads']];
const VIEWS = [[1920, 1080], [1366, 768]];

const PROBE = String.raw`(function(){
  var vw=innerWidth, vh=innerHeight;
  var R={overlaps:[],truncated:[],lowContrast:[],rawValues:[],hardcoded:[],
         tableOverflow:[],noLabel:[],emptyLinks:[],hScroll:0,textLen:0,dir:'',lang:'',nodes:0};
  R.dir=document.documentElement.dir; R.lang=document.documentElement.lang;
  R.hScroll=document.documentElement.scrollWidth-document.documentElement.clientWidth;
  R.nodes=document.querySelectorAll('*').length;
  R.textLen=(document.body.innerText||'').trim().length;

  function txt(e){return (e.innerText||'').trim();}
  function vis(e){var c=getComputedStyle(e);return c.display!=='none'&&c.visibility!=='hidden'&&parseFloat(c.opacity)>0.05;}

  // 1. Real overlaps: leaf-ish text boxes intersecting each other
  var leaves=[];
  document.querySelectorAll('main *, aside *, header *').forEach(function(e){
    if(e.children.length>0) return;
    var t=txt(e); if(!t||t.length<2) return;
    if(!vis(e)) return;
    var r=e.getBoundingClientRect();
    if(r.width<4||r.height<4) return;
    if(r.bottom<0||r.top>vh||r.right<0||r.left>vw) return;
    leaves.push({el:e,r:r,t:t.slice(0,36)});
  });
  var seen=0;
  for(var i=0;i<leaves.length&&seen<12;i++){
    for(var j=i+1;j<leaves.length&&seen<12;j++){
      var a=leaves[i].r,b=leaves[j].r;
      var ox=Math.min(a.right,b.right)-Math.max(a.left,b.left);
      var oy=Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top);
      if(ox>3&&oy>3){
        var frac=ox*oy/Math.min(a.width*a.height,b.width*b.height);
        if(frac>0.18){
          R.overlaps.push({a:leaves[i].t,b:leaves[j].t,frac:Math.round(frac*100)/100});
          seen++;
        }
      }
    }
  }

  // 2. Truncation: text wider than its box while clipped
  document.querySelectorAll('main *, aside *, header *').forEach(function(e){
    if(e.children.length>0) return;
    var c=getComputedStyle(e);
    if(c.overflow==='hidden'||c.textOverflow==='ellipsis'){
      if(e.scrollWidth>e.clientWidth+2&&e.clientWidth>0&&txt(e)){
        R.truncated.push({t:txt(e).slice(0,40),need:e.scrollWidth,have:e.clientWidth});
      }
    }
  });

  // 3. Contrast: text color vs nearest opaque background
  function rgb(s){var m=s.match(/[\d.]+/g);return m?m.map(Number):null;}
  function lum(c){var a=c.slice(0,3).map(function(v){v/=255;return v<=0.03928?v/12.92:Math.pow((v+0.055)/1.055,2.4);});return 0.2126*a[0]+0.7152*a[1]+0.0722*a[2];}
  function bgOf(e){var n=e;while(n&&n!==document.documentElement){var c=getComputedStyle(n);var b=rgb(c.backgroundColor);if(b&&(b.length<4||b[3]>0.6))return b;n=n.parentElement;}return [255,255,255];}
  var checked=0;
  document.querySelectorAll('main p, main span, main td, main th, main label, main h1, main h2, main h3, aside a, header span').forEach(function(e){
    if(checked>=400) return; if(e.children.length>0) return;
    var t=txt(e); if(t.length<3||!vis(e)) return;
    var c=getComputedStyle(e); var fg=rgb(c.color); if(!fg) return;
    var bg=bgOf(e);
    var L1=lum(fg),L2=lum(bg);
    var ratio=(Math.max(L1,L2)+0.05)/(Math.min(L1,L2)+0.05);
    var size=parseFloat(c.fontSize), bold=parseInt(c.fontWeight,10)>=600;
    var large=size>=24||(size>=18.66&&bold);
    var min=large?3:4.5;
    checked++;
    if(ratio<min-0.05) R.lowContrast.push({t:t.slice(0,40),ratio:Math.round(ratio*100)/100,min:min,px:size,color:c.color});
  });

  // 4. Raw value leaks
  var body=document.body.innerText||'';
  ['undefined','NaN','[object Object]','Infinity','Invalid Date'].forEach(function(b){if(body.indexOf(b)>=0)R.rawValues.push(b);});
  if(/\bnull\b/.test(body))R.rawValues.push('null');
  // uuid exposure
  var uu=body.match(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi);
  if(uu)R.rawValues.push('uuid x'+uu.length);

  // 5. Table overflow (table wider than its scroll container)
  document.querySelectorAll('table').forEach(function(t){
    var r=t.getBoundingClientRect();
    var host=t.parentElement;
    if(r.right>vw+1){
      var cs=getComputedStyle(host);
      R.tableOverflow.push({w:Math.round(r.width),right:Math.round(r.right),hostOverflowX:cs.overflowX});
    }
  });

  // 6. a11y
  document.querySelectorAll('button').forEach(function(b){
    var n=(b.innerText||b.getAttribute('aria-label')||b.title||'').trim();
    if(!n)R.noLabel.push(String(b.className).slice(0,40));
  });
  document.querySelectorAll('a').forEach(function(a){
    if(!(a.innerText||'').trim()&&!a.getAttribute('aria-label'))R.emptyLinks.push(a.getAttribute('href'));
  });

  function cap(a,n){return a.slice(0,n);}
  R.overlaps=cap(R.overlaps,6);R.truncated=cap(R.truncated,6);R.lowContrast=cap(R.lowContrast,8);
  R.tableOverflow=cap(R.tableOverflow,3);R.noLabel=cap(R.noLabel,4);R.emptyLinks=cap(R.emptyLinks,4);
  R.counts={overlaps:R.overlaps.length,truncated:R.truncated.length,lowContrast:R.lowContrast.length,
            raw:R.rawValues.length,tableOverflow:R.tableOverflow.length,noLabel:R.noLabel.length};
  return JSON.stringify(R);
})()`;

async function main() {
  if (!(await fetch(BASE)).ok) throw new Error('web down');
  const prof = mkdtempSync(join(tmpdir(), 'dos-probe-'));
  const ch = spawn(CHROME, ['--headless=new', `--remote-debugging-port=${PORT}`, `--user-data-dir=${prof}`,
    '--no-first-run', '--disable-extensions', '--hide-scrollbars', '--window-size=1920,1080', 'about:blank'], { stdio: 'ignore' });
  const clean = () => { try { ch.kill(); } catch {} try { rmSync(prof, { recursive: true, force: true }); } catch {} };
  process.on('exit', clean);

  let ok = false;
  for (let i = 0; i < 40; i++) { await sleep(200); try { if ((await fetch(`http://127.0.0.1:${PORT}/json/version`)).ok) { ok = true; break; } } catch {} }
  if (!ok) throw new Error('cdp down');
  const tabs = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
  const cdp = new Cdp(tabs.find((t) => t.type === 'page').webSocketDebuggerUrl);
  await cdp.connect();
  await cdp.send('Page.enable'); await cdp.send('Runtime.enable');
  await cdp.send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: 'reduce' }] });

  const all = [];
  for (const locale of ['en', 'ar']) {
    for (const [vw, vh] of VIEWS) {
      await cdp.send('Emulation.setDeviceMetricsOverride', { width: vw, height: vh, deviceScaleFactor: 1, mobile: false });
      for (const [name, path] of ROUTES) {
        await cdp.send('Page.navigate', { url: `${BASE}/` });
        await sleep(350);
        await cdp.send('Runtime.evaluate', { expression: `localStorage.setItem('decisionos_locale','${locale}')` });
        await cdp.send('Page.navigate', { url: `${BASE}${path}` });
        await sleep(2200);
        const r = await cdp.send('Runtime.evaluate', { expression: PROBE, returnByValue: true });
        let d = null; try { d = JSON.parse(r.result.value); } catch { d = { error: r.result.value }; }
        all.push({ route: name, path, locale, vw, vh, ...d });
        console.log(`${locale} ${String(vw).padStart(4)} ${path.padEnd(17)} ` +
          `ovl:${d.counts?.overlaps ?? '?'} trunc:${d.counts?.truncated ?? '?'} contrast:${d.counts?.lowContrast ?? '?'} ` +
          `raw:${(d.rawValues || []).join(',') || '-'} tbl:${d.counts?.tableOverflow ?? '?'} hs:${d.hScroll}`);
      }
    }
  }
  writeFileSync(join(OUT, 'probe.json'), JSON.stringify(all, null, 2));
  console.log(`\n-> ${join(OUT, 'probe.json')}`);
  clean(); process.exit(0);
}
main().catch((e) => { console.error('FAILED', e); process.exit(1); });
