/**
 * scripts/test_browser_auth_boundary_cdp.mjs
 * Adversarial test: Intercept backend API with HTTP 401 Unauthorized
 * Assert that Nuxt frontend handles 401 gracefully via UI error-banner with zero unhandled exceptions.
 */
import { spawn } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';

const CHROME_PATH = process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const WEB_BASE_URL = 'http://localhost:3000';
const CDP_PORT = 9224;

class CdpConnection {
  constructor(wsUrl) {
    this.wsUrl = wsUrl;
    this.ws = null;
    this.id = 1;
    this.pending = new Map();
    this.listeners = new Map();
  }

  async connect() {
    this.ws = new WebSocket(this.wsUrl);
    await new Promise((resolve, reject) => {
      this.ws.onopen = resolve;
      this.ws.onerror = reject;
    });
    this.ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        if (msg.error) reject(msg.error);
        else resolve(msg.result);
      } else if (msg.method && this.listeners.has(msg.method)) {
        for (const cb of this.listeners.get(msg.method)) {
          cb(msg.params);
        }
      }
    };
  }

  send(method, params = {}) {
    const curId = this.id++;
    return new Promise((resolve, reject) => {
      this.pending.set(curId, { resolve, reject });
      this.ws.send(JSON.stringify({ id: curId, method, params }));
    });
  }

  on(method, callback) {
    if (!this.listeners.has(method)) this.listeners.set(method, []);
    this.listeners.get(method).push(callback);
  }

  close() {
    if (this.ws) this.ws.close();
  }
}

async function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function run() {
  const tempProfile = mkdtempSync(join(tmpdir(), 'decisionos-auth-adv-'));
  const chromeProc = spawn(CHROME_PATH, [
    '--headless=new',
    `--remote-debugging-port=${CDP_PORT}`,
    `--user-data-dir=${tempProfile}`,
    '--no-first-run',
    '--no-default-browser-check',
    'about:blank',
  ], { stdio: 'ignore' });

  const cleanup = () => {
    try { chromeProc.kill(); } catch {}
    try { rmSync(tempProfile, { recursive: true, force: true }); } catch {}
  };
  process.on('exit', cleanup);

  for (let i = 0; i < 30; i++) {
    await sleep(200);
    try {
      const res = await fetch(`http://localhost:${CDP_PORT}/json/version`);
      if (res.ok) break;
    } catch {}
  }

  const tabsRes = await fetch(`http://localhost:${CDP_PORT}/json/list`);
  const tabs = await tabsRes.json();
  const pageTab = tabs.find((t) => t.type === 'page');
  const cdp = new CdpConnection(pageTab.webSocketDebuggerUrl);
  await cdp.connect();

  await cdp.send('Page.enable');
  await cdp.send('Runtime.enable');
  await cdp.send('Fetch.enable', {
    patterns: [{ urlPattern: '*:8100/v1/decisions*', requestStage: 'Request' }]
  });

  const unhandledExceptions = [];
  const consoleErrors = [];

  cdp.on('Runtime.exceptionThrown', (p) => {
    unhandledExceptions.push(p.exceptionDetails.text);
  });
  cdp.on('Runtime.consoleAPICalled', (p) => {
    if (p.type === 'error') consoleErrors.push(p.args.map(a => a.value ?? a.description ?? '').join(' '));
  });

  // Intercept /decisions API request and fulfill with 401 Unauthorized
  cdp.on('Fetch.requestPaused', async (params) => {
    if (params.request.method === 'OPTIONS') {
      await cdp.send('Fetch.fulfillRequest', {
        requestId: params.requestId,
        responseCode: 204,
        responseHeaders: [
          { name: 'Access-Control-Allow-Origin', value: 'http://localhost:3000' },
          { name: 'Access-Control-Allow-Credentials', value: 'true' },
          { name: 'Access-Control-Allow-Methods', value: 'GET, POST, OPTIONS' },
          { name: 'Access-Control-Allow-Headers', value: 'Content-Type, X-Tenant, X-User, Idempotency-Key' },
        ],
      });
      return;
    }
    await cdp.send('Fetch.fulfillRequest', {
      requestId: params.requestId,
      responseCode: 401,
      responseHeaders: [
        { name: 'Content-Type', value: 'application/json' },
        { name: 'Access-Control-Allow-Origin', value: 'http://localhost:3000' },
        { name: 'Access-Control-Allow-Credentials', value: 'true' },
        { name: 'Access-Control-Allow-Methods', value: 'GET, POST, OPTIONS' },
        { name: 'Access-Control-Allow-Headers', value: 'Content-Type, X-Tenant, X-User, Idempotency-Key' },
      ],
      body: Buffer.from(JSON.stringify({ detail: 'demo authentication missing' })).toString('base64'),
    });
  });

  console.log('[Auth Challenge] Navigating to http://localhost:3000/decisions with API mocking HTTP 401...');
  await cdp.send('Page.navigate', { url: `${WEB_BASE_URL}/decisions` });

  await sleep(1500);

  const evalRes = await cdp.send('Runtime.evaluate', {
    expression: `JSON.stringify({
      hasErrorBanner: document.querySelector('.error-banner') !== null,
      errorBannerText: document.querySelector('.error-banner')?.innerText || '',
      bodyText: document.body.innerText.slice(0, 300)
    })`
  });
  const result = JSON.parse(evalRes.result?.value || '{}');

  console.log('[Auth Challenge] Result:', JSON.stringify(result, null, 2));
  console.log('[Auth Challenge] Unhandled Exceptions:', unhandledExceptions.length);
  console.log('[Auth Challenge] Console Errors:', consoleErrors.length);

  cdp.close();
  cleanup();

  const success = result.hasErrorBanner &&
                  result.errorBannerText.includes('Demo authentication missing') &&
                  unhandledExceptions.length === 0;

  if (success) {
    console.log('[SUCCESS] Frontend correctly intercepted 401 and displayed friendly error banner without crashing!');
    process.exit(0);
  } else {
    console.error('[FAILURE] Frontend failed to gracefully handle 401 Unauthorized.');
    process.exit(1);
  }
}

run().catch((e) => {
  console.error(e);
  process.exit(1);
});
