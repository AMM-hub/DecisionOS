/**
 * scripts/verify_empty_states_cdp.mjs
 * DecisionOS PILOT-01 Milestone 1: Empty-State Verification Runner
 * Zero-dependency: Uses Node 24 native WebSocket + fetch + Chrome DevTools Protocol
 */
import { spawn } from 'node:child_process';
import { mkdtempSync, rmSync, writeFileSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';

const CHROME_PATH = process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const WEB_BASE_URL = process.env.WEB_BASE_URL || 'http://localhost:3000';
const API_BASE_URL = process.env.API_BASE_URL || 'http://localhost:8100';
const CDP_PORT = 9222;
const ARTIFACTS_DIR = join(process.cwd(), 'var', 'qa_artifacts');

mkdirSync(ARTIFACTS_DIR, { recursive: true });

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

  clearListeners() {
    this.listeners.clear();
  }

  close() {
    if (this.ws) this.ws.close();
  }
}

async function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function pollHealth() {
  console.log(`[Pre-flight] Checking API health at ${API_BASE_URL}/v1/health...`);
  const apiRes = await fetch(`${API_BASE_URL}/v1/health`);
  if (!apiRes.ok) throw new Error(`API health check failed: HTTP ${apiRes.status}`);

  console.log(`[Pre-flight] Checking Web frontend at ${WEB_BASE_URL}...`);
  const webRes = await fetch(WEB_BASE_URL);
  if (!webRes.ok) throw new Error(`Web frontend health check failed: HTTP ${webRes.status}`);
  console.log('[Pre-flight] Both backend and frontend services are healthy.');
}

async function run() {
  await pollHealth();

  const tempProfile = mkdtempSync(join(tmpdir(), 'decisionos-qa-'));
  console.log(`[Chrome] Launching Headless Chrome with profile: ${tempProfile}`);

  const chromeProc = spawn(CHROME_PATH, [
    '--headless=new',
    `--remote-debugging-port=${CDP_PORT}`,
    `--user-data-dir=${tempProfile}`,
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-background-networking',
    '--disable-extensions',
    '--window-size=1920,1080',
    'about:blank',
  ], { stdio: 'ignore' });

  let cleanedUp = false;
  const cleanup = () => {
    if (cleanedUp) return;
    cleanedUp = true;
    try { chromeProc.kill(); } catch {}
    try { rmSync(tempProfile, { recursive: true, force: true }); } catch {}
  };
  process.on('exit', cleanup);
  process.on('SIGINT', () => { cleanup(); process.exit(1); });

  // Wait for CDP endpoint readiness
  let version = null;
  for (let i = 0; i < 30; i++) {
    await sleep(200);
    try {
      const res = await fetch(`http://localhost:${CDP_PORT}/json/version`);
      if (res.ok) { version = await res.json(); break; }
    } catch {}
  }
  if (!version) throw new Error('Timed out waiting for Chrome DevTools Protocol endpoint.');
  console.log(`[Chrome] Connected to Chrome ${version['Browser']}`);

  // Locate active page target
  const tabsRes = await fetch(`http://localhost:${CDP_PORT}/json/list`);
  const tabs = await tabsRes.json();
  const pageTab = tabs.find((t) => t.type === 'page');
  if (!pageTab) throw new Error('No active page tab found in Chrome.');

  const cdp = new CdpConnection(pageTab.webSocketDebuggerUrl);
  await cdp.connect();

  // Enable CDP domains
  await cdp.send('Page.enable');
  await cdp.send('Runtime.enable');
  await cdp.send('Network.enable');

  const routes = [
    { name: 'pilot', path: '/pilot' },
    { name: 'decisions', path: '/decisions' },
    { name: 'investigations', path: '/investigations' },
  ];

  const overallResults = [];
  let allPassed = true;

  for (const route of routes) {
    console.log(`\n========================================`);
    console.log(`[Route] Verifying: ${route.path}`);
    console.log(`========================================`);

    // Reset listeners for this route
    cdp.clearListeners();

    const consoleLogs = [];
    const consoleErrors = [];
    const unhandledExceptions = [];
    const networkResponses = [];
    let inFlightRequests = 0;
    let pageLoadFired = false;

    cdp.on('Page.loadEventFired', () => {
      pageLoadFired = true;
    });

    cdp.on('Runtime.consoleAPICalled', (params) => {
      const text = params.args.map((a) => a.value ?? a.description ?? '').join(' ');
      consoleLogs.push({ type: params.type, text });
      if (params.type === 'error') {
        consoleErrors.push(text);
      }
    });

    cdp.on('Runtime.exceptionThrown', (params) => {
      unhandledExceptions.push({
        text: params.exceptionDetails.text,
        description: params.exceptionDetails.exception?.description,
        lineNumber: params.exceptionDetails.lineNumber,
      });
    });

    cdp.on('Network.requestWillBeSent', () => {
      inFlightRequests++;
    });

    cdp.on('Network.responseReceived', (params) => {
      networkResponses.push({
        url: params.response.url,
        status: params.response.status,
        statusText: params.response.statusText,
        mimeType: params.response.mimeType,
      });
    });

    cdp.on('Network.loadingFinished', () => {
      inFlightRequests = Math.max(0, inFlightRequests - 1);
    });

    cdp.on('Network.loadingFailed', () => {
      inFlightRequests = Math.max(0, inFlightRequests - 1);
    });

    const fullUrl = `${WEB_BASE_URL}${route.path}`;
    await cdp.send('Page.navigate', { url: fullUrl });

    // Wait for Page Load Event (up to 8s)
    const loadStart = Date.now();
    while (!pageLoadFired && (Date.now() - loadStart) < 8000) {
      await sleep(100);
    }

    // Wait for Network Idle (0 in-flight requests for at least 600ms)
    console.log('[CDP] Waiting for network idle & async Vue hydration...');
    let idleCounter = 0;
    for (let t = 0; t < 35; t++) {
      await sleep(200);
      if (inFlightRequests === 0) idleCounter++;
      else idleCounter = 0;
      if (idleCounter >= 3) break;
    }

    // Wait for DOM settlement (absence of .loading element, up to 5s)
    for (let t = 0; t < 25; t++) {
      const evalLoading = await cdp.send('Runtime.evaluate', {
        expression: `!!document.querySelector('.loading')`,
      });
      if (!evalLoading.result?.value) break;
      await sleep(200);
    }

    // Small stabilization grace period
    await sleep(300);

    // Capture complete DOM Snapshot
    const domRes = await cdp.send('Runtime.evaluate', {
      expression: 'document.documentElement.outerHTML',
    });
    const domHtml = domRes.result?.value || '';
    const domArtifactPath = join(ARTIFACTS_DIR, `dom_${route.name}_empty.html`);
    writeFileSync(domArtifactPath, domHtml, 'utf8');
    console.log(`[Artifact] DOM snapshot saved to: ${domArtifactPath}`);

    // Find main document response
    const docResponse = networkResponses.find((r) => r.url === fullUrl || r.url === `${fullUrl}/`);
    const docStatus = docResponse ? docResponse.status : 200;

    // Check backend API responses for this route
    const apiResponses = networkResponses.filter((r) => r.url.includes('/v1/'));
    const apiFailures = apiResponses.filter((r) => r.status >= 400);

    // Route-specific DOM validations via browser Runtime.evaluate
    let domChecks = {};
    if (route.name === 'pilot') {
      const evalRes = await cdp.send('Runtime.evaluate', {
        expression: `JSON.stringify({
          hasTitle: document.body.innerText.includes('Executive Pilot Command Center'),
          hasExecutiveSummary: document.body.innerText.includes('Executive Operational Summary'),
          hasEmptyAlerts: document.body.innerText.includes('No active alert episodes'),
          noActiveBanner: document.querySelector('.status-banner') === null
        })`,
      });
      domChecks = JSON.parse(evalRes.result?.value || '{}');
    } else if (route.name === 'decisions') {
      const evalRes = await cdp.send('Runtime.evaluate', {
        expression: `JSON.stringify({
          hasEmptyState: document.querySelector('.empty-state') !== null,
          hasNoDataText: document.body.innerText.includes('No data available'),
          noCards: document.querySelector('.dec-card') === null,
          noErrorBanner: document.querySelector('.error-banner') === null
        })`,
      });
      domChecks = JSON.parse(evalRes.result?.value || '{}');
    } else if (route.name === 'investigations') {
      const evalRes = await cdp.send('Runtime.evaluate', {
        expression: `JSON.stringify({
          hasEmptyState: document.querySelector('.empty-state') !== null,
          hasNoDataText: document.body.innerText.includes('No data available'),
          noCards: document.querySelector('.inv-card') === null,
          noErrorBanner: document.querySelector('.error-banner') === null
        })`,
      });
      domChecks = JSON.parse(evalRes.result?.value || '{}');
    }

    const routePassed =
      docStatus === 200 &&
      apiFailures.length === 0 &&
      unhandledExceptions.length === 0 &&
      consoleErrors.length === 0 &&
      Object.values(domChecks).every(Boolean);

    if (!routePassed) allPassed = false;

    const resultSummary = {
      route: route.path,
      passed: routePassed,
      docStatus,
      apiCallsCount: apiResponses.length,
      apiFailures: apiFailures.map((f) => ({ url: f.url, status: f.status })),
      unhandledExceptionsCount: unhandledExceptions.length,
      unhandledExceptions,
      consoleErrorsCount: consoleErrors.length,
      consoleErrors,
      domChecks,
      domSnapshotFile: domArtifactPath,
    };
    overallResults.push(resultSummary);

    console.log(`[Result] Route ${route.path} -> ${routePassed ? 'PASS' : 'FAIL'}`);
    console.log(` - Document HTTP Status: ${docStatus}`);
    console.log(` - API Calls Intercepted: ${apiResponses.length} (${apiFailures.length} failed)`);
    console.log(` - Console Errors: ${consoleErrors.length}`);
    if (consoleErrors.length > 0) console.log(`   Errors: ${JSON.stringify(consoleErrors)}`);
    console.log(` - Unhandled Exceptions: ${unhandledExceptions.length}`);
    if (unhandledExceptions.length > 0) console.log(`   Exceptions: ${JSON.stringify(unhandledExceptions)}`);
    console.log(` - DOM Assertions: ${JSON.stringify(domChecks)}`);
  }

  // Write aggregate JSON artifact
  const resultsJsonPath = join(ARTIFACTS_DIR, 'empty_state_results.json');
  writeFileSync(resultsJsonPath, JSON.stringify({
    timestamp: new Date().toISOString(),
    overallPassed: allPassed,
    results: overallResults,
  }, null, 2), 'utf8');
  console.log(`\n[Artifact] Aggregate results saved to: ${resultsJsonPath}`);

  cdp.close();
  cleanup();

  if (!allPassed) {
    console.error('\n[FATAL] Empty-state verification failed on one or more routes.');
    process.exit(1);
  }
  console.log('\n[SUCCESS] Milestone 1 empty-state verification succeeded on all routes!');
  process.exit(0);
}

run().catch((err) => {
  console.error('[FATAL Error]', err);
  process.exit(1);
});
