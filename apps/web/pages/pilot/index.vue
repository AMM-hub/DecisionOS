<template>
  <div class="page">
    <!-- Header -->
    <div class="header-row">
      <div>
        <h1>{{ t('pilotCenter.title', locale) }}</h1>
        <p class="muted">{{ t('pilotCenter.subtitle', locale) }}</p>
      </div>
      <div class="actions-row">
        <NuxtLink to="/pilot/setup" class="btn btn-primary">
          {{ t('pilotCenter.setupLink', locale) }}
        </NuxtLink>
      </div>
    </div>

    <!-- Loading / Empty State / Main Content -->
    <div v-if="loading" class="loading">{{ t('common.loading', locale) }}</div>
    <div v-else-if="!pilot" class="card empty-state text-center" style="padding: 3rem 1.5rem; text-align: center;">
      <div style="font-size: 2.5rem; margin-bottom: 0.75rem;">🚀</div>
      <h3 style="margin-bottom: 0.5rem;">{{ locale === 'ar' ? 'لم يتم تكوين برنامج تشغيلي تجريبي بعد' : 'No Operational Pilot Initialized Yet' }}</h3>
      <p class="muted" style="max-width: 500px; margin: 0 auto 1.5rem auto;">
        {{ locale === 'ar' ? 'قم بإعداد برنامج الدعم التشغيلي التجريبي لتحميل الحزمة الدلالية وحساب المقاييس ومراقبة الطوابير.' : 'Initialize the Support SLA pilot runbook to bootstrap semantic definitions, run synthetic batches, and monitor operational loop health.' }}
      </p>
      <NuxtLink to="/pilot/setup" class="btn btn-primary">
        {{ t('pilotCenter.setupLink', locale) }}
      </NuxtLink>
    </div>
    <div v-else>
      <!-- Security & Pilot Status Banner -->
      <div class="status-banner card margin-y">
        <div class="banner-grid">
          <div>
            <span class="muted text-xs">PILOT NAME</span>
            <h3>{{ pilot.name }}</h3>
            <span class="badge badge-green">{{ pilot.status }}</span>
          </div>
          <div>
            <span class="muted text-xs">DOMAIN & GRAIN</span>
            <p class="margin-0"><strong>{{ pilot.domain }}</strong> (ticket_id)</p>
            <span class="text-xs muted">Dataset Rev #{{ pilot.dataset_revision || 1 }}</span>
          </div>
          <div>
            <span class="muted text-xs">AUTHENTICATION & SECURITY GATE</span>
            <div class="margin-y">
              <span class="badge badge-warning">INTERNAL EVALUATION ONLY</span>
            </div>
            <p class="text-xs muted margin-0">Demo headers active. External customer pilot blocked until security gate resolution.</p>
          </div>
        </div>
      </div>

      <!-- Executive Summary Grid -->
      <div v-if="summary" class="grid kpi-grid margin-y">
        <NuxtLink to="/alerts" class="kpi-card card">
          <span class="kpi-label">Active Alerts</span>
          <span class="kpi-val danger-text bidi-ltr">{{ summary.open_alerts }}</span>
          <span class="kpi-sub muted">Requires immediate attention</span>
        </NuxtLink>

        <NuxtLink to="/predictive" class="kpi-card card">
          <span class="kpi-label">At-Risk Cases (24h SLA)</span>
          <span class="kpi-val warning-text bidi-ltr">{{ summary.high_risk_cases }}</span>
          <span class="kpi-sub muted">High SLA breach probability</span>
        </NuxtLink>

        <NuxtLink to="/investigations" class="kpi-card card">
          <span class="kpi-label">Active Investigations</span>
          <span class="kpi-val blue-text bidi-ltr">{{ summary.active_investigations }}</span>
          <span class="kpi-sub muted">Open root-cause cases</span>
        </NuxtLink>

        <NuxtLink to="/decisions" class="kpi-card card">
          <span class="kpi-label">Open / Active Decisions</span>
          <span class="kpi-val purple-text bidi-ltr">{{ summary.open_decisions }}</span>
          <span class="kpi-sub muted">Governed operational loop</span>
        </NuxtLink>

        <NuxtLink to="/decisions" class="kpi-card card">
          <span class="kpi-label">Decision Reviews Due</span>
          <span class="kpi-val orange-text bidi-ltr">{{ summary.reviews_due }}</span>
          <span class="kpi-sub muted">Pending outcome recording</span>
        </NuxtLink>

        <NuxtLink to="/decisions" class="kpi-card card">
          <span class="kpi-label">Evaluated Outcomes</span>
          <span class="kpi-val green-text bidi-ltr">{{ summary.completed_reviews }}</span>
          <span class="kpi-sub muted">Closed decision reviews</span>
        </NuxtLink>
      </div>

      <!-- Executive Overview Answers Section -->
      <div class="card margin-y">
        <h2>Executive Operational Summary</h2>
        <div class="answers-grid">
          <div class="answer-item">
            <h4>1. What needs attention now?</h4>
            <p v-if="summary && summary.open_alerts > 0">
              <strong>{{ summary.open_alerts }} active alert episode(s)</strong> detected in queue backlog and SLA breach rates.
            </p>
            <p v-else class="muted">No active alert episodes. Operations are running within threshold limits.</p>
          </div>

          <div class="answer-item">
            <h4>2. Which cases are at risk?</h4>
            <p v-if="summary && summary.high_risk_cases > 0">
              <strong>{{ summary.high_risk_cases }} open case(s)</strong> classified as High Risk (&ge; 50% breach probability within 24h).
            </p>
            <p v-else class="muted">No high-risk cases flagged by evaluation models.</p>
          </div>

          <div class="answer-item">
            <h4>3. What decisions are open & due for review?</h4>
            <p v-if="summary">
              <strong>{{ summary.open_decisions }} open decision(s)</strong>, with <strong>{{ summary.reviews_due }} due for review</strong>.
            </p>
          </div>

          <div class="answer-item">
            <h4>4. What outcomes have been observed?</h4>
            <p v-if="summary && summary.completed_reviews > 0">
              <strong>{{ summary.completed_reviews }} decision review(s)</strong> completed with recorded baseline vs observed comparisons.
            </p>
            <p v-else class="muted">No decision outcomes evaluated yet in this pilot lifecycle.</p>
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
      const bootRes = await get<any>('/pilots/semantic-pack')
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
.page { max-width: 1100px; margin: 0 auto; padding: 1rem; }
.header-row { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 1rem; }
.actions-row { display: flex; gap: 0.5rem; }
.status-banner { background: #f8fafc; border-left: 4px solid #0284c7; padding: 1rem; }
.banner-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 1rem; }
.kpi-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 1rem; }
.kpi-card { text-decoration: none; color: inherit; display: flex; flex-direction: column; padding: 1rem; transition: transform 0.15s ease; }
.kpi-card:hover { transform: translateY(-2px); border-color: #cbd5e1; }
.kpi-label { font-size: 0.85rem; color: #64748b; font-weight: 600; }
.kpi-val { font-size: 2rem; font-weight: 700; margin: 0.25rem 0; }
.kpi-sub { font-size: 0.8rem; }
.danger-text { color: #dc2626; }
.warning-text { color: #d97706; }
.blue-text { color: #0284c7; }
.purple-text { color: #7c3aed; }
.orange-text { color: #ea580c; }
.green-text { color: #16a34a; }
.answers-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1.25rem; margin-top: 1rem; }
.answer-item { background: #f8fafc; padding: 1rem; border-radius: 6px; border: 1px solid #e2e8f0; }
.answer-item h4 { margin-top: 0; margin-bottom: 0.5rem; color: #1e293b; font-size: 0.95rem; }
.answer-item p { margin: 0; font-size: 0.9rem; }
.badge-warning { background: #fef3c7; color: #92400e; border: 1px solid #fde68a; }
.badge-green { background: #dcfce7; color: #166534; }
</style>
