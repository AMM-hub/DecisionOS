<template>
  <div class="page">
    <h1>Monitoring & Alerts</h1>
    <p class="muted">Data health, contextual anomaly detection, and alert lifecycle (spec §14).</p>

    <div class="tabs">
      <button v-for="tab in tabs" :key="tab.id" :class="{ active: activeTab === tab.id }"
              @click="activeTab = tab.id">{{ tab.label }}</button>
    </div>

    <!-- Data Health Tab -->
    <div v-if="activeTab === 'health'" class="tab-content">
      <div v-if="healthLoading" class="loading">Loading health status...</div>
      <div v-else-if="healthError" class="error-banner">{{ healthError }}</div>
      <div v-else>
        <div v-for="ds in healthData" :key="ds.dataset_id" class="card">
          <div class="card-header">
            <strong>{{ ds.dataset_id }}</strong>
            <span :class="'badge badge-' + healthBadgeClass(ds.status)">{{ ds.status }}</span>
          </div>
          <div class="card-body">
            <table class="meta-table">
              <tr><td>Freshness</td><td>{{ ds.freshness_hours != null ? ds.freshness_hours + 'h' : '—' }}</td></tr>
              <tr><td>Revisions</td><td>{{ ds.revision_count }}</td></tr>
              <tr><td>Latest</td><td>#{{ ds.latest_revision }}</td></tr>
              <tr><td>Last Ingested</td><td>{{ ds.last_ingested_at ? formatDate(ds.last_ingested_at) : '—' }}</td></tr>
            </table>
          </div>
        </div>
        <p v-if="healthData.length === 0" class="muted">No datasets found.</p>
      </div>
    </div>

    <!-- Alert Rules Tab -->
    <div v-if="activeTab === 'rules'" class="tab-content">
      <button class="btn btn-sm" @click="showNewRuleForm = !showNewRuleForm">
        {{ showNewRuleForm ? 'Cancel' : '+ New Rule' }}
      </button>

      <div v-if="showNewRuleForm" class="card rule-form">
        <h3>Create Alert Rule</h3>
        <div class="form-row">
          <label>Name <input v-model="newRule.name" placeholder="e.g. First-response SLA" /></label>
          <label>Dataset ID <input v-model="newRule.dataset_id" placeholder="dataset id" /></label>
          <label>Metric ID <input v-model="newRule.metric_id" placeholder="metric id" /></label>
        </div>
        <div class="form-row">
          <label>Method <select v-model="newRule.method">
            <option>seasonal_naive</option>
            <option>residual_detection</option>
          </select></label>
          <label>Threshold <input v-model.number="newRule.threshold" type="number" step="0.1" /></label>
          <label>Persistence <input v-model.number="newRule.persistence" type="number" min="1" /></label>
        </div>
        <button class="btn" @click="createRule">Create</button>
        <span v-if="ruleError" class="error-text">{{ ruleError }}</span>
      </div>

      <div v-if="rulesLoading" class="loading">Loading rules...</div>
      <div v-else>
        <div v-for="rule in rules" :key="rule.id" class="card">
          <div class="card-header">
            <strong>{{ rule.name }}</strong>
            <span :class="'badge badge-' + (rule.enabled ? 'green' : 'gray')">
              {{ rule.enabled ? 'Enabled' : 'Disabled' }}
            </span>
          </div>
          <div class="card-body">
            <span class="muted">Dataset:</span> {{ rule.dataset_id }} &middot;
            <span class="muted">Metric:</span> {{ rule.metric_id }} &middot;
            <span class="muted">Method:</span> {{ rule.method }} &middot;
            <span class="muted">Threshold:</span> {{ rule.threshold }} &middot;
            <span class="muted">Owner:</span> {{ rule.owner }}
            <div class="actions">
              <button class="btn btn-xs" @click="toggleRule(rule)">{{ rule.enabled ? 'Disable' : 'Enable' }}</button>
              <button class="btn btn-xs" @click="evaluateRule(rule.id)">Evaluate</button>
            </div>
          </div>
        </div>
        <p v-if="rules.length === 0" class="muted">No rules defined. Create one above.</p>
      </div>
    </div>

    <!-- Active Episodes Tab -->
    <div v-if="activeTab === 'episodes'" class="tab-content">
      <div v-if="episodesLoading" class="loading">Loading episodes...</div>
      <div v-else>
        <div v-for="ep in episodeList" :key="ep.id" class="card">
          <div class="card-header">
            <strong>Episode {{ ep.id.substring(0, 8) }}…</strong>
            <span :class="'badge badge-' + episodeBadgeClass(ep.workflow_status)">{{ ep.workflow_status }}</span>
          </div>
          <div class="card-body">
            <table class="meta-table">
              <tr><td>Rule</td><td>{{ ep.rule_id.substring(0, 8) }}…</td></tr>
              <tr><td>Observed</td><td>{{ ep.observed_value }}</td></tr>
              <tr><td>Expected Range</td><td>[{{ ep.expected_lower }}, {{ ep.expected_upper }}]</td></tr>
              <tr><td>Method</td><td>{{ ep.scoring_method }}</td></tr>
              <tr><td>Effect Size</td><td>{{ ep.effect_size }}</td></tr>
              <tr><td>Started</td><td>{{ formatDate(ep.started_at) }}</td></tr>
            </table>
            <div v-if="canTransition(ep.workflow_status)" class="actions">
              <button v-if="ep.workflow_status === 'open'" class="btn btn-xs"
                      @click="transitionEpisode(ep.id, 'acknowledged')">Acknowledge</button>
              <button v-if="ep.workflow_status === 'acknowledged'" class="btn btn-xs"
                      @click="transitionEpisode(ep.id, 'investigating')">Investigate</button>
              <button v-if="ep.workflow_status !== 'resolved' && ep.workflow_status !== 'dismissed'" class="btn btn-xs"
                      @click="transitionEpisode(ep.id, 'resolved')">Resolve</button>
              <button v-if="ep.workflow_status !== 'dismissed' && ep.workflow_status !== 'resolved'" class="btn btn-xs"
                      @click="transitionEpisode(ep.id, 'dismissed')">Dismiss</button>
            </div>
          </div>
        </div>
        <p v-if="episodeList.length === 0" class="muted">No active episodes.</p>
      </div>
    </div>

    <!-- History Tab -->
    <div v-if="activeTab === 'history'" class="tab-content">
      <div v-if="historyLoading" class="loading">Loading history...</div>
      <div v-else>
        <div v-for="ep in historyList" :key="ep.id" class="card">
          <div class="card-header">
            <strong>Episode {{ ep.id.substring(0, 8) }}…</strong>
            <span :class="'badge badge-' + episodeBadgeClass(ep.workflow_status)">{{ ep.workflow_status }}</span>
          </div>
          <div class="card-body">
            <table class="meta-table">
              <tr><td>Rule</td><td>{{ ep.rule_id.substring(0, 8) }}…</td></tr>
              <tr><td>Observed</td><td>{{ ep.observed_value }}</td></tr>
              <tr><td>Started</td><td>{{ formatDate(ep.started_at) }}</td></tr>
              <tr v-if="ep.resolved_at"><td>Resolved</td><td>{{ formatDate(ep.resolved_at) }}</td></tr>
            </table>
          </div>
        </div>
        <p v-if="historyList.length === 0" class="muted">No resolved/dismissed episodes.</p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'

const tabs = [
  { id: 'health', label: 'Data Health' },
  { id: 'rules', label: 'Alert Rules' },
  { id: 'episodes', label: 'Active Episodes' },
  { id: 'history', label: 'History' },
]
const activeTab = ref('health')

// Health
const healthLoading = ref(false)
const healthError = ref('')
const healthData = ref<any[]>([])

// Rules
const rulesLoading = ref(false)
const rules = ref<any[]>([])
const showNewRuleForm = ref(false)
const ruleError = ref('')
const newRule = ref({
  name: '',
  dataset_id: '',
  metric_id: '',
  method: 'seasonal_naive',
  threshold: 3.0,
  persistence: 1,
})

// Episodes
const episodesLoading = ref(false)
const episodeList = ref<any[]>([])
const historyLoading = ref(false)
const historyList = ref<any[]>([])

function healthBadgeClass(status: string): string {
  return { healthy: 'green', stale: 'yellow', suspended: 'red', unknown: 'gray' }[status] || 'gray'
}

function episodeBadgeClass(status: string): string {
  return {
    open: 'yellow',
    acknowledged: 'blue',
    investigating: 'orange',
    resolved: 'green',
    dismissed: 'gray',
  }[status] || 'gray'
}

function canTransition(status: string): boolean {
  return ['open', 'acknowledged', 'investigating'].includes(status)
}

function formatDate(iso: string): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return iso
  }
}

async function loadHealth() {
  healthLoading.value = true
  healthError.value = ''
  try {
    const res = await fetch('/v1/monitoring/health', {
      headers: { 'X-Tenant': 'tenant_alpha', 'X-User': 'alpha.manager' },
    })
    if (!res.ok) { healthError.value = `HTTP ${res.status}`; return }
    const data = await res.json()
    healthData.value = Array.isArray(data) ? data : []
  } catch (e: any) {
    healthError.value = e.message || 'Failed to load health data'
  } finally {
    healthLoading.value = false
  }
}

async function loadRules() {
  rulesLoading.value = true
  try {
    const res = await fetch('/v1/monitoring/rules', {
      headers: { 'X-Tenant': 'tenant_alpha', 'X-User': 'alpha.manager' },
    })
    const data = await res.json()
    rules.value = data.rules || []
  } catch {
    rules.value = []
  } finally {
    rulesLoading.value = false
  }
}

async function createRule() {
  ruleError.value = ''
  try {
    const res = await fetch('/v1/monitoring/rules', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Tenant': 'tenant_alpha', 'X-User': 'alpha.manager' },
      body: JSON.stringify(newRule.value),
    })
    if (!res.ok) { ruleError.value = `HTTP ${res.status}`; return }
    showNewRuleForm.value = false
    newRule.value = { name: '', dataset_id: '', metric_id: '', method: 'seasonal_naive', threshold: 3.0, persistence: 1 }
    await loadRules()
  } catch (e: any) {
    ruleError.value = e.message || 'Create failed'
  }
}

async function toggleRule(rule: any) {
  try {
    await fetch(`/v1/monitoring/rules/${rule.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', 'X-Tenant': 'tenant_alpha', 'X-User': 'alpha.manager' },
      body: JSON.stringify({ enabled: !rule.enabled }),
    })
    await loadRules()
  } catch { /* ignore */ }
}

async function evaluateRule(ruleId: string) {
  try {
    await fetch('/v1/monitoring/evaluate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Tenant': 'tenant_alpha', 'X-User': 'alpha.manager' },
      body: JSON.stringify({ rule_ids: [ruleId] }),
    })
    await loadEpisodes()
  } catch { /* ignore */ }
}

async function loadEpisodes() {
  episodesLoading.value = true
  try {
    const res = await fetch('/v1/monitoring/episodes?status=open,acknowledged,investigating', {
      headers: { 'X-Tenant': 'tenant_alpha', 'X-User': 'alpha.manager' },
    })
    const data = await res.json()
    episodeList.value = data.episodes || []
  } catch {
    episodeList.value = []
  } finally {
    episodesLoading.value = false
  }
}

async function loadHistory() {
  historyLoading.value = true
  try {
    const res = await fetch('/v1/monitoring/episodes?status=resolved,dismissed', {
      headers: { 'X-Tenant': 'tenant_alpha', 'X-User': 'alpha.manager' },
    })
    const data = await res.json()
    historyList.value = data.episodes || []
  } catch {
    historyList.value = []
  } finally {
    historyLoading.value = false
  }
}

async function transitionEpisode(episodeId: string, status: string) {
  try {
    await fetch(`/v1/monitoring/episodes/${episodeId}/status`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', 'X-Tenant': 'tenant_alpha', 'X-User': 'alpha.manager' },
      body: JSON.stringify({ status }),
    })
    await loadEpisodes()
    await loadHistory()
  } catch { /* ignore */ }
}

onMounted(() => {
  loadHealth()
  loadRules()
  loadEpisodes()
  loadHistory()
})
</script>

<style scoped>
/* Minimal scoped styles; global card/badge/form styles come from app.vue layout */
.page { padding: 1rem; max-width: 1200px; margin: auto; }
h1 { font-size: 1.5rem; margin-top: 0; }
.muted { color: #888; }
.tabs { display: flex; gap: 0.5rem; margin: 1rem 0; }
.tabs button { background: #222; color: #ccc; border: 1px solid #444; padding: 0.4rem 1rem; cursor: pointer; }
.tabs button.active { background: #335; color: #fff; border-color: #669; }
.tab-content { margin-top: 0.5rem; }
.card { background: #1e1e2e; border: 1px solid #333; border-radius: 6px; margin-bottom: 0.5rem; overflow: hidden; }
.card-header { display: flex; align-items: center; gap: 0.75rem; padding: 0.5rem 0.75rem; background: #2a2a3a; }
.card-body { padding: 0.5rem 0.75rem; color: #ccc; }
.badge { display: inline-block; font-size: 0.75rem; padding: 0.15rem 0.5rem; border-radius: 4px; font-weight: 600; }
.badge-green { background: #1a4; color: #fff; }
.badge-yellow { background: #b82; color: #000; }
.badge-red { background: #c33; color: #fff; }
.badge-gray { background: #555; color: #ccc; }
.badge-blue { background: #36a; color: #fff; }
.badge-orange { background: #d75; color: #000; }
.meta-table { width: 100%; font-size: 0.85rem; }
.meta-table td:first-child { color: #888; padding-right: 0.75rem; }
.loading { color: #888; font-style: italic; }
.error-banner { background: #3a1a1a; color: #e55; padding: 0.5rem; border-radius: 4px; }
.error-text { color: #e55; margin-left: 0.5rem; }
.actions { display: flex; gap: 0.4rem; margin-top: 0.4rem; }
.btn { background: #335; color: #eee; border: 1px solid #557; padding: 0.3rem 0.75rem; border-radius: 4px; cursor: pointer; }
.btn-sm { composes: btn; font-size: 0.8rem; }
.btn-xs { composes: btn; font-size: 0.75rem; padding: 0.2rem 0.5rem; }
.rule-form { padding: 0.75rem; }
.form-row { display: flex; gap: 0.75rem; margin-bottom: 0.4rem; flex-wrap: wrap; }
.form-row label { display: flex; flex-direction: column; font-size: 0.8rem; color: #888; }
.form-row input, .form-row select { background: #222; color: #ddd; border: 1px solid #444; padding: 0.25rem; }
</style>