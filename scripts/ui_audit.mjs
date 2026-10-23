/**
 * scripts/ui_audit.mjs
 * DecisionOS UI audit sweep — every route x 2 viewports x 2 locales.
 * Reports console errors, layout overflow, clipped text, bad values, a11y gaps.
 * Zero-dependency: Node 24 WebSocket + fetch + Chrome DevTools Protocol.
 *
 *   node scripts/ui_audit.mjs
 */
import { spawn } from 'node:child_process';
import { mkdtempSync, rmSync, writeFileSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';

const CHROME_PATH = process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const WEB_BASE_URL = process.env.WEB_BASE_URL || 'http://127.0.0.1:3000';
const CDP_PORT = Number(process.env.CDP_PORT || 9333);
const OUT_DIR = join(process.cwd(), 'var', 'ui_audit');
mkdirSync(OUT_DIR, { recursive: true });

class Cdp {
  constructor(wsUrl) { this.wsUrl = wsUrl; this.ws = null; this.id = 1; this.pending = new Map(); this.listeners = new Map(); }
  async connect() {
    this.ws = new WebSocket(this.wsUrl);
    await new Promise((res, rej) => { this.ws.onopen = res; this.ws.onerror = rej; });
    this.ws.onmessage = (ev) => {
      const m = JSON.parse(ev.data);
      if (m.id && this.pending.has(m.id)) {
        const { resolve, reject } = this.pending.get(m.id);
        this.pending.delete(m.id);
        m.error ? reject(new Error(JSON.stringify(m.error))) : resolve(m.result);
      } else if (m.method && this.listeners.has(m.method)) {
        for (const cb of this.listeners.get(m.method)) cb(m.params);
      }
    };
  }
  send(method, params = {}) {
    const id = this.id++;
    return new Promise((resolve, reject) => { this.pending.set(id, { resolve, reject }); this.ws.send(JSON.stringify({ id, method, params })); });
  }
  on(m, cb) { if (!this.listeners.has(m)) this.listeners.set(m, []); this.listeners.get(m).push(cb); }
  clear() { this.listeners.clear(); }
  close() { try { this.ws?.close(); } catch {} }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const ROUTES = [
  ['home', '/'],
  ['pilot', '/pilot'],
  ['pilot-setup', '/pilot/setup'],
  ['decisions', '/decisions'],
  ['risk', '/risk'],
  ['monitoring', '/monitoring'],
  ['investigations', '/investigations'],
  ['forecasts', '/forecasts'],
  ['workflow', '/workflow'],
  ['scenarios', '/scenarios'],
  ['datasets', '/datasets'],
  ['metrics', '/metrics'],
  ['uploads', '/uploads'],
];
const VIEWPORTS = [[1920, 1080], [1366, 768]];
const LOCALES = ['en', 'ar'];

// In-page probe: returns structural findings as JSON.
const PROBE = `(() => {
  const vw = window.innerWidth, vh = window.innerHeight;
  const out = {
    title: document.title,
    dir: document.documentElement.dir,
    lang: document.documentElement.lang,
    hScroll: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    bodyText: (document.body.innerText || '').slice(0, 400),
    textLen: (document.body.innerText || '').trim().length,
    nodes: document.querySelectorAll('*').length,
    overflowers: [],
    clipped: [],
    tinyText: [],
    badValues: [],
    brokenImages: [],
    unlabeledButtons: [],
    emptySections: [],
    duplicates: []
  };

  // elements sticking out horizontally
  for (const el of document.querySelectorAll('body *')) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    if (r.right > vw + 2 || r.left < -2) {
      out.overflowers.push({ tag: el.tagName, cls: (el.className || '').toString().slice(0, 60),
        right: Math.round(r.right), left: Math.round(r.left), text: (el.innerText || '').trim().slice(0, 40) });
    }
    // vertical clipping of text containers
    const cs = getComputedStyle(el);
    if ((cs.overflow === 'hidden' || cs.overflowY === 'hidden') && el.scrollHeight > el.clientHeight + 3 && el.clientHeight > 0) {
      if ((el.innerText || '').trim().length > 0) {
        out.clipped.push({ tag: el.tagName, cls: (el.className || '').toString().slice(0, 60),
          clip: el.scrollHeight - el.clientHeight, text: (el.innerText || '').trim().slice(0, 40) });
      }
    }
    const fs = parseFloat(cs.fontSize);
    if (fs && fs > 0 && fs < 11 && (el.innerText || '').trim().length > 2) {
      out.tinyText.push({ px: fs, text: (el.innerText || '').trim().slice(0, 40) });
    }
  }

  const txt = document.body.innerText || '';
  for (const bad of ['undefined', 'NaN', '[object Object]', 'null', 'Infinity', 'Invalid Date']) {
    if (txt.includes(bad)) out.badValues.push(bad);
  }

  for (const img of document.querySelectorAll('img')) {
    if (img.complete && img.naturalWidth === 0) out.brokenImages.push(img.getAttribute('src'));
  }

  for (const b of document.querySelectorAll('button, a[role=button]')) {
    const name = (b.innerText || b.getAttribute('aria-label') || b.getAttribute('title') || '').trim();
    if (!name) out.unlabeledButtons.push((b.className || '').toString().slice(0, 50));
  }

  // sections with a heading and literally nothing under it
  for (const sec of document.querySelectorAll('section, .card, [class*=panel]')) {
    const t = (sec.innerText || '').trim();
    if (t.length > 0 && t.length < 8 && sec.querySelectorAll('button, a, table, canvas, svg, input').length === 0) {
      out.emptySections.push({ cls: (sec.className || '').toString().slice(0, 50), text: t });
    }
  }

  // trim noisy arrays
  const cap = (a, n) => a.slice(0, n);
  out.overflowers = cap(out.overflowers, 6);
  out.clipped = cap(out.clipped, 6);
  out.tinyText = cap(out.tinyText, 5);
  out.emptySections = cap(out.emptySections, 5);
  out.unlabeledButtons = cap(out.unlabeledButtons, 5);
  out.overflowCount = out.overflowers.length;
  return JSON.stringify(out);
})()`;

async function run() {
  // preflight
  const webRes = await fetch(WEB_BASE_URL);
  if (!webRes.ok) throw new Error(`web not reachable: ${webRes.status}`);

  const profile = mkdtempSync(join(tmpdir(), 'dos-ui-audit-'));
  const chrome = spawn(CHROME_PATH, [
    '--headless=new', `--remote-debugging-port=${CDP_PORT}`, `--user-data-dir=${profile}`,
    '--no-first-run', '--no-default-browser-check', '--disable-extensions',
    '--hide-scrollbars', '--force-device-scale-factor=1', '--window-size=1920,1080', 'about:blank',
  ], { stdio: 'ignore' });

  const cleanup = () => { try { chrome.kill(); } catch {} try { rmSync(profile, { recursive: true, force: true }); } catch {} };
  process.on('exit', cleanup);

  let ver = null;
  for (let i = 0; i < 40; i++) {
    await sleep(200);
    try { const r = await fetch(`http://127.0.0.1:${CDP_PORT}/json/version`); if (r.ok) { ver = await r.json(); break; } } catch {}
  }
  if (!ver) throw new Error('Chrome CDP did not come up');

  const tabs = await (await fetch(`http://127.0.0.1:${CDP_PORT}/json/list`)).json();
  const page = tabs.find((t) => t.type === 'page');
  const cdp = new Cdp(page.webSocketDebuggerUrl);
  await cdp.connect();
  await cdp.send('Page.enable');
  await cdp.send('Runtime.enable');
  await cdp.send('Network.enable');
  await cdp.send('Log.enable');

  const results = [];

  for (const locale of LOCALES) {
    for (const [vw, vh] of VIEWPORTS) {
      await cdp.send('Emulation.setDeviceMetricsOverride', { width: vw, height: vh, deviceScaleFactor: 1, mobile: false });

      for (const [name, path] of ROUTES) {
        cdp.clear();
        const errors = [];
        const exceptions = [];
        const failedReqs = [];
        let loaded = false;

        cdp.on('Page.loadEventFired', () => { loaded = true; });
        cdp.on('Runtime.consoleAPICalled', (p) => {
          if (p.type === 'error') errors.push(p.args.map((a) => a.value ?? a.description ?? '').join(' ').slice(0, 300));
        });
        cdp.on('Runtime.exceptionThrown', (p) => {
          exceptions.push((p.exceptionDetails.exception?.description || p.exceptionDetails.text || '').split('\n')[0].slice(0, 300));
        });
        cdp.on('Network.loadingFailed', (p) => {
          if (!String(p.errorText || '').includes('ERR_ABORTED')) failedReqs.push(`${p.errorText} ${p.blockedReason || ''}`.trim());
        });

        // seed locale before app boots
        await cdp.send('Page.navigate', { url: `${WEB_BASE_URL}/` });
        await sleep(400);
        await cdp.send('Runtime.evaluate', { expression: `localStorage.setItem('decisionos_locale','${locale}')` });

        loaded = false;
        const url = `${WEB_BASE_URL}${path}`;
        await cdp.send('Page.navigate', { url });
        const t0 = Date.now();
        while (!loaded && Date.now() - t0 < 10000) await sleep(100);
        await sleep(1800); // hydration + API

        let probe = null;
        try {
          const r = await cdp.send('Runtime.evaluate', { expression: PROBE, returnByValue: true });
          probe = JSON.parse(r.result.value);
        } catch (e) {
          probe = { probeError: String(e).slice(0, 200) };
        }

        const shot = await cdp.send('Page.captureScreenshot', { format: 'png' });
        const file = join(OUT_DIR, `${name}_${locale}_${vw}x${vh}.png`);
        writeFileSync(file, Buffer.from(shot.data, 'base64'));

        const rec = { route: name, path, locale, vw, vh, errors, exceptions, failedReqs, probe, shot: file };
        results.push(rec);

        const flags = [];
        if (errors.length) flags.push(`${errors.length} consoleErr`);
        if (exceptions.length) flags.push(`${exceptions.length} exception`);
        if (probe?.hScroll > 0) flags.push(`hScroll+${probe.hScroll}`);
        if (probe?.overflowCount) flags.push(`${probe.overflowCount} overflow`);
        if (probe?.clipped?.length) flags.push(`${probe.clipped.length} clipped`);
        if (probe?.badValues?.length) flags.push(`bad:${probe.badValues.join(',')}`);
        if (probe?.brokenImages?.length) flags.push('brokenImg');
        if (probe?.textLen < 60) flags.push('near-empty');
        console.log(`${locale} ${vw}x${vh} ${path.padEnd(18)} ${flags.length ? '⚠ ' + flags.join(' | ') : 'ok'}`);
      }
    }
  }

  writeFileSync(join(OUT_DIR, 'audit.json'), JSON.stringify(results, null, 2));
  console.log(`\nWrote ${results.length} records -> ${join(OUT_DIR, 'audit.json')}`);
  cdp.close();
  cleanup();
  process.exit(0);
}

run().catch((e) => { console.error('AUDIT FAILED:', e); process.exit(1); });
