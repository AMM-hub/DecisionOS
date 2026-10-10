<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { DEMO_ACTORS } from '~/composables/api'
import { useLocale, SUPPORTED_LOCALES, loadMessages, t } from '~/composables/locale'

const route = useRoute()
const { user, base } = useApi()
const health = ref<'checking' | 'ok' | 'down'>('checking')
const healthPingMs = ref<number | null>(null)
const { locale, setLocale } = useLocale()
const mobileSidebarOpen = ref(false)

// Load messages on startup
await loadMessages(locale.value)

async function ping() {
  health.value = 'checking'
  const started = performance.now()
  try {
    const res = await fetch(`${base.value}/health`)
    health.value = res.ok ? 'ok' : 'down'
    healthPingMs.value = Math.round(performance.now() - started)
  } catch {
    health.value = 'down'
    healthPingMs.value = null
  }
}

onMounted(() => {
  ping()
  const interval = setInterval(ping, 15000)
  onUnmounted(() => clearInterval(interval))
})

const actorInitials = computed(() => {
  if (user.value === 'alpha.manager') return 'AM'
  if (user.value === 'alpha.modeler') return 'SM'
  return 'OP'
})

const routeTitle = computed(() => {
  const p = route.path
  if (p === '/pilot') return t('nav.pilot', locale.value)
  if (p === '/decisions') return t('nav.decisions', locale.value)
  if (p === '/risk') return t('nav.risk', locale.value)
  if (p === '/monitoring') return t('nav.monitoring', locale.value)
  if (p.startsWith('/investigations')) return t('nav.investigations', locale.value)
  if (p === '/forecasts') return t('nav.forecasts', locale.value)
  if (p === '/workflow') return t('nav.workflow', locale.value)
  if (p === '/scenarios') return t('nav.scenarios', locale.value)
  if (p === '/datasets') return t('nav.datasets', locale.value)
  if (p === '/metrics') return t('nav.metrics', locale.value)
  if (p === '/uploads') return t('nav.uploads', locale.value)
  if (p === '/pilot/setup') return t('nav.pilot', locale.value)
  return t('nav.home', locale.value)
})

function closeMobileNav() {
  mobileSidebarOpen.value = false
}
</script>

<template>
  <div class="shell" :class="locale === 'ar' ? 'rtl' : ''">
    <!-- Inline SVG Symbol Sprite from Approved Design System -->
    <svg width="0" height="0" style="position:absolute; display:none;" aria-hidden="true">
      <defs>
        <symbol id="i-grid" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></symbol>
        <symbol id="i-gauge" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M12 14a2 2 0 1 0 0-4 2 2 0 0 0 0 4Z"/><path d="m13.4 12.6 4.1-4.1"/><path d="M4.6 18a9 9 0 1 1 14.8 0"/></symbol>
        <symbol id="i-check-square" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></symbol>
        <symbol id="i-alert" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4"/><path d="M12 17h.01"/></symbol>
        <symbol id="i-search" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></symbol>
        <symbol id="i-flask" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M9 3h6"/><path d="M10 3v6.5L4.5 18A2 2 0 0 0 6.2 21h11.6a2 2 0 0 0 1.7-3L14 9.5V3"/><path d="M7 15h10"/></symbol>
        <symbol id="i-pulse" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12h4l2 6 4-14 2 8h6"/></symbol>
        <symbol id="i-layers" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="m12 3 9 5-9 5-9-5 9-5Z"/><path d="m3 13 9 5 9-5"/></symbol>
        <symbol id="i-trend" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M3 17l6-6 4 4 8-8"/><path d="M17 7h4v4"/></symbol>
        <symbol id="i-chev-r" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="m9 6 6 6-6 6"/></symbol>
        <symbol id="i-chev-d" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></symbol>
        <symbol id="i-x" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12"/></symbol>
        <symbol id="i-bell" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M6 8a6 6 0 0 1 12 0c0 7 3 8 3 8H3s3-1 3-8"/><path d="M10.5 20a2 2 0 0 0 3 0"/></symbol>
        <symbol id="i-menu" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M4 6h16M4 12h16M4 18h16"/></symbol>
        <symbol id="i-plus" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M5 12h14"/></symbol>
        <symbol id="i-link" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1.5 1.5"/><path d="M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1.5-1.5"/></symbol>
        <symbol id="i-shield" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3 5 6v6c0 4.5 3 7.5 7 9 4-1.5 7-4.5 7-9V6l-7-3Z"/><path d="m9 12 2 2 4-4"/></symbol>
        <symbol id="i-check" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m5 12 4.5 4.5L19 7"/></symbol>
        <symbol id="i-upload" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M7 9l5-5 5 5"/><path d="M12 4v12"/></symbol>
        <symbol id="i-database" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/></symbol>
        <symbol id="i-ruler" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M3 8h18v8H3z"/><path d="M7 8v3M11 8v4M15 8v3M19 8v4"/></symbol>
        <symbol id="i-branch" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="6" cy="6" r="2.5"/><circle cx="18" cy="6" r="2.5"/><circle cx="6" cy="18" r="2.5"/><path d="M6 8.5v7"/><path d="M8.5 6h7"/><path d="M18 8.5c0 4-4 4-9 4.5"/></symbol>
      </defs>
    </svg>

    <div class="app">
      <!-- ============ PERSISTENT 248px SIDEBAR ============ -->
      <aside class="sidebar" :class="{ open: mobileSidebarOpen }">
        <div class="brand">
          <span class="brand-mark">D</span>
          <div class="brand-text">
            <span class="brand-name">{{ t('common.appName', locale) }}</span>
            <span class="brand-env">tenant_alpha · v2</span>
          </div>
        </div>

        <nav aria-label="Primary">
          <!-- Command Group -->
          <div class="nav-group">
            <span class="nav-label">Command</span>
            <NuxtLink to="/pilot" class="nav-item" @click="closeMobileNav">
              <svg class="ico"><use href="#i-gauge"/></svg>
              <span>{{ t('nav.pilotDashboard', locale) }}</span>
            </NuxtLink>
            <NuxtLink to="/decisions" class="nav-item" @click="closeMobileNav">
              <svg class="ico"><use href="#i-check-square"/></svg>
              <span>{{ t('nav.decisions', locale) }}</span>
            </NuxtLink>
            <NuxtLink to="/risk" class="nav-item" @click="closeMobileNav">
              <svg class="ico"><use href="#i-alert"/></svg>
              <span>{{ t('nav.risk', locale) }}</span>
            </NuxtLink>
          </div>

          <!-- Signal Group -->
          <div class="nav-group">
            <span class="nav-label">Signal</span>
            <NuxtLink to="/monitoring" class="nav-item" @click="closeMobileNav">
              <svg class="ico"><use href="#i-pulse"/></svg>
              <span>{{ t('nav.monitoring', locale) }}</span>
            </NuxtLink>
            <NuxtLink to="/investigations" class="nav-item" @click="closeMobileNav">
              <svg class="ico"><use href="#i-flask"/></svg>
              <span>{{ t('nav.investigations', locale) }}</span>
            </NuxtLink>
            <NuxtLink to="/forecasts" class="nav-item" @click="closeMobileNav">
              <svg class="ico"><use href="#i-trend"/></svg>
              <span>{{ t('nav.forecasts', locale) }}</span>
            </NuxtLink>
            <NuxtLink to="/workflow" class="nav-item" @click="closeMobileNav">
              <svg class="ico"><use href="#i-branch"/></svg>
              <span>{{ t('nav.workflow', locale) }}</span>
            </NuxtLink>
            <NuxtLink to="/scenarios" class="nav-item" @click="closeMobileNav">
              <svg class="ico"><use href="#i-ruler"/></svg>
              <span>{{ t('nav.scenarios', locale) }}</span>
            </NuxtLink>
          </div>

          <!-- Data Foundation Group -->
          <div class="nav-group">
            <span class="nav-label">Data foundation</span>
            <NuxtLink to="/datasets" class="nav-item" @click="closeMobileNav">
              <svg class="ico"><use href="#i-layers"/></svg>
              <span>{{ t('nav.datasets', locale) }}</span>
            </NuxtLink>
            <NuxtLink to="/metrics" class="nav-item" @click="closeMobileNav">
              <svg class="ico"><use href="#i-database"/></svg>
              <span>{{ t('nav.metrics', locale) }}</span>
            </NuxtLink>
            <NuxtLink to="/uploads" class="nav-item" @click="closeMobileNav">
              <svg class="ico"><use href="#i-upload"/></svg>
              <span>{{ t('nav.uploads', locale) }}</span>
            </NuxtLink>
            <NuxtLink to="/pilot/setup" class="nav-item" @click="closeMobileNav">
              <svg class="ico"><use href="#i-shield"/></svg>
              <span>{{ t('nav.pilot', locale) }}</span>
            </NuxtLink>
          </div>
        </nav>

        <div class="sidebar-foot">
          <div class="pilot-chip">
            <span class="pc-ico"><svg style="width:15px;height:15px"><use href="#i-shield"/></svg></span>
            <div class="pc-body">
              <span class="pc-name">Support SLA Pilot</span>
              <span class="pc-sub">Phase 2 · ticket_id grain</span>
            </div>
          </div>
        </div>
      </aside>

      <!-- Scrim for mobile sidebar -->
      <div class="sidebar-scrim" :hidden="!mobileSidebarOpen" @click="closeMobileNav"></div>

      <!-- ============ MAIN CONTENT AREA ============ -->
      <div class="main">
        <!-- Sticky blurred topbar -->
        <header class="topbar">
          <button class="icon-btn topbar-toggle" @click="mobileSidebarOpen = !mobileSidebarOpen" aria-label="Toggle navigation">
            <svg><use href="#i-menu"/></svg>
          </button>

          <div class="crumb">
            <NuxtLink to="/" class="home">{{ t('common.appName', locale) }}</NuxtLink>
            <span class="sep">/</span>
            <span class="here">{{ routeTitle }}</span>
          </div>

          <span class="grow"></span>

          <!-- Health Pill -->
          <span class="health" :data-state="health" :title="`Analytics API ${health}`">
            <span class="dot"></span>
            <span>API {{ health === 'ok' ? (healthPingMs ? `${healthPingMs}ms` : 'healthy') : health }}</span>
          </span>

          <!-- Separation of duties actor selector -->
          <label class="actor" title="Acting as (separation of duties)">
            <span class="av">{{ actorInitials }}</span>
            <select v-model="user" aria-label="Acting user">
              <option v-for="(meta, id) in DEMO_ACTORS" :key="id" :value="id">{{ meta.label }}</option>
            </select>
          </label>

          <!-- Language switcher (segmented button) -->
          <div class="seg" role="group" aria-label="Language">
            <button type="button" :aria-pressed="locale === 'en'" @click="setLocale('en')">EN</button>
            <button type="button" :aria-pressed="locale === 'ar'" @click="setLocale('ar')">العربية</button>
          </div>
        </header>

        <main class="content">
          <NuxtPage />
        </main>
      </div>
    </div>
  </div>
</template>

<style>
/* ============================================================
   DecisionOS — Design System (Monochrome Slate Foundation)
   High-density precision tokens, hairline borders, tabular numerals.
   ============================================================ */
:root {
  color-scheme: light;

  --bg:            oklch(98.4% 0.003 255);
  --surface:       oklch(100% 0 0);
  --surface-2:     oklch(97.4% 0.004 255);
  --surface-3:     oklch(95.2% 0.005 255);
  --fg:            oklch(22% 0.015 260);
  --fg-strong:     oklch(15% 0.018 260);
  --muted:         oklch(50% 0.012 255);
  --faint:         oklch(64% 0.01 255);
  --border:        oklch(92.5% 0.005 255);
  --border-strong: oklch(85% 0.008 255);

  --accent:        oklch(52% 0.155 265);
  --accent-ink:    oklch(40% 0.14 265);
  --accent-soft:   color-mix(in oklch, var(--accent) 11%, transparent);
  --accent-line:   color-mix(in oklch, var(--accent) 32%, transparent);

  --ok:            oklch(56% 0.12 155);
  --ok-ink:        oklch(42% 0.1 155);
  --ok-soft:       color-mix(in oklch, var(--ok) 13%, transparent);
  --warn:          oklch(70% 0.14 75);
  --warn-ink:      oklch(46% 0.1 68);
  --warn-soft:     color-mix(in oklch, var(--warn) 22%, transparent);
  --crit:          oklch(55% 0.2 25);
  --crit-ink:      oklch(46% 0.185 25);
  --crit-soft:     color-mix(in oklch, var(--crit) 12%, transparent);

  --font-sans: -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Segoe UI', system-ui, sans-serif;
  --font-mono: ui-monospace, 'SF Mono', 'JetBrains Mono', Menlo, 'Cascadia Code', monospace;
  --font-display: var(--font-sans);

  --r-xs: 4px; --r-sm: 6px; --r: 7px; --r-md: 9px; --r-lg: 10px; --r-full: 999px;
  --shadow-1: 0 1px 2px oklch(20% 0.02 260 / 0.05);
  --shadow-2: 0 8px 30px -8px oklch(20% 0.03 260 / 0.16), 0 1px 3px oklch(20% 0.03 260 / 0.05);
  --shadow-3: 0 24px 60px -12px oklch(20% 0.04 260 / 0.24);

  --sidebar-w: 248px;
  --topbar-h: 56px;
}

*, *::before, *::after { box-sizing: border-box; }
html, body { height: 100%; margin: 0; padding: 0; }
body {
  background: var(--bg);
  color: var(--fg);
  font-family: var(--font-sans);
  font-size: 13.5px;
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

h1, h2, h3, h4, p { margin: 0; }
h1, h2, h3, h4 { font-family: var(--font-display); }
a { color: inherit; text-decoration: none; }
button { font: inherit; color: inherit; cursor: pointer; background: none; border: 0; }
input, select, textarea { font: inherit; }
::selection { background: var(--accent-soft); }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: var(--r-xs); }

/* Tabular Numerals & BiDi Isolation */
.num { font-family: var(--font-mono); font-variant-numeric: tabular-nums; letter-spacing: -0.01em; }
.isolate,
.bidi-ltr,
bdi,
code,
.hash,
.kpi-val,
.stat .n,
.factor-impact,
[data-bidi="ltr"] {
  unicode-bidi: isolate;
  direction: ltr;
  display: inline-block;
}

/* App Shell Grid */
.app {
  display: grid;
  grid-template-columns: var(--sidebar-w) 1fr;
  min-height: 100vh;
}

/* Persistent 248px Left Sidebar */
.sidebar {
  position: sticky;
  top: 0;
  align-self: start;
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--surface);
  border-inline-end: 1px solid var(--border);
  padding: 14px 12px 12px;
  gap: 2px;
  overflow-y: auto;
  z-index: 40;
}
.brand { display: flex; align-items: center; gap: 10px; padding: 4px 8px 14px; }
.brand-mark {
  width: 28px; height: 28px; border-radius: 7px; flex: none;
  background: var(--fg-strong); color: var(--surface);
  display: grid; place-items: center;
  font-family: var(--font-mono); font-size: 13px; font-weight: 600; letter-spacing: -0.04em;
}
.brand-text { display: flex; flex-direction: column; line-height: 1.15; min-width: 0; }
.brand-name { font-size: 14.5px; font-weight: 650; letter-spacing: -0.02em; color: var(--fg-strong); }
.brand-env { font-family: var(--font-mono); font-size: 9.5px; letter-spacing: 0.12em; text-transform: uppercase; color: var(--faint); }

.nav-group { display: flex; flex-direction: column; gap: 1px; margin-top: 6px; }
.nav-label {
  font-family: var(--font-mono); font-size: 10px; letter-spacing: 0.14em;
  text-transform: uppercase; color: var(--faint); padding: 8px 10px 4px;
}
.nav-item {
  position: relative; display: flex; align-items: center; gap: 10px;
  padding: 7px 10px; border-radius: var(--r);
  color: var(--muted); font-size: 13px; font-weight: 500;
  width: 100%; text-align: start; line-height: 1.3;
  transition: background 0.12s ease, color 0.12s ease;
}
.nav-item .ico { width: 16px; height: 16px; flex: none; opacity: 0.8; }
.nav-item:hover { background: var(--surface-2); color: var(--fg); }
.nav-item.router-link-active,
.nav-item[aria-current="page"] {
  background: var(--accent-soft);
  color: var(--accent-ink);
  font-weight: 600;
}
.nav-item.router-link-active .ico,
.nav-item[aria-current="page"] .ico {
  opacity: 1;
  color: var(--accent);
}
.nav-item.router-link-active::before,
.nav-item[aria-current="page"]::before {
  content: "";
  position: absolute;
  inset-inline-start: -12px;
  top: 7px;
  bottom: 7px;
  width: 3px;
  border-radius: 0 3px 3px 0;
  background: var(--accent);
}

.sidebar-foot { margin-top: auto; padding: 12px 8px 4px; border-top: 1px solid var(--border); }
.pilot-chip { display: flex; align-items: center; gap: 9px; }
.pilot-chip .pc-ico {
  width: 30px; height: 30px; border-radius: var(--r); background: var(--surface-2);
  border: 1px solid var(--border); display: grid; place-items: center; color: var(--muted); flex: none;
}
.pilot-chip .pc-body { min-width: 0; }
.pilot-chip .pc-name { font-size: 12.5px; font-weight: 600; color: var(--fg); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.pilot-chip .pc-sub { font-family: var(--font-mono); font-size: 10px; color: var(--faint); letter-spacing: 0.02em; }

/* Main Section */
.main { min-width: 0; display: flex; flex-direction: column; }
.topbar {
  position: sticky; top: 0; z-index: 30;
  display: flex; align-items: center; gap: 10px; flex-wrap: nowrap;
  padding: 0 18px; height: var(--topbar-h);
  background: color-mix(in oklch, var(--bg) 86%, transparent);
  backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--border);
}
.topbar > * { flex: none; }
.topbar-toggle { display: none; }
.crumb { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--muted); min-width: 0; flex: 0 1 auto; overflow: hidden; }
.crumb .sep { color: var(--faint); }
.crumb .here { color: var(--fg-strong); font-weight: 600; white-space: nowrap; text-overflow: ellipsis; overflow: hidden; }
.topbar .grow { flex: 1 1 auto; }

.icon-btn {
  width: 34px; height: 34px; border-radius: var(--r); display: grid; place-items: center;
  color: var(--muted); border: 1px solid transparent; flex: none;
  transition: background 0.12s ease, color 0.12s ease, border-color 0.12s ease;
}
.icon-btn:hover { background: var(--surface-2); color: var(--fg); border-color: var(--border); }
.icon-btn svg { width: 17px; height: 17px; }

.health {
  display: inline-flex; align-items: center; gap: 6px;
  font-family: var(--font-mono); font-size: 11px; letter-spacing: 0.02em;
  padding: 0 10px; height: 26px; border-radius: var(--r-full); border: 1px solid var(--border);
  background: var(--surface); color: var(--muted); flex: none;
}
.health .dot { width: 6px; height: 6px; border-radius: 50%; background: var(--ok); }
.health[data-state="down"] .dot { background: var(--crit); }
.health[data-state="checking"] .dot { background: var(--warn); }

.actor {
  display: flex; align-items: center; gap: 8px; padding: 3px 8px 3px 10px; height: 34px;
  border: 1px solid var(--border); border-radius: var(--r-full); background: var(--surface); flex: none;
}
.actor .av {
  width: 24px; height: 24px; border-radius: 50%; flex: none;
  background: var(--accent-soft); color: var(--accent-ink);
  font-family: var(--font-mono); font-size: 10.5px; font-weight: 600;
  display: grid; place-items: center;
}
.actor select { border: 0; background: none; font-size: 12.5px; color: var(--fg); outline: 0; cursor: pointer; max-width: 170px; }

.seg { display: inline-flex; border: 1px solid var(--border); border-radius: var(--r); overflow: hidden; background: var(--surface); flex: none; }
.seg button { padding: 0 11px; height: 32px; font-size: 12px; font-weight: 600; color: var(--muted); transition: background 0.12s ease, color 0.12s ease; }
.seg button:hover { background: var(--surface-2); color: var(--fg); }
.seg button[aria-pressed="true"] { background: var(--fg-strong); color: var(--surface); }
.seg button + button { border-inline-start: 1px solid var(--border); }

.content { padding: 20px 24px 64px; max-width: 1560px; width: 100%; }

/* Buttons & UI Controls */
.btn {
  display: inline-flex; align-items: center; justify-content: center; gap: 7px;
  height: 34px; padding: 0 14px; border-radius: var(--r);
  border: 1px solid transparent; font-size: 13px; font-weight: 550; letter-spacing: -0.005em;
  white-space: nowrap; transition: background 0.13s ease, border-color 0.13s ease, color 0.13s ease, transform 0.06s ease;
}
.btn:active { transform: translateY(0.5px); }
.btn svg { width: 15px; height: 15px; }
.btn-primary { background: var(--fg-strong); color: var(--surface); border-color: var(--fg-strong); }
.btn-primary:hover { background: oklch(26% 0.02 260); border-color: oklch(26% 0.02 260); }
.btn-secondary, button.secondary { background: var(--surface); color: var(--fg); border-color: var(--border-strong); }
.btn-secondary:hover, button.secondary:hover { background: var(--surface-2); border-color: var(--faint); }
.btn-ghost { background: transparent; color: var(--muted); }
.btn-ghost:hover { background: var(--surface-2); color: var(--fg); }
.btn-sm { height: 28px; padding: 0 10px; font-size: 12px; }
.btn-xs { height: 24px; padding: 0 8px; font-size: 11px; border-radius: var(--r-sm); }
.btn:disabled, button:disabled { opacity: 0.45; cursor: not-allowed; }
.btn-danger, button.danger { background: transparent; color: var(--crit-ink); border-color: color-mix(in oklch, var(--crit) 32%, transparent); }
.btn-danger:hover, button.danger:hover { background: var(--crit-soft); }

/* Panels & Surfaces */
.panel, .card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  margin-bottom: 14px;
}
.panel-head, .card-header {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  padding: 11px 14px; border-bottom: 1px solid var(--border);
}
.panel-head h2, .panel-head h3, .card-header h2, .card-header h3 {
  font-size: 13.5px; font-weight: 650; letter-spacing: -0.01em; color: var(--fg-strong);
}
.panel-head .sub { font-size: 11.5px; color: var(--faint); font-family: var(--font-mono); }
.panel-body, .card-body { padding: 14px; }
.panel-body.tight { padding: 0; }

/* KPI Band */
.kpi-band {
  display: grid;
  grid-template-columns: repeat(4, minmax(0,1fr));
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  background: var(--surface);
  overflow: hidden;
  margin-bottom: 16px;
}
.kpi {
  position: relative; display: flex; flex-direction: column; gap: 5px;
  padding: 14px 16px; text-align: start; border-inline-start: 1px solid var(--border);
  transition: background 0.12s ease;
}
.kpi:first-child { border-inline-start: 0; }
.kpi:hover { background: var(--surface-2); }
.kpi .k-label { display: flex; align-items: center; gap: 7px; font-size: 11.5px; font-weight: 550; color: var(--muted); }
.kpi .k-label .mark { width: 6px; height: 6px; border-radius: 50%; flex: none; background: var(--faint); }
.kpi[data-tone="crit"] .k-label .mark { background: var(--crit); }
.kpi[data-tone="warn"] .k-label .mark { background: var(--warn); }
.kpi[data-tone="ok"] .k-label .mark { background: var(--ok); }
.kpi[data-tone="accent"] .k-label .mark { background: var(--accent); }
.kpi .k-val { font-family: var(--font-mono); font-variant-numeric: tabular-nums; font-size: 26px; font-weight: 600; letter-spacing: -0.03em; line-height: 1; color: var(--fg-strong); }
.kpi .k-val .unit { font-size: 13px; color: var(--faint); margin-inline-start: 3px; letter-spacing: 0; }
.kpi .k-foot { display: flex; align-items: baseline; gap: 8px; font-size: 11px; color: var(--faint); margin-top: 3px; }
.kpi .k-delta { font-family: var(--font-mono); font-weight: 600; }
.kpi .k-delta.up { color: var(--crit-ink); }
.kpi .k-delta.down { color: var(--ok-ink); }
.kpi .k-delta.flat { color: var(--muted); }

/* Enterprise Tables */
.table-scroll { overflow-x: auto; width: 100%; }
table.dt, table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
table.dt th, table.dt td, table th, table td {
  height: 36px; padding: 6px 14px; text-align: start; border-bottom: 1px solid var(--border); vertical-align: middle;
}
table.dt thead th, table thead th {
  position: sticky; top: 0; z-index: 2; background: var(--surface-2); height: 34px;
  font-family: var(--font-mono); font-size: 10.5px; letter-spacing: 0.07em; text-transform: uppercase;
  color: var(--muted); font-weight: 600; white-space: nowrap; border-bottom: 1px solid var(--border-strong);
}
table.dt thead th.sortable { cursor: pointer; user-select: none; }
table.dt thead th.sortable:hover { color: var(--fg); }
table.dt tbody tr { transition: background 0.1s ease; cursor: pointer; }
table.dt tbody tr:hover { background: var(--surface-2); }
table.dt tbody tr.selected { background: var(--accent-soft); }
table.dt td.num, table.dt th.num { font-family: var(--font-mono); font-variant-numeric: tabular-nums; text-align: end; }
table.dt td.strong { font-weight: 600; color: var(--fg-strong); }
table.dt td .id { font-family: var(--font-mono); font-size: 12px; color: var(--fg); }
.status-dot { width: 7px; height: 7px; border-radius: 50%; display: inline-block; flex: none; }
.status-cell { display: inline-flex; align-items: center; gap: 7px; white-space: nowrap; }
.status-cell[data-tone="ok"] { color: var(--ok-ink); }
.status-cell[data-tone="ok"] .status-dot { background: var(--ok); }
.status-cell[data-tone="warn"] { color: var(--warn-ink); }
.status-cell[data-tone="warn"] .status-dot { background: var(--warn); }
.status-cell[data-tone="crit"] { color: var(--crit-ink); }
.status-cell[data-tone="crit"] .status-dot { background: var(--crit); }
.status-cell[data-tone="accent"] { color: var(--accent-ink); }
.status-cell[data-tone="accent"] .status-dot { background: var(--accent); }

/* Status Badges & Chips */
.badge, .chip {
  display: inline-flex; align-items: center; gap: 6px;
  font-family: var(--font-mono); font-size: 10.5px; font-weight: 600; letter-spacing: 0.05em;
  padding: 2px 8px; border-radius: var(--r-full); border: 1px solid var(--border);
  background: var(--surface-2); color: var(--muted); white-space: nowrap;
}
.badge.ok, .chip[data-tone="ok"], .badge-green { color: var(--ok-ink); background: var(--ok-soft); border-color: transparent; }
.badge.warn, .chip[data-tone="warn"], .badge-yellow, .badge-warning { color: var(--warn-ink); background: var(--warn-soft); border-color: transparent; }
.badge.err, .badge.crit, .chip[data-tone="crit"], .badge-red { color: var(--crit-ink); background: var(--crit-soft); border-color: transparent; }
.badge.blue, .chip[data-tone="accent"] { color: var(--accent-ink); background: var(--accent-soft); border-color: transparent; }
.badge.purple { color: oklch(46% 0.18 310); background: oklch(94% 0.04 310); border-color: transparent; }
.badge.gray { color: var(--muted); background: var(--surface-2); border-color: var(--border); }

/* Banners */
.banner {
  display: flex; align-items: center; gap: 10px; padding: 11px 14px; border-radius: var(--r-md);
  border: 1px solid var(--border); background: var(--surface); font-size: 12.5px; color: var(--muted);
}
.banner[data-tone="warn"] { background: var(--warn-soft); border-color: color-mix(in oklch, var(--warn) 40%, transparent); color: var(--warn-ink); }
.banner svg { width: 16px; height: 16px; flex: none; }

/* Detail Drawer & Scrim */
.scrim { position: fixed; inset: 0; background: oklch(20% 0.02 260 / 0.34); backdrop-filter: blur(1.5px); z-index: 60; }
.drawer {
  position: fixed; inset-block: 0; inset-inline-end: 0; width: min(580px, 94vw);
  background: var(--surface); border-inline-start: 1px solid var(--border);
  box-shadow: var(--shadow-3); z-index: 61; display: flex; flex-direction: column;
}
.drawer-head { padding: 18px 20px 14px; border-bottom: 1px solid var(--border); }
.drawer-head .dh-top { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.drawer-head h2 { font-size: 16px; font-weight: 650; letter-spacing: -0.02em; color: var(--fg-strong); line-height: 1.25; }
.drawer-body { overflow-y: auto; padding: 18px 20px; display: flex; flex-direction: column; gap: 18px; }
.drawer-foot { margin-top: auto; padding: 14px 20px; border-top: 1px solid var(--border); display: flex; gap: 8px; justify-content: flex-end; background: var(--surface); }

/* Modals */
.modal-backdrop, .modal-wrap {
  position: fixed; inset: 0; background: oklch(20% 0.02 260 / 0.34); backdrop-filter: blur(1.5px);
  z-index: 70; display: grid; place-items: center; padding: 20px;
}
.modal {
  width: 100%; max-width: 560px; max-height: 90vh; overflow-y: auto;
  background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-lg); box-shadow: var(--shadow-3);
  padding: 1.5rem;
}

/* Fields & Inputs */
input, select, textarea {
  border: 1px solid var(--border-strong); border-radius: var(--r); background: var(--surface);
  padding: 6px 10px; font-size: 13px; color: var(--fg);
}
input:focus, select:focus, textarea:focus {
  outline: 0; border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft);
}
label.field { display: flex; flex-direction: column; gap: 5px; font-size: 12.5px; margin-bottom: 10px; font-weight: 550; color: var(--fg); }

/* Backward Compatibility Utilities */
.muted { color: var(--muted); }
.faint { color: var(--faint); }
.row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.grid { display: grid; gap: 14px; }
.grid-2, .grid.cols-2 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.grid-3, .grid.cols-3 { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.stat { text-align: left; }
.stat .n { font-size: 1.8rem; font-weight: 700; font-family: var(--font-mono); }
.loading { color: var(--muted); font-style: italic; padding: 1rem; }
.error-banner { background: var(--crit-soft); color: var(--crit-ink); padding: 0.75rem; border-radius: var(--r); margin-bottom: 1rem; }

/* RTL Overrides */
.rtl { direction: rtl; }
.rtl .stat { text-align: right; }
.rtl th, .rtl td { text-align: right; }
.rtl .nav-item::before { border-radius: 3px 0 0 3px; }

/* Responsive Media Queries */
@media (max-width: 920px) {
  .app { grid-template-columns: 1fr; }
  :root { --sidebar-w: 0px; }
  .sidebar {
    position: fixed; inset-block: 0; inset-inline-start: 0; width: 264px;
    transform: translateX(-100%); transition: transform 0.22s cubic-bezier(0.22,1,0.36,1);
    box-shadow: var(--shadow-3);
  }
  .rtl .sidebar { inset-inline-start: auto; inset-inline-end: 0; transform: translateX(100%); }
  .sidebar.open { transform: none !important; }
  .sidebar-scrim { display: block; position: fixed; inset: 0; background: oklch(20% 0.02 260 / 0.34); z-index: 39; }
  .topbar-toggle { display: grid; }
  .content { padding: 18px 16px 56px; }
  .grid-2, .grid-3, .grid.cols-3 { grid-template-columns: 1fr; }
}
@media (max-width: 620px) {
  .kpi-band { grid-template-columns: 1fr; }
  .kpi { border-inline-start: 0 !important; border-top: 1px solid var(--border); }
  .kpi:first-child { border-top: 0; }
  .health { display: none; }
}
</style>