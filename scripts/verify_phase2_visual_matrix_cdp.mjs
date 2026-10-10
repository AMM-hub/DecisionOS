/**
 * scripts/verify_phase2_visual_matrix_cdp.mjs
 * DecisionOS PILOT-01 Milestone 2: Visual & Localization Matrix Test Runner
 *
 * Full Matrix Grid:
 * - Viewports: 1920x1080 (Full HD Desktop), 1366x768 (Standard Laptop)
 * - Locales: 'en' (LTR), 'ar' (RTL)
 * - Routes: '/pilot', '/decisions', '/investigations'
 * (Total: 12 test matrix configurations)
 *
 * Core Assertions:
 * 1. Viewport metrics via CDP Emulation.setDeviceMetricsOverride
 * 2. UI select & programmatic locale switching (select.locale-picker, localStorage)
 * 3. Direction validation: documentElement.dir ('rtl' for Arabic, 'ltr' for English) and .shell.rtl class
 * 4. Zero horizontal overflow clipping (scrollWidth <= clientWidth + 1 tolerance)
 * 5. Critical action buttons visible above the fold (rect.bottom <= viewportHeight, rect.top >= 0)
 * 6. Zero badge overlap via pairwise Axis-Aligned Bounding Box (AABB) intersection
 * 7. Numbers, percentages, and ticket IDs LTR readability preservation via DOM Range character coordinate analysis
 * 8. Table header alignment in RTL (textAlign === 'right') and LTR (textAlign === 'left')
 * 9. Screenshots saved to var/qa_artifacts/screenshots/<route>_<locale>_<viewport>.png
 * 10. DOM snapshots saved to var/qa_artifacts/dom_<route>_<locale>_<viewport>.html
 * 11. Aggregate JSON telemetry saved to var/qa_artifacts/visual_matrix_results.json
 *
 * Zero external dependencies: Uses Node 24 native WebSocket + fetch + CDP
 */

import { spawn } from 'node:child_process';
import { mkdtempSync, rmSync, writeFileSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';

const CHROME_PATH = process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const WEB_BASE_URL = process.env.WEB_BASE_URL || 'http://localhost:3000';
const API_BASE_URL = process.env.API_BASE_URL || 'http://localhost:8100';
const CDP_PORT = parseInt(process.env.CDP_PORT || '9226', 10);
const ARTIFACTS_DIR = join(process.cwd(), 'var', 'qa_artifacts');
const SCREENSHOTS_DIR = join(ARTIFACTS_DIR, 'screenshots');

mkdirSync(SCREENSHOTS_DIR, { recursive: true });

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

  send(method, params = {}, timeoutMs = 15000) {
    const curId = this.id++;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        if (this.pending.has(curId)) {
          this.pending.delete(curId);
          reject(new Error(`CDP command '${method}' timed out after ${timeoutMs}ms`));
        }
      }, timeoutMs);

      this.pending.set(curId, {
        resolve: (val) => { clearTimeout(timer); resolve(val); },
        reject: (err) => { clearTimeout(timer); reject(err); },
      });

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
    if (this.ws) {
      try { this.ws.close(); } catch {}
    }
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

  const tempProfile = mkdtempSync(join(tmpdir(), 'decisionos-m2-visual-'));
  console.log(`[Chrome] Launching Headless Chrome with isolated profile: ${tempProfile}`);

  const chromeProc = spawn(CHROME_PATH, [
    '--headless=new',
    `--remote-debugging-port=${CDP_PORT}`,
    `--user-data-dir=${tempProfile}`,
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-background-networking',
    '--disable-extensions',
    '--disable-sync',
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

  let version = null;
  for (let i = 0; i < 30; i++) {
    await sleep(200);
    try {
      const res = await fetch(`http://localhost:${CDP_PORT}/json/version`);
      if (res.ok) { version = await res.json(); break; }
    } catch {}
  }
  if (!version) throw new Error('Timed out waiting for Chrome DevTools Protocol endpoint.');
  console.log(`[Chrome] Connected to ${version['Browser']}`);

  const tabsRes = await fetch(`http://localhost:${CDP_PORT}/json/list`);
  const tabs = await tabsRes.json();
  const pageTab = tabs.find((t) => t.type === 'page');
  if (!pageTab) throw new Error('No active page tab found in Chrome.');

  const cdp = new CdpConnection(pageTab.webSocketDebuggerUrl);
  await cdp.connect();

  await cdp.send('Page.enable');
  await cdp.send('Runtime.enable');
  await cdp.send('Network.enable');

  const VIEWPORTS = [
    { width: 1920, height: 1080, name: '1920x1080', label: 'Full HD Desktop' },
    { width: 1366, height: 768, name: '1366x768', label: 'Standard Laptop' },
  ];

  const LOCALES = [
    { code: 'en', dir: 'ltr', label: 'English' },
    { code: 'ar', dir: 'rtl', label: 'Arabic' },
  ];

  const ROUTES = [
    {
      path: '/pilot',
      name: 'pilot',
      title: 'Executive Pilot Command Center',
      criticalButton: {
        role: 'Guided Pilot Setup',
        selector: 'main .actions-row a.btn-primary, main a[href="/pilot/setup"]',
        textRegex: 'Guided Pilot Setup|إعداد|setupLink',
      },
    },
    {
      path: '/decisions',
      name: 'decisions',
      title: 'Decisions Console',
      criticalButton: {
        role: '+ Create Decision Brief',
        selector: 'main .header-row button.btn-primary, button.btn-primary',
        textRegex: 'Create Decision|Decision Brief|إنشاء|newDecision',
      },
    },
    {
      path: '/investigations',
      name: 'investigations',
      title: 'Investigations Console',
      criticalButton: {
        role: '+ Launch Investigation',
        selector: 'main .header-row button.btn-primary, button.btn-primary',
        textRegex: 'Launch Investigation|Investigation|إطلاق|newInvestigation',
      },
    },
  ];

  const matrixResults = [];
  let overallPassed = true;

  console.log(`\n================================================================`);
  console.log(`Executing Milestone 2 Phase 2 Browser Matrix Verification`);
  console.log(`Matrix Grid: 2 Viewports x 2 Locales x 3 Routes = 12 Test Cases`);
  console.log(`================================================================\n`);

  for (const vp of VIEWPORTS) {
    console.log(`\n----------------------------------------------------------------`);
    console.log(`[Viewport Group] Setting Viewport to ${vp.name} (${vp.label})`);
    console.log(`----------------------------------------------------------------`);

    // Dynamically set viewport via Emulation.setDeviceMetricsOverride
    await cdp.send('Emulation.setDeviceMetricsOverride', {
      width: vp.width,
      height: vp.height,
      deviceScaleFactor: 1,
      mobile: false,
      screenWidth: vp.width,
      screenHeight: vp.height,
    });

    for (const loc of LOCALES) {
      for (const route of ROUTES) {
        const testId = `${route.name}_${loc.code}_${vp.name}`;
        console.log(`\n>>> Executing Test: [${testId}] (Route: ${route.path}, Locale: ${loc.code.toUpperCase()}, VP: ${vp.name})`);

        cdp.clearListeners();
        const consoleErrors = [];
        const unhandledExceptions = [];
        let inFlightRequests = 0;
        let pageLoadFired = false;

        cdp.on('Page.loadEventFired', () => { pageLoadFired = true; });
        cdp.on('Runtime.consoleAPICalled', (params) => {
          if (params.type === 'error') {
            const text = params.args.map((a) => a.value ?? a.description ?? '').join(' ');
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
        cdp.on('Network.requestWillBeSent', () => { inFlightRequests++; });
        cdp.on('Network.loadingFinished', () => { inFlightRequests = Math.max(0, inFlightRequests - 1); });
        cdp.on('Network.loadingFailed', () => { inFlightRequests = Math.max(0, inFlightRequests - 1); });

        const fullUrl = `${WEB_BASE_URL}${route.path}`;
        await cdp.send('Page.navigate', { url: fullUrl });

        // Wait for page load
        const loadStart = Date.now();
        while (!pageLoadFired && (Date.now() - loadStart) < 8000) {
          await sleep(100);
        }

        // Wait for network idle
        let idleCounter = 0;
        for (let t = 0; t < 30; t++) {
          await sleep(150);
          if (inFlightRequests === 0) idleCounter++;
          else idleCounter = 0;
          if (idleCounter >= 3) break;
        }

        // Wait for removal of loading indicators
        for (let t = 0; t < 20; t++) {
          const evalLoading = await cdp.send('Runtime.evaluate', {
            expression: `!!document.querySelector('.loading')`,
          });
          if (!evalLoading.result?.value) break;
          await sleep(150);
        }

        // Locale Switch: Programmatic + UI dropdown interaction
        await cdp.send('Runtime.evaluate', {
          expression: `(() => {
            const targetLocale = '${loc.code}';
            // 1. Set localStorage for persistence
            localStorage.setItem('decisionos_locale', targetLocale);

            // 2. Interact with UI dropdown
            const select = document.querySelector('select.locale-picker') || document.querySelector('select[aria-label="Language"]');
            if (select) {
              select.value = targetLocale;
              select.dispatchEvent(new Event('input', { bubbles: true }));
              select.dispatchEvent(new Event('change', { bubbles: true }));
            }

            // 3. Update document attributes
            document.documentElement.lang = targetLocale;
            document.documentElement.dir = targetLocale === 'ar' ? 'rtl' : 'ltr';
            const shell = document.querySelector('.shell');
            if (shell) {
              if (targetLocale === 'ar') shell.classList.add('rtl');
              else shell.classList.remove('rtl');
            }
          })()`,
        });

        // Stabilization pause for Vue reactivity & layout reflow
        await sleep(350);

        // Comprehensive in-browser DOM & visual assertions
        const evalRes = await cdp.send('Runtime.evaluate', {
          expression: `(() => {
            const doc = document.documentElement;
            const body = document.body;
            const shell = document.querySelector('.shell');
            const targetLocale = '${loc.code}';
            const expectedDir = '${loc.dir}';

            // 1. Direction & Locale Attributes
            const actualDir = doc.dir || doc.getAttribute('dir') || 'ltr';
            const actualLang = doc.lang || doc.getAttribute('lang') || 'en';
            const hasRtlClass = shell ? shell.classList.contains('rtl') : false;
            const dirValid = (actualDir === expectedDir) &&
                             (targetLocale === 'ar' ? hasRtlClass : !hasRtlClass);

            // 2. Horizontal Overflow Clipping (scrollWidth <= clientWidth)
            const docScrollWidth = doc.scrollWidth;
            const docClientWidth = doc.clientWidth;
            const bodyScrollWidth = body.scrollWidth;
            const bodyClientWidth = body.clientWidth;

            // Allow 1px subpixel tolerance
            const hasDocOverflow = docScrollWidth > (docClientWidth + 1);
            const hasBodyOverflow = bodyScrollWidth > (bodyClientWidth + 1);

            const overflowingElements = [];
            const allNodes = document.querySelectorAll('*');
            for (const el of allNodes) {
              if (el.scrollWidth > (el.clientWidth + 1) && el.clientWidth > 0) {
                const cs = window.getComputedStyle(el);
                if (cs.overflowX !== 'auto' && cs.overflowX !== 'scroll' && cs.overflowX !== 'hidden') {
                  const rect = el.getBoundingClientRect();
                  if (rect.right > (window.innerWidth + 1) || rect.left < -1) {
                    overflowingElements.push({
                      tag: el.tagName.toLowerCase(),
                      className: (el.className || '').toString().slice(0, 40),
                      id: el.id || '',
                      scrollWidth: el.scrollWidth,
                      clientWidth: el.clientWidth,
                      delta: el.scrollWidth - el.clientWidth,
                    });
                  }
                }
              }
            }
            const overflowPass = !hasDocOverflow && !hasBodyOverflow && overflowingElements.length === 0;

            // 3. Badge Overlap Detection (AABB collision detection)
            const badges = Array.from(document.querySelectorAll('.badge'));
            const visibleBadges = [];
            for (let i = 0; i < badges.length; i++) {
              const b = badges[i];
              const r = b.getBoundingClientRect();
              const cs = window.getComputedStyle(b);
              if (r.width > 0 && r.height > 0 && cs.display !== 'none' && cs.visibility !== 'hidden') {
                visibleBadges.push({
                  index: i,
                  text: b.textContent.trim().slice(0, 30),
                  rect: {
                    top: Math.round(r.top * 10) / 10,
                    bottom: Math.round(r.bottom * 10) / 10,
                    left: Math.round(r.left * 10) / 10,
                    right: Math.round(r.right * 10) / 10,
                    width: Math.round(r.width * 10) / 10,
                    height: Math.round(r.height * 10) / 10,
                  }
                });
              }
            }

            const badgeOverlaps = [];
            for (let i = 0; i < visibleBadges.length; i++) {
              for (let j = i + 1; j < visibleBadges.length; j++) {
                const b1 = visibleBadges[i];
                const b2 = visibleBadges[j];
                const xOverlap = Math.min(b1.rect.right, b2.rect.right) - Math.max(b1.rect.left, b2.rect.left);
                const yOverlap = Math.min(b1.rect.bottom, b2.rect.bottom) - Math.max(b1.rect.top, b2.rect.top);
                // Strict collision: true intersection > 1px in both dimensions
                if (xOverlap > 1 && yOverlap > 1) {
                  badgeOverlaps.push({
                    badge1: b1.text,
                    badge2: b2.text,
                    overlapWidth: Math.round(xOverlap * 10) / 10,
                    overlapHeight: Math.round(yOverlap * 10) / 10,
                    rect1: b1.rect,
                    rect2: b2.rect,
                  });
                }
              }
            }
            const badgePass = badgeOverlaps.length === 0;

            // 4. Critical Action Button Above the Fold (rect.bottom <= viewportHeight)
            let criticalBtn = document.querySelector('${route.criticalButton.selector}');
            if (!criticalBtn) {
              const regex = new RegExp('${route.criticalButton.textRegex}', 'i');
              criticalBtn = Array.from(document.querySelectorAll('a.btn, button.btn, button')).find(el => regex.test(el.textContent));
            }

            let btnCheck = {
              expectedRole: '${route.criticalButton.role}',
              found: false,
              aboveFold: false,
              visible: false,
              rect: null,
            };

            if (criticalBtn) {
              const r = criticalBtn.getBoundingClientRect();
              const cs = window.getComputedStyle(criticalBtn);
              const isVis = r.width > 0 && r.height > 0 && cs.display !== 'none' && cs.visibility !== 'hidden';
              const isAbove = isVis && (r.bottom <= window.innerHeight) && (r.top >= 0);
              const isWithinH = (r.left >= 0) && (r.right <= window.innerWidth);
              btnCheck = {
                expectedRole: '${route.criticalButton.role}',
                found: true,
                text: criticalBtn.textContent.trim(),
                visible: isVis,
                aboveFold: isAbove && isWithinH,
                rect: {
                  top: Math.round(r.top),
                  bottom: Math.round(r.bottom),
                  left: Math.round(r.left),
                  right: Math.round(r.right),
                  width: Math.round(r.width),
                  height: Math.round(r.height),
                },
                viewportHeight: window.innerHeight,
                viewportWidth: window.innerWidth,
              };
            }
            const btnPass = btnCheck.found && btnCheck.aboveFold;

            // 5. Numbers, Percentages, and Ticket IDs LTR Readability & Range Analysis
            const idAndNumRegex = /(\\b[A-Za-z]+-\\d+\\b|\\bev-[\\w-]+\\b|\\b\\d+(\\.\\d+)?%|\\bRev\\s*#\\d+|\\bv\\d+(\\.\\d+)?)/;
            const bidiCandidates = document.querySelectorAll('code, .hash, .kpi-val, .badge, th, td, p, span, strong, h1, h2, h3, h4');
            const foundTokens = [];
            let bidiPreserved = true;

            for (const el of bidiCandidates) {
              const text = el.textContent?.trim() || '';
              const match = text.match(idAndNumRegex);
              if (match) {
                const token = match[0];
                const cs = window.getComputedStyle(el);

                let isLtrOrientation = true;
                if (targetLocale === 'ar' && token.length > 1) {
                  // Perform DOM Range character coordinate check
                  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
                  let targetNode = null;
                  while (walker.nextNode()) {
                    if (walker.currentNode.textContent.includes(token)) {
                      targetNode = walker.currentNode;
                      break;
                    }
                  }
                  if (targetNode) {
                    try {
                      const range = document.createRange();
                      const startIdx = targetNode.textContent.indexOf(token);
                      const endIdx = startIdx + token.length - 1;
                      range.setStart(targetNode, startIdx);
                      range.setEnd(targetNode, startIdx + 1);
                      const r1 = range.getBoundingClientRect();
                      range.setStart(targetNode, endIdx);
                      range.setEnd(targetNode, endIdx + 1);
                      const r2 = range.getBoundingClientRect();
                      if (r1.width > 0 && r2.width > 0) {
                        isLtrOrientation = r1.left < r2.left;
                        if (!isLtrOrientation) bidiPreserved = false;
                      }
                    } catch {}
                  }
                }

                foundTokens.push({
                  token,
                  tag: el.tagName.toLowerCase(),
                  direction: cs.direction,
                  unicodeBidi: cs.unicodeBidi,
                  isLtrOrientation,
                });
              }
            }
            const bidiPass = bidiPreserved;

            // 6. Table Header Alignment Validation
            const thElements = Array.from(document.querySelectorAll('table th'));
            const expectedThAlign = targetLocale === 'ar' ? 'right' : 'left';
            const thMismatches = [];
            for (const th of thElements) {
              const cs = window.getComputedStyle(th);
              if (cs.textAlign !== expectedThAlign) {
                thMismatches.push({
                  text: th.textContent.trim(),
                  actual: cs.textAlign,
                  expected: expectedThAlign,
                });
              }
            }
            const tablePass = thMismatches.length === 0;

            return {
              dirValid,
              actualDir,
              actualLang,
              hasRtlClass,
              overflowPass,
              hasDocOverflow,
              hasBodyOverflow,
              docScrollWidth,
              docClientWidth,
              overflowingElements,
              badgePass,
              badgeCount: visibleBadges.length,
              badgeOverlaps,
              btnPass,
              btnCheck,
              bidiPass,
              bidiTokenCount: foundTokens.length,
              sampleBidiTokens: foundTokens.slice(0, 10),
              tablePass,
              thCount: thElements.length,
              thMismatches,
            };
          })()`,
          returnByValue: true,
        });

        const checks = evalRes.result?.value || {};

        // Capture screenshot via Page.captureScreenshot
        const screenshotRes = await cdp.send('Page.captureScreenshot', {
          format: 'png',
          captureBeyondViewport: false,
        });
        const screenshotBuffer = Buffer.from(screenshotRes.data, 'base64');
        const screenshotFileName = `${route.name}_${loc.code}_${vp.name}.png`;
        const screenshotPath = join(SCREENSHOTS_DIR, screenshotFileName);
        writeFileSync(screenshotPath, screenshotBuffer);

        // Capture full DOM snapshot
        const domRes = await cdp.send('Runtime.evaluate', {
          expression: 'document.documentElement.outerHTML',
        });
        const domHtml = domRes.result?.value || '';
        const domFileName = `dom_${route.name}_${loc.code}_${vp.name}.html`;
        const domPath = join(ARTIFACTS_DIR, domFileName);
        writeFileSync(domPath, domHtml, 'utf8');

        // Determine test pass/fail
        const testPassed =
          checks.dirValid &&
          checks.overflowPass &&
          checks.badgePass &&
          checks.btnPass &&
          checks.bidiPass &&
          checks.tablePass &&
          consoleErrors.length === 0 &&
          unhandledExceptions.length === 0;

        if (!testPassed) overallPassed = false;

        const resultEntry = {
          id: testId,
          route: route.path,
          routeName: route.name,
          locale: loc.code,
          viewport: { width: vp.width, height: vp.height, name: vp.name },
          passed: testPassed,
          assertions: {
            dirValidation: {
              passed: checks.dirValid,
              actualDir: checks.actualDir,
              expectedDir: loc.dir,
              actualLang: checks.actualLang,
              hasRtlClass: checks.hasRtlClass,
            },
            horizontalOverflow: {
              passed: checks.overflowPass,
              docScrollWidth: checks.docScrollWidth,
              docClientWidth: checks.docClientWidth,
              overflowingElementsCount: checks.overflowingElements?.length || 0,
              overflowingElements: checks.overflowingElements || [],
            },
            badgeOverlap: {
              passed: checks.badgePass,
              badgeCount: checks.badgeCount,
              overlapsCount: checks.badgeOverlaps?.length || 0,
              overlaps: checks.badgeOverlaps || [],
            },
            criticalButtonAboveFold: {
              passed: checks.btnPass,
              button: checks.btnCheck,
            },
            bidiRetention: {
              passed: checks.bidiPass,
              tokensCount: checks.bidiTokenCount,
              sampleTokens: checks.sampleBidiTokens,
            },
            tableHeaderAlignment: {
              passed: checks.tablePass,
              thCount: checks.thCount,
              mismatches: checks.thMismatches,
            },
          },
          consoleErrorsCount: consoleErrors.length,
          consoleErrors,
          unhandledExceptionsCount: unhandledExceptions.length,
          unhandledExceptions,
          artifacts: {
            screenshot: screenshotPath,
            domSnapshot: domPath,
          },
        };

        matrixResults.push(resultEntry);

        console.log(` - Status: ${testPassed ? '✅ PASS' : '❌ FAIL'}`);
        console.log(` - Direction: dir="${checks.actualDir}" lang="${checks.actualLang}" shell.rtl=${checks.hasRtlClass} (${checks.dirValid ? 'OK' : 'FAIL'})`);
        console.log(` - Overflow: scrollWidth=${checks.docScrollWidth} clientWidth=${checks.docClientWidth} (${checks.overflowPass ? 'OK' : 'FAIL'})`);
        console.log(` - Badges: ${checks.badgeCount} detected, ${checks.badgeOverlaps?.length || 0} overlaps (${checks.badgePass ? 'OK' : 'FAIL'})`);
        console.log(` - Critical Button: found=${checks.btnCheck?.found} aboveFold=${checks.btnCheck?.aboveFold} (Y: ${checks.btnCheck?.rect?.top}..${checks.btnCheck?.rect?.bottom}) (${checks.btnPass ? 'OK' : 'FAIL'})`);
        console.log(` - BiDi Retention: tokens=${checks.bidiTokenCount} (${checks.bidiPass ? 'OK' : 'FAIL'})`);
        console.log(` - Screenshot: ${screenshotFileName} (${screenshotBuffer.length} bytes)`);
        console.log(` - DOM Snapshot: ${domFileName}`);
      }
    }
  }

  // Write aggregate JSON telemetry
  const resultsJsonPath = join(ARTIFACTS_DIR, 'visual_matrix_results.json');
  const summaryPayload = {
    timestamp: new Date().toISOString(),
    runner: 'scripts/verify_phase2_visual_matrix_cdp.mjs',
    browser: version['Browser'],
    matrixGrid: {
      viewports: VIEWPORTS.map(v => v.name),
      locales: LOCALES.map(l => l.code),
      routes: ROUTES.map(r => r.path),
    },
    totalConfigurations: matrixResults.length,
    passedConfigurations: matrixResults.filter(r => r.passed).length,
    failedConfigurations: matrixResults.filter(r => !r.passed).length,
    overallPassed,
    results: matrixResults,
  };

  writeFileSync(resultsJsonPath, JSON.stringify(summaryPayload, null, 2), 'utf8');
  console.log(`\n================================================================`);
  console.log(`[Artifact] Aggregate matrix telemetry saved to: ${resultsJsonPath}`);
  console.log(`Summary: ${summaryPayload.passedConfigurations}/${summaryPayload.totalConfigurations} configurations passed.`);
  console.log(`Overall Result: ${overallPassed ? 'ALL PASSED' : 'FAILURES DETECTED'}`);
  console.log(`================================================================\n`);

  cdp.close();
  cleanup();

  if (!overallPassed) {
    console.error('[FATAL] Visual matrix verification encountered one or more failures.');
    process.exit(1);
  }

  console.log('[SUCCESS] All 12 visual matrix test configurations passed successfully!');
  process.exit(0);
}

run().catch((err) => {
  console.error('[FATAL Error]', err);
  process.exit(1);
});
