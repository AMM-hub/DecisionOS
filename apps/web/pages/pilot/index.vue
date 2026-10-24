<template>
  <div class="pilot-page">
    <!-- Page Header -->
    <div class="page-head">
      <div class="titles">
        <div class="eyebrow">{{ t('pilotCenter.subtitle', locale) }}</div>
        <h1>{{ t('pilotCenter.title', locale) }}</h1>
        <p class="desc">
          Live health of the ingest &rarr; metric &rarr; forecast &rarr; workflow &rarr; risk &rarr; decision pipeline for tenant_alpha (<span class="isolate mono">ticket_id</span> grain).
        </p>
      </div>
      <div class="actions">
        <button class="btn btn-secondary btn-sm" @click="loadPilotSummary">
          <svg><use href="#i-pulse"/></svg>
          <span>Refresh</span>
        </button>
        <NuxtLink to="/pilot/setup" class="btn btn-secondary btn-sm">
          <svg><use href="#i-shield"/></svg>
          <span>{{ t('pilotCenter.setupLink', locale) }}</span>
        </NuxtLink>
        <NuxtLink to="/decisions" class="btn btn-primary btn-sm">
          <svg><use href="#i-plus"/></svg>
          <span>{{ t('decisions.newDecision', locale) }}</span>
        </NuxtLink>
      </div>
    </div>

    <!-- Loading State -->
    <div v-if="loading" class="loading">{{ t('common.loading', locale) }}</div>

    <!-- Empty State -->
    <div v-else-if="!pilot" class="panel empty text-center" style="padding: 3.5rem 1.5rem; text-align: center;">
      <div class="e-ico" style="margin: 0 auto 0.75rem auto;">
        <svg><use href="#i-shield"/></svg>
      </div>
      <h3 style="margin-bottom: 0.5rem;">
        {{ locale === 'ar' ? 'لم يتم تكوين برنامج تشغيلي تجريبي بعد' : 'No Operational Pilot Initialized Yet' }}
      </h3>
      <p class="muted" style="max-width: 520px; margin: 0 auto 1.5rem auto;">
        {{ locale === 'ar' ? 'قم بإعداد برنامج الدعم التشغيلي التجريبي لتحميل الحزمة الدلالية وحساب المقاييس ومراقبة الطوابير.' : 'Initialize the Support SLA pilot runbook to bootstrap semantic definitions, run synthetic batches, and monitor operational loop health.' }}
      </p>
      <NuxtLink to="/pilot/setup" class="btn btn-primary">
        {{ t('pilotCenter.setupLink', locale) }}
      </NuxtLink>
    </div>

    <!-- Live Pilot Command Center -->
    <div v-else>
      <!-- Live Pilot Banner -->
      <div class="panel" style="padding: 13px 18px; margin-bottom: 14px; border-inline-start: 4px solid var(--accent);">
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px;">
          <div>
            <div class="faint" style="font-family: var(--font-mono); font-size: 10px; text-transform: uppercase; letter-spacing: 0.1em;">
              ACTIVE OPERATIONAL PILOT
            </div>
            <div style="display: flex; align-items: center; gap: 8px; margin-top: 3px;">
              <h3 style="font-size: 15px; font-weight: 650; margin: 0; color: var(--fg-strong);">{{ pilot.name }}</h3>
              <span class="chip" data-tone="ok"><span class="d"></span>{{ pilot.status }}</span>
              <span class="chip" data-tone="warn"><span class="d"></span>INTERNAL EVALUATION ONLY</span>
            </div>
          </div>
          <div style="display: flex; gap: 18px; font-size: 12.5px; align-items: center;">
            <div><span class="muted">Domain:</span> <strong>{{ pilot.domain }}</strong> (<span class="mono">ticket_id</span>)</div>
            <div><span class="muted">Revision:</span> <strong class="mono">#{{ pilot.dataset_revision || 1 }}</strong></div>
          </div>
        </div>
      </div>

      <!-- High-Density KPI Strip -->
      <div class="kpi-band" role="group" aria-label="Key operational metrics">
        <NuxtLink to="/monitoring" class="kpi" data-tone="crit">
          <span class="k-label"><span class="mark"></span><span>Active Alerts</span></span>
          <span class="k-val"><span class="num isolate">{{ summary?.open_alerts ?? 0 }}</span></span>
          <span class="k-foot">
            <span class="k-delta up">{{ summary?.open_alerts > 0 ? 'Requires attention' : 'Normal range' }}</span>
          </span>
        </NuxtLink>

        <NuxtLink to="/risk" class="kpi" data-tone="warn">
          <span class="k-label"><span class="mark"></span><span>At-Risk Cases (24h)</span></span>
          <span class="k-val"><span class="num isolate">{{ summary?.high_risk_cases ?? 0 }}</span></span>
          <span class="k-foot">
            <span class="k-delta flat">&ge; 50% breach probability</span>
          </span>
        </NuxtLink>

        <NuxtLink to="/investigations" class="kpi" data-tone="accent">
          <span class="k-label"><span class="mark"></span><span>Active Investigations</span></span>
          <span class="k-val"><span class="num isolate">{{ summary?.active_investigations ?? 0 }}</span></span>
          <span class="k-foot">
            <span class="k-delta down">Open root-cause cases</span>
          </span>
        </NuxtLink>

        <NuxtLink to="/decisions" class="kpi" data-tone="ok">
          <span class="k-label"><span class="mark"></span><span>Open Decisions</span></span>
          <span class="k-val"><span class="num isolate">{{ summary?.open_decisions ?? 0 }}</span></span>
          <span class="k-foot">
            <span class="k-delta down">{{ summary?.reviews_due ?? 0 }} reviews due</span>
          </span>
        </NuxtLink>
      </div>

      <!-- Telemetry Series -->
      <div class="panel" style="margin-bottom: 14px;">
        <div class="panel-head">
          <h2>Operational Telemetry</h2>
          <span class="sub">live pilot series</span>
        </div>
        <div class="empty" style="padding: 3.5rem 1.5rem;">
          <div class="e-ico">
            <svg><use href="#i-pulse"/></svg>
          </div>
          <h3>Awaiting telemetry</h3>
          <p class="muted">No telemetry captured yet — refresh the pilot after ingestion to build a series.</p>
          <button class="btn btn-primary btn-sm" style="margin-top: 10px;" @click="loadPilotSummary">
            <svg><use href="#i-pulse"/></svg>
            <span>Refresh pilot</span>
          </button>
        </div>
      </div>

      <!-- Executive Overview Operational Answers Panel -->
      <div class="panel">
        <div class="panel-head">
          <h2>Executive Operational Summary</h2>
          <span class="sub">Structured Synthesis</span>
        </div>
        <div class="panel-body">
          <div class="grid grid-2">
            <div style="padding: 12px 14px; background: var(--surface-2); border-radius: var(--r); border: 1px solid var(--border);">
              <h4 style="font-size: 13px; font-weight: 650; margin-bottom: 6px; color: var(--fg-strong);">
                1. What needs attention now?
              </h4>
              <p v-if="summary && summary.open_alerts > 0" style="font-size: 12.5px; margin: 0;">
                <strong style="color: var(--crit-ink);">{{ summary.open_alerts }} active alert episode(s)</strong> detected in queue backlog and SLA breach rates.
              </p>
              <p v-else class="muted" style="font-size: 12.5px; margin: 0;">
                No active alert episodes. Operations running within established tolerance thresholds.
              </p>
            </div>

            <div style="padding: 12px 14px; background: var(--surface-2); border-radius: var(--r); border: 1px solid var(--border);">
              <h4 style="font-size: 13px; font-weight: 650; margin-bottom: 6px; color: var(--fg-strong);">
                2. Which cases are at risk?
              </h4>
              <p v-if="summary && summary.high_risk_cases > 0" style="font-size: 12.5px; margin: 0;">
                <strong style="color: var(--warn-ink);">{{ summary.high_risk_cases }} open case(s)</strong> classified as High Risk (&ge; 50% breach probability within 24h).
              </p>
              <p v-else class="muted" style="font-size: 12.5px; margin: 0;">
                No high-risk cases flagged by evaluation models.
              </p>
            </div>

            <div style="padding: 12px 14px; background: var(--surface-2); border-radius: var(--r); border: 1px solid var(--border);">
              <h4 style="font-size: 13px; font-weight: 650; margin-bottom: 6px; color: var(--fg-strong);">
                3. What decisions are open &amp; due for review?
              </h4>
              <p v-if="summary" style="font-size: 12.5px; margin: 0;">
                <strong>{{ summary.open_decisions }} open decision(s)</strong>, with <strong>{{ summary.reviews_due }} due for review</strong>.
              </p>
            </div>

            <div style="padding: 12px 14px; background: var(--surface-2); border-radius: var(--r); border: 1px solid var(--border);">
              <h4 style="font-size: 13px; font-weight: 650; margin-bottom: 6px; color: var(--fg-strong);">
                4. What outcomes have been observed?
              </h4>
              <p v-if="summary && summary.completed_reviews > 0" style="font-size: 12.5px; margin: 0;">
                <strong style="color: var(--ok-ink);">{{ summary.completed_reviews }} decision review(s)</strong> completed with recorded baseline vs observed comparisons.
              </p>
              <p v-else class="muted" style="font-size: 12.5px; margin: 0;">
                No decision outcomes evaluated yet in this pilot lifecycle.
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useLocale, t } from '~/composables/locale'

const { locale } = useLocale()
const { get } = useApi()

const pilot = ref<any>(null)
const summary = ref<any>(null)
const loading = ref(true)

async function loadPilotSummary() {
  loading.value = true
  try {
    const pilots = await get<any[]>('/pilots')
    if (Array.isArray(pilots) && pilots.length > 0) {
      pilot.value = pilots[0]
      const sumRes = await get<any>(`/pilots/${pilot.value.id}/summary`)
      summary.value = sumRes.summary
    } else {
      // Auto bootstrap if none exist
      await get<any>('/pilots/semantic-pack')
      const refreshed = await get<any[]>('/pilots')
      if (Array.isArray(refreshed) && refreshed.length > 0) {
        pilot.value = refreshed[0]
        const sumRes = await get<any>(`/pilots/${pilot.value.id}/summary`)
        summary.value = sumRes.summary
      }
    }
  } catch {
    // fallback defaults
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadPilotSummary()
})
</script>

<style scoped>
.pilot-page { display: flex; flex-direction: column; gap: 0; }
.page-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; margin-bottom: 20px; flex-wrap: wrap; }
.eyebrow { font-family: var(--font-mono); font-size: 10.5px; letter-spacing: 0.14em; text-transform: uppercase; color: var(--faint); margin-bottom: 6px; }
.page-head h1 { font-size: 20px; font-weight: 650; letter-spacing: -0.02em; color: var(--fg-strong); line-height: 1.2; }
.page-head .desc { font-size: 13px; color: var(--muted); margin-top: 4px; max-width: 68ch; }
.page-head .actions { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.chart-wrap { position: relative; }
.chart-svg { width: 100%; height: auto; display: block; }
</style>
