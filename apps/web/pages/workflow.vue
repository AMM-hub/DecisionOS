<script setup lang="ts">
import type {
  Dataset,
  WorkflowBottleneckResponse,
  WorkflowVariantResponse,
  WorkflowConformanceResponse,
  WorkflowCaseMetricsResponse,
  WorkflowThroughputResponse
} from '~/shared/types'

const { get, post } = useApi()

const datasets = ref<Dataset[]>([])
const loading = ref(false)
const busy = ref(false)
const error = ref<string | null>(null)
const tab = ref<'bottlenecks' | 'variants' | 'conformance' | 'cases' | 'throughput'>('bottlenecks')

const form = reactive({
  dataset_id: '',
  case_id_col: 'case_id',
  event_col: 'event_type',
  timestamp_col: 'occurred_at',
  attributes: '',
  unit: 'hours',
  sla_hours: 48,
  top: 5,
})

const bottlenecks = ref<WorkflowBottleneckResponse | null>(null)
const variants = ref<WorkflowVariantResponse | null>(null)
const conformance = ref<WorkflowConformanceResponse | null>(null)
const caseMetrics = ref<WorkflowCaseMetricsResponse | null>(null)
const throughput = ref<WorkflowThroughputResponse | null>(null)

// Dummy conformance rules for demo
const rulesText = ref(`created → assigned
assigned → customer_reply
assigned → agent_note
customer_reply → assigned
customer_reply → agent_note
agent_note → assigned
agent_note → customer_reply
agent_note → resolved
assigned → resolved`)

async function loadDatasets() {
  loading.value = true
  try { datasets.value = await get<Dataset[]>('/datasets') }
  catch (e) { error.value = e instanceof Error ? e.message : String(e) }
  finally { loading.value = false }
}
onMounted(loadDatasets)

function payload() {
  const p: Record<string, unknown> = {
    dataset_id: form.dataset_id,
    case_id_col: form.case_id_col,
    event_col: form.event_col,
    timestamp_col: form.timestamp_col,
    unit: form.unit,
  }
  if (form.attributes) p.attributes = form.attributes.split(',').map((s: string) => s.trim()).filter(Boolean)
  return p
}

async function run() {
  busy.value = true; error.value = null
  try {
    switch (tab.value) {
      case 'bottlenecks':
        bottlenecks.value = await post<WorkflowBottleneckResponse>('/workflow/bottlenecks', payload())
        break
      case 'variants':
        variants.value = await post<WorkflowVariantResponse>('/workflow/variants', { ...payload(), top: Number(form.top) })
        break
      case 'conformance':
        conformance.value = await post<WorkflowConformanceResponse>('/workflow/conformance', {
          ...payload(), expected_rules: parseRules(rulesText.value)
        })
        break
      case 'cases':
        caseMetrics.value = await post<WorkflowCaseMetricsResponse>('/workflow/case-metrics', {
          ...payload(), sla_hours: Number(form.sla_hours)
        })
        break
      case 'throughput':
        throughput.value = await post<WorkflowThroughputResponse>('/workflow/throughput', payload())
        break
    }
  } catch (e) { error.value = e instanceof Error ? e.message : String(e) }
  finally { busy.value = false }
}

function parseRules(text: string): Array<{ from_activity: string; to_activity: string }> {
  return text.split('\n')
    .map((l: string) => l.trim())
    .filter(Boolean)
    .map((l: string) => {
      const m = l.match(/^(\S+)\s*[→➡]->?\s*(\S+)$/)
      return m ? { from_activity: m[1], to_activity: m[2] } : null
    })
    .filter(Boolean) as Array<{ from_activity: string; to_activity: string }>
}

function fmt(n: number | null | undefined): string {
  if (n == null) return '—'
  return Number(n).toFixed(2)
}

function pct(n: number): string {
  return (n * 100).toFixed(1) + '%'
}
</script>

<template>
  <section>
    <div class="row" style="justify-content: space-between">
      <h1>Workflow Analytics</h1>
      <button class="secondary" :disabled="loading" @click="loadDatasets">{{ loading ? 'Loading…' : 'Refresh datasets' }}</button>
    </div>
    <p class="muted">Process intelligence over event-history datasets — bottleneck detection, variant analysis, conformance checking, case SLA metrics, and throughput times (§15).</p>

    <div v-if="error" class="card"><span class="badge err">{{ error }}</span></div>

    <!-- Dataset & column mapping -->
    <div class="card">
      <label class="field">
        Dataset
        <select v-model="form.dataset_id">
          <option value="" disabled>Select a dataset…</option>
          <option v-for="d in datasets" :key="d.dataset_id" :value="d.dataset_id">{{ d.name }} ({{ d.dataset_id.slice(0, 8) }})</option>
        </select>
      </label>
      <div class="grid cols-3">
        <label class="field">
          Case ID column
          <input v-model="form.case_id_col" placeholder="case_id" />
        </label>
        <label class="field">
          Event column
          <input v-model="form.event_col" placeholder="event_type" />
        </label>
        <label class="field">
          Timestamp column
          <input v-model="form.timestamp_col" placeholder="occurred_at" />
        </label>
      </div>
      <div class="grid cols-2">
        <label class="field">
          Unit
          <select v-model="form.unit">
            <option value="hours">hours</option>
            <option value="minutes">minutes</option>
            <option value="days">days</option>
          </select>
        </label>
        <label class="field">
          Additional attribute columns (comma-separated)
          <input v-model="form.attributes" placeholder="agent_id, priority" />
        </label>
      </div>
    </div>

    <!-- Tabs -->
    <nav class="tabs" aria-label="Analysis tabs">
      <button :class="{ active: tab === 'bottlenecks' }" @click="tab = 'bottlenecks'">Bottlenecks</button>
      <button :class="{ active: tab === 'variants' }" @click="tab = 'variants'">Variants</button>
      <button :class="{ active: tab === 'conformance' }" @click="tab = 'conformance'">Conformance</button>
      <button :class="{ active: tab === 'cases' }" @click="tab = 'cases'">SLA Metrics</button>
      <button :class="{ active: tab === 'throughput' }" @click="tab = 'throughput'">Throughput</button>
    </nav>

    <button :disabled="!form.dataset_id || busy" @click="run" style="margin: 0.5rem 0">
      {{ busy ? 'Analysing…' : `Run ${tab === 'bottlenecks' ? 'Bottleneck' : tab === 'variants' ? 'Variant' : tab === 'conformance' ? 'Conformance' : tab === 'cases' ? 'SLA' : 'Throughput'} Analysis` }}
    </button>

    <!-- Tab content -->
    <div v-if="tab === 'bottlenecks' && bottlenecks" class="card">
      <h2>Bottlenecks <span class="badge">{{ bottlenecks.bottlenecks.length }} stages</span></h2>
      <p class="muted">Sorted by longest median duration first. Last events of each case have no exit timestamp → excluded from duration stats.</p>
      <table>
        <thead>
          <tr><th>Activity</th><th>Cases</th><th>Median ({{ form.unit }})</th><th>Avg</th><th>Wait time</th></tr>
        </thead>
        <tbody>
          <tr v-for="b in bottlenecks.bottlenecks" :key="b.activity" :class="{ highlight: b.count > 0 && b.median !== null }">
            <td><code>{{ b.activity }}</code></td>
            <td>{{ b.count }}</td>
            <td><strong>{{ fmt(b.median) }}</strong></td>
            <td>{{ fmt(b.avg) }}</td>
            <td class="muted">{{ fmt(b.waiting_time) }}</td>
          </tr>
        </tbody>
      </table>
      <p class="muted">Revision {{ bottlenecks.revision }} · evidence: <code>{{ bottlenecks.evidence_ref.slice(0, 12) }}…</code></p>
    </div>

    <div v-if="tab === 'variants' && variants" class="card">
      <h2>Process Variants <span class="badge">{{ variants.total_variants }} variants</span></h2>
      <p class="muted">Showing top {{ form.top }} variants of {{ variants.total_variants }} across {{ variants.total_cases }} cases.</p>
      <table>
        <thead>
          <tr><th>#</th><th>Cases</th><th>Frequency</th><th>Path</th></tr>
        </thead>
        <tbody>
          <tr v-for="(v, i) in variants.variants" :key="i">
            <td>{{ i + 1 }}</td>
            <td>{{ v.case_count }}</td>
            <td>{{ pct(v.frequency) }}</td>
            <td><code>{{ v.simplified_path.join(' → ') }}</code></td>
          </tr>
        </tbody>
      </table>
      <p v-if="variants.variants.length < variants.total_variants" class="muted">+ {{ variants.total_variants - variants.variants.length }} more variants</p>
    </div>

    <div v-if="tab === 'conformance' && conformance" class="card">
      <h2>Conformance</h2>
      <div class="grid cols-3">
        <div class="stat"><div class="n">{{ pct(conformance.fitness) }}</div><span class="muted">Fitness</span></div>
        <div class="stat"><div class="n">{{ pct(conformance.precision) }}</div><span class="muted">Precision</span></div>
        <div class="stat"><div class="n">{{ conformance.violated_cases }} / {{ conformance.total_cases }}</div><span class="muted">Violated cases</span></div>
      </div>
      <div v-if="conformance.example_violations.length" style="margin-top:0.5rem">
        <h3>Example violations</h3>
        <table>
          <thead><tr><th>Case</th><th>From</th><th>To</th></tr></thead>
          <tbody>
            <tr v-for="(v, i) in conformance.example_violations" :key="i">
              <td><code>{{ v.case_id }}</code></td>
              <td>{{ v.from }}</td>
              <td>{{ v.to }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="conformance.unknown_activities.length" style="margin-top:0.5rem">
        <h3>Unknown activities <span class="badge warn">{{ conformance.unknown_activities.length }}</span></h3>
        <p class="muted">These event types are not mentioned in the expected transition rules — preserved, never dropped.</p>
        <code>{{ conformance.unknown_activities.join(', ') }}</code>
      </div>
      <div style="margin-top:1rem">
        <label class="field">
          Expected transition rules (one per line, e.g. <code>created → assigned</code>)
          <textarea v-model="rulesText" rows="10" style="font-family: monospace; font-size: 0.85rem" />
        </label>
      </div>
    </div>

    <div v-if="tab === 'cases' && caseMetrics" class="card">
      <h2>Case SLA Metrics <span class="badge ok">{{ caseMetrics.summary.met }} met</span> <span class="badge warn">{{ caseMetrics.summary.in_progress }} in progress</span> <span class="badge err">{{ caseMetrics.summary.breached }} breached</span></h2>
      <p class="muted">{{ caseMetrics.summary.total_cases }} cases · SLA threshold: {{ caseMetrics.sla_hours }}h · as of {{ caseMetrics.as_of }}</p>
      <table>
        <thead>
          <tr><th>Case</th><th>Duration ({{ caseMetrics.unit }})</th><th>Age</th><th>Stages</th><th>Current</th><th>SLA</th></tr>
        </thead>
        <tbody>
          <tr v-for="c in caseMetrics.metrics" :key="c.case_id">
            <td><code>{{ c.case_id }}</code></td>
            <td>{{ fmt(c.duration) }}</td>
            <td>{{ fmt(c.age) }}</td>
            <td>{{ c.stage_count }}</td>
            <td><code>{{ c.current }}</code></td>
            <td>
              <span :class="['badge', c.sla_status === 'met' ? 'ok' : c.sla_status === 'breached' ? 'err' : 'warn']">{{ c.sla_status }}</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="tab === 'throughput' && throughput" class="card">
      <h2>Throughput <span class="badge">{{ throughput.stages.length }} stages</span></h2>
      <p class="muted">Time-in-stage (in {{ throughput.unit }}). Final event of each case excluded from time stats.</p>
      <table>
        <thead>
          <tr><th>Stage</th><th>Count</th><th>Min</th><th>Median</th><th>Max</th><th>P90</th><th>From</th><th>To</th></tr>
        </thead>
        <tbody>
          <tr v-for="s in throughput.stages" :key="s.stage">
            <td><code>{{ s.stage }}</code></td>
            <td>{{ s.count }}</td>
            <td>{{ fmt(s.min) }}</td>
            <td><strong>{{ fmt(s.median) }}</strong></td>
            <td>{{ fmt(s.max) }}</td>
            <td>{{ fmt(s.p90) }}</td>
            <td class="muted">{{ Object.keys(s.from_activities).slice(0, 3).join(', ') }}</td>
            <td class="muted">{{ Object.keys(s.to_activities).slice(0, 3).join(', ') }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
.tabs { display: flex; gap: 0; border-bottom: 1px solid #e2e8f0; margin: 0.5rem 0; }
.tabs button {
  background: transparent; color: #475569; border: 0; padding: 0.5rem 1rem;
  cursor: pointer; border-bottom: 2px solid transparent; border-radius: 0; font-size: 0.9rem;
}
.tabs button.active { color: #0f766e; font-weight: 600; border-bottom-color: #0f766e; }
textarea { width: 100%; box-sizing: border-box; }
.highlight { background: #f0fdfa; }
.stat { text-align: center; }
.stat .n { font-size: 1.8rem; font-weight: 700; }
</style>