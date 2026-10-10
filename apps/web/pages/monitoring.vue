<template>
  <div class="monitoring-page">
    <div class="page-head">
      <div class="titles">
        <div class="eyebrow">Continuous Signal</div>
        <h1>Monitoring &amp; Alerts</h1>
        <p class="desc">Data health, contextual anomaly detection, and alert lifecycle (spec §14).</p>
      </div>
      <div class="actions">
        <button class="btn btn-secondary btn-sm" @click="refreshAll">
          <svg><use href="#i-pulse"/></svg>
          <span>Refresh</span>
        </button>
      </div>
    </div>

    <!-- Segmented Navigation Tabs -->
    <div class="segmented" style="margin-bottom: 16px;">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        type="button"
        :aria-pressed="activeTab === tab.id"
        @click="activeTab = tab.id"
      >
        {{ tab.label }}
      </button>
    </div>

    <!-- Data Health Tab -->
    <div v-if="activeTab === 'health'">
      <div v-if="healthLoading" class="loading">Loading health status...</div>
      <div v-else-if="healthError" class="error-banner">{{ healthError }}</div>
      <div v-else class="grid grid-2">
        <div v-for="ds in healthData" :key="ds.dataset_id" class="panel">
          <div class="panel-head">
            <h3 class="mono isolate" style="font-size: 13.5px; margin: 0;">{{ ds.dataset_id }}</h3>
            <span class="chip" :data-tone="healthBadgeTone(ds.status)">
              <span class="d"></span>
              {{ ds.status }}
            </span>
          </div>
          <div class="panel-body">
            <div class="kv" style="display: grid; grid-template-columns: 140px 1fr; gap: 6px 12px; font-size: 12.5px;">
              <span class="muted">Freshness:</span>
              <span class="isolate mono">{{ ds.freshness_hours != null ? ds.freshness_hours + 'h' : '—' }}</span>
              <span class="muted">Revisions:</span>
              <span class="isolate mono">{{ ds.revision_count }}</span>
              <span class="muted">Latest Revision:</span>
              <span class="isolate mono">#{{ ds.latest_revision }}</span>
              <span class="muted">Last Ingested:</span>
              <span class="faint">{{ ds.last_ingested_at ? formatDate(ds.last_ingested_at) : '—' }}</span>
            </div>
          </div>
        </div>
        <p v-if="healthData.length === 0" class="muted">No datasets found.</p>
      </div>
    </div>

    <!-- Alert Rules Tab -->
    <div v-if="activeTab === 'rules'">
      <div style="margin-bottom: 12px; display: flex; justify-content: flex-end;">
        <button class="btn btn-secondary btn-sm" @click="showNewRuleForm = !showNewRuleForm">
          {{ showNewRuleForm ? 'Cancel' : '+ New Rule' }}
        </button>
      </div>

      <!-- New Rule Form Panel -->
      <div v-if="showNewRuleForm" class="panel" style="margin-bottom: 16px;">
        <div class="panel-head">
          <h3>Create Alert Rule</h3>
        </div>
        <div class="panel-body">
          <div class="grid grid-3">
            <label class="field">
              <span>Rule Name</span>
              <input v-model="newRule.name" class="input" placeholder="e.g. First-response SLA" />
            </label>
            <label class="field">
              <span>Dataset ID</span>
              <input v-model="newRule.dataset_id" class="input" placeholder="dataset id" />
            </label>
            <label class="field">
              <span>Metric ID</span>
              <input v-model="newRule.metric_id" class="input" placeholder="metric id" />
            </label>
          </div>
          <div class="grid grid-3" style="margin-top: 10px;">
            <label class="field">
              <span>Method</span>
              <select v-model="newRule.method" class="select">
                <option value="seasonal_naive">seasonal_naive</option>
                <option value="residual_detection">residual_detection</option>
              </select>
            </label>
            <label class="field">
              <span>Threshold</span>
              <input v-model.number="newRule.threshold" class="input" type="number" step="0.1" />
            </label>
            <label class="field">
              <span>Persistence</span>
              <input v-model.number="newRule.persistence" class="input" type="number" min="1" />
            </label>
          </div>
          <div style="display: flex; gap: 10px; align-items: center; margin-top: 14px;">
            <button class="btn btn-primary btn-sm" @click="createRule">Create Rule</button>
            <span v-if="ruleError" style="color: var(--crit-ink); font-size: 12px;">{{ ruleError }}</span>
          </div>
        </div>
      </div>

      <div v-if="rulesLoading" class="loading">Loading rules...</div>
      <div v-else class="grid grid-2">
        <div v-for="rule in rules" :key="rule.id" class="panel">
          <div class="panel-head">
            <h3 style="font-size: 13.5px; margin: 0;">{{ rule.name }}</h3>
            <span class="chip" :data-tone="rule.enabled ? 'ok' : ''">
              <span class="d"></span>
              {{ rule.enabled ? 'Enabled' : 'Disabled' }}
            </span>
          </div>
          <div class="panel-body" style="font-size: 12.5px;">
            <div style="margin-bottom: 8px;">
              <span class="muted">Dataset:</span> <code class="isolate">{{ rule.dataset_id }}</code> &middot;
              <span class="muted">Metric:</span> <code class="isolate">{{ rule.metric_id }}</code> &middot;
              <span class="muted">Threshold:</span> <strong class="mono isolate">{{ rule.threshold }}</strong>
            </div>
            <div class="row" style="margin-top: 12px; gap: 8px;">
              <button class="btn btn-secondary btn-xs" @click="toggleRule(rule)">
                {{ rule.enabled ? 'Disable' : 'Enable' }}
              </button>
              <button class="btn btn-primary btn-xs" @click="evaluateRule(rule.id)">
                Evaluate Now
              </button>
            </div>
          </div>
        </div>
        <p v-if="rules.length === 0" class="muted">No rules defined. Create one above.</p>
      </div>
    </div>

    <!-- Active Episodes Tab -->
    <div v-if="activeTab === 'episodes'">
      <div v-if="episodesLoading" class="loading">Loading episodes...</div>
      <div v-else class="grid grid-2">
        <div v-for="ep in episodeList" :key="ep.id" class="panel">
          <div class="panel-head">
            <strong class="mono isolate">Episode {{ ep.id.substring(0, 8) }}…</strong>
            <span class="chip" :data-tone="episodeBadgeTone(ep.workflow_status)">
              <span class="d"></span>
              {{ ep.workflow_status }}
            </span>
          </div>
          <div class="panel-body">
            <div class="kv" style="display: grid; grid-template-columns: 130px 1fr; gap: 5px 12px; font-size: 12px;">
              <span class="muted">Rule:</span> <span class="mono isolate">{{ ep.rule_id.substring(0, 8) }}…</span>
              <span class="muted">Observed Value:</span> <strong class="mono isolate">{{ ep.observed_value }}</strong>
              <span class="muted">Expected Range:</span> <span class="mono isolate">[{{ ep.expected_lower }}, {{ ep.expected_upper }}]</span>
              <span class="muted">Scoring Method:</span> <span>{{ ep.scoring_method }}</span>
              <span class="muted">Started:</span> <span class="faint">{{ formatDate(ep.started_at) }}</span>
            </div>

            <div v-if="canTransition(ep.workflow_status)" class="row" style="margin-top: 12px; gap: 6px;">
              <button class="btn btn-primary btn-xs" @click="launchInvestigation(ep.id)">
                Launch Investigation
              </button>
              <button v-if="ep.workflow_status === 'open'" class="btn btn-secondary btn-xs" @click="transitionEpisode(ep.id, 'acknowledged')">
                Acknowledge
              </button>
              <button v-if="ep.workflow_status === 'acknowledged'" class="btn btn-secondary btn-xs" @click="transitionEpisode(ep.id, 'investigating')">
                Investigate
              </button>
              <button v-if="ep.workflow_status !== 'resolved' && ep.workflow_status !== 'dismissed'" class="btn btn-secondary btn-xs" @click="transitionEpisode(ep.id, 'resolved')">
                Resolve
              </button>
              <button v-if="ep.workflow_status !== 'dismissed' && ep.workflow_status !== 'resolved'" class="btn btn-ghost btn-xs" @click="transitionEpisode(ep.id, 'dismissed')">
                Dismiss
              </button>
            </div>
          </div>
        </div>
        <p v-if="episodeList.length === 0" class="muted">No active alert episodes.</p>
      </div>
    </div>

    <!-- History Tab -->
    <div v-if="activeTab === 'history'">
      <div v-if="historyLoading" class="loading">Loading history...</div>
      <div v-else class="grid grid-2">
        <div v-for="ep in historyList" :key="ep.id" class="panel">
          <div class="panel-head">
            <strong class="mono isolate">Episode {{ ep.id.substring(0, 8) }}…</strong>
            <span class="chip" :data-tone="episodeBadgeTone(ep.workflow_status)">
              <span class="d"></span>
              {{ ep.workflow_status }}
            </span>
          </div>
          <div class="panel-body">
            <div class="kv" style="display: grid; grid-template-columns: 130px 1fr; gap: 5px 12px; font-size: 12px;">
              <span class="muted">Rule:</span> <span class="mono isolate">{{ ep.rule_id.substring(0, 8) }}…</span>
              <span class="muted">Observed Value:</span> <strong class="mono isolate">{{ ep.observed_value }}</strong>
              <span class="muted">Started:</span> <span class="faint">{{ formatDate(ep.started_at) }}</span>
              <span v-if="ep.resolved_at" class="muted">Resolved:</span>
              <span v-if="ep.resolved_at" class="faint">{{ formatDate(ep.resolved_at) }}</span>
            </div>
          </div>
        </div>
        <p v-if="historyList.length === 0" class="muted">No resolved or dismissed episodes.</p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import type {
  MonitoringHealthDataset,
  MonitoringAlertRule,
  MonitoringAlertEpisode,
  MonitoringCreateRuleRequest,
  Investigation,
} from '~/shared/types'

const { get, post } = useApi()
const put = <T>(path: string, body?: unknown) =>
  useApi().call<T>(path, {
    method: 'PUT',
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })

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
const healthData = ref<MonitoringHealthDataset[]>([])

// Rules
const rulesLoading = ref(false)
const rules = ref<MonitoringAlertRule[]>([])
const showNewRuleForm = ref(false)
const ruleError = ref('')
const newRule = ref<MonitoringCreateRuleRequest>({
  name: '',
  dataset_id: '',
  metric_id: '',
  method: 'seasonal_naive',
  threshold: 3.0,
  persistence: 1,
})

// Episodes
const episodesLoading = ref(false)
const episodeList = ref<MonitoringAlertEpisode[]>([])
const historyLoading = ref(false)
const historyList = ref<MonitoringAlertEpisode[]>([])

function healthBadgeTone(status: string): string {
  return ({ healthy: 'ok', stale: 'warn', suspended: 'crit', unknown: '' } as Record<string, string>)[status] || ''
}

function episodeBadgeTone(status: string): string {
  return ({
    open: 'warn',
    acknowledged: 'accent',
    investigating: 'warn',
    resolved: 'ok',
    dismissed: '',
  } as Record<string, string>)[status] || ''
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
    const data = await get<MonitoringHealthDataset[]>('/monitoring/health')
    healthData.value = Array.isArray(data) ? data : []
  } catch (e: unknown) {
    healthError.value = e instanceof Error ? e.message : 'Failed to load health data'
  } finally {
    healthLoading.value = false
  }
}

async function loadRules() {
  rulesLoading.value = true
  try {
    const data = await get<{ rules: MonitoringAlertRule[] }>('/monitoring/rules')
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
    await post('/monitoring/rules', newRule.value)
    showNewRuleForm.value = false
    newRule.value = { name: '', dataset_id: '', metric_id: '', method: 'seasonal_naive', threshold: 3.0, persistence: 1 }
    await loadRules()
  } catch (e: unknown) {
    ruleError.value = e instanceof Error ? e.message : 'Create failed'
  }
}

async function toggleRule(rule: MonitoringAlertRule) {
  try {
    await put(`/monitoring/rules/${rule.id}`, { enabled: !rule.enabled })
    await loadRules()
  } catch { /* ignore */ }
}

async function evaluateRule(ruleId: string) {
  try {
    await post('/monitoring/evaluate', { rule_ids: [ruleId] })
    await loadEpisodes()
  } catch { /* ignore */ }
}

async function loadEpisodes() {
  episodesLoading.value = true
  try {
    const data = await get<{ episodes: MonitoringAlertEpisode[] }>('/monitoring/episodes?status=open,acknowledged,investigating')
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
    const data = await get<{ episodes: MonitoringAlertEpisode[] }>('/monitoring/episodes?status=resolved,dismissed')
    historyList.value = data.episodes || []
  } catch {
    historyList.value = []
  } finally {
    historyLoading.value = false
  }
}

async function launchInvestigation(episodeId: string) {
  try {
    const inv = await post<Investigation>(`/monitoring/episodes/${episodeId}/investigate`)
    navigateTo(`/investigations/${inv.id}`)
  } catch (e: unknown) {
    alert(e instanceof Error ? e.message : 'Launch investigation failed')
  }
}

async function transitionEpisode(episodeId: string, status: string) {
  try {
    await put(`/monitoring/episodes/${episodeId}/status`, { status })
    await loadEpisodes()
    await loadHistory()
  } catch { /* ignore */ }
}

function refreshAll() {
  loadHealth()
  loadRules()
  loadEpisodes()
  loadHistory()
}

onMounted(() => {
  refreshAll()
})
</script>

<style scoped>
.monitoring-page { display: flex; flex-direction: column; gap: 0; }
.page-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; margin-bottom: 20px; flex-wrap: wrap; }
.eyebrow { font-family: var(--font-mono); font-size: 10.5px; letter-spacing: 0.14em; text-transform: uppercase; color: var(--faint); margin-bottom: 6px; }
.page-head h1 { font-size: 20px; font-weight: 650; letter-spacing: -0.02em; color: var(--fg-strong); line-height: 1.2; }
.page-head .desc { font-size: 13px; color: var(--muted); margin-top: 4px; max-width: 68ch; }
.page-head .actions { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
</style>