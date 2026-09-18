<script setup lang="ts">
import { DEMO_ACTORS } from '~/composables/api'

const links = [
  { to: '/', label: 'Overview' },
  { to: '/uploads', label: 'Uploads' },
  { to: '/datasets', label: 'Datasets' },
  { to: '/metrics', label: 'Metrics' },
  { to: '/forecasts', label: 'Forecasts' },
  { to: '/workflow', label: 'Workflow' }
]

const { user, base } = useApi()
const health = ref<'checking' | 'ok' | 'down'>('checking')

async function ping() {
  try {
    const res = await fetch(`${base.value}/health`)
    health.value = res.ok ? 'ok' : 'down'
  } catch {
    health.value = 'down'
  }
}
onMounted(() => { ping(); setInterval(ping, 15000) })
</script>

<template>
  <div class="shell">
    <header>
      <span class="brand">DecisionOS</span>
      <nav aria-label="Primary">
        <NuxtLink v-for="l in links" :key="l.to" :to="l.to">{{ l.label }}</NuxtLink>
      </nav>
      <div class="spacer" />
      <span class="badge" :class="health === 'ok' ? 'ok' : health === 'down' ? 'err' : 'warn'" :title="`Analytics API ${health}`">
        <span class="dot" /> API {{ health }}
      </span>
      <label class="actor">
        <span class="muted">acting as</span>
        <select v-model="user" aria-label="Acting user">
          <option v-for="(meta, id) in DEMO_ACTORS" :key="id" :value="id">{{ meta.label }}</option>
        </select>
      </label>
    </header>
    <main>
      <NuxtPage />
    </main>
  </div>
</template>

<style>
:root { color-scheme: light; }
body { font-family: system-ui, -apple-system, 'Segoe UI', sans-serif; margin: 0; color: #1a2333; }
header { display: flex; align-items: center; gap: 1.25rem; padding: 0.75rem 1.5rem; border-bottom: 1px solid #e2e8f0; }
.brand { font-weight: 700; }
nav { display: flex; gap: 1rem; }
nav a { text-decoration: none; color: #475569; }
nav a.router-link-active { color: #0f766e; font-weight: 600; }
.spacer { flex: 1; }
.actor { display: flex; align-items: center; gap: 0.4rem; font-size: 0.85rem; }
.actor select { padding: 0.25rem 0.4rem; border-radius: 6px; border: 1px solid #cbd5e1; }
.dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; background: currentColor; margin-right: 4px; }
main { max-width: 1080px; margin: 0 auto; padding: 1.5rem; }
.card { border: 1px solid #e2e8f0; border-radius: 8px; padding: 1rem 1.25rem; margin: 1rem 0; }
.muted { color: #64748b; font-size: 0.9rem; }
.badge { display: inline-block; padding: 0.1rem 0.5rem; border-radius: 999px; font-size: 0.78rem; background: #e2e8f0; }
.badge.ok { background: #dcfce7; color: #166534; }
.badge.warn { background: #fef9c3; color: #854d0e; }
.badge.err { background: #fee2e2; color: #991b1b; }
table { border-collapse: collapse; width: 100%; font-size: 0.9rem; }
th, td { text-align: left; padding: 0.35rem 0.6rem; border-bottom: 1px solid #e2e8f0; }
button, .btn { background: #0f766e; color: #fff; border: 0; border-radius: 6px; padding: 0.5rem 0.9rem; cursor: pointer; }
button:disabled { opacity: 0.5; cursor: not-allowed; }
button.secondary { background: #e2e8f0; color: #1a2333; }
button.danger { background: #b91c1c; }
input, select, textarea { font: inherit; padding: 0.4rem 0.5rem; border: 1px solid #cbd5e1; border-radius: 6px; }
label.field { display: flex; flex-direction: column; gap: 0.2rem; font-size: 0.85rem; margin: 0.5rem 0; }
.grid { display: grid; gap: 1rem; }
.grid.cols-3 { grid-template-columns: repeat(3, 1fr); }
.stat { text-align: left; }
.stat .n { font-size: 1.8rem; font-weight: 700; }
.row { display: flex; gap: 0.6rem; align-items: center; flex-wrap: wrap; }
code { background: #f1f5f9; padding: 0.05rem 0.3rem; border-radius: 4px; font-size: 0.85em; }
.linklike { background: none; border: 0; color: #0f766e; cursor: pointer; padding: 0; text-decoration: underline; }
</style>
