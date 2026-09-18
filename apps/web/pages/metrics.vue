<script setup lang="ts">
import type {
  Dataset, DatasetSchema, MetricDefinition, MetricQueryAnswered,
  MetricQueryInsufficient, MetricQueryResult, Predicate, PredicateOp
} from '~/shared/types'

const { get, post } = useApi()

const defs = ref<MetricDefinition[]>([])
const datasets = ref<Dataset[]>([])
const schemas = ref<Record<string, DatasetSchema>>({})
const loading = ref(false)
const busy = ref(false)
const error = ref<string | null>(null)
const notice = ref<string | null>(null)

const OPS: PredicateOp[] = ['is_not_null', 'is_null', 'eq', 'not_in', 'in', 'lt', 'gte']

// ---- propose form ---------------------------------------------------------
interface PredForm { field: string; op: PredicateOp; value: string }
const emptyPred = (): PredForm => ({ field: '', op: 'is_not_null', value: '' })

const form = reactive({
  open: false,
  metric_id: '',
  name: '',
  dataset_id: '',
  time_basis: '',
  timezone: 'Asia/Bahrain',
  kind: 'ratio' as MetricDefinition['kind'],
  num: emptyPred(),
  den: emptyPred(),
  cnt: emptyPred(),
  start_field: '',
  end_field: '',
  unit: 'hours' as 'hours' | 'minutes' | 'days',
  quantile: 0.5,
  elig: emptyPred()
})

const publishedDatasets = computed(() => datasets.value.filter(d => d.revision != null))
const formFields = computed(() => {
  const s = schemas.value[form.dataset_id]
  return s ? Object.entries(s.columns) : []
})

function toPredicate(p: PredForm, valueList: boolean): Predicate | null {
  if (!p.field) return null
  if (p.op === 'is_not_null' || p.op === 'is_null') return { op: p.op, field: p.field }
  if (valueList) return { op: p.op, field: p.field, value: p.value.split(',').map(v => v.trim()).filter(Boolean) }
  return { op: p.op, field: p.field, value: p.value }
}

async function loadSchema(id: string) {
  if (!id || schemas.value[id]) return
  try { const s = await get<DatasetSchema>(`/datasets/${id}/schema`); schemas.value[id] = s }
  catch { /* unpublished datasets have no schema */ }
}
watch(() => form.dataset_id, id => loadSchema(id))

function buildContent(): Record<string, unknown> {
  const elig = [toPredicate(form.elig, true)].filter(Boolean)
  if (form.kind === 'ratio') {
    return {
      metric_id: form.metric_id, name: form.name, kind: 'ratio', dataset_id: form.dataset_id,
      time_basis: form.time_basis, timezone: form.timezone, eligibility: elig,
      expression: {
        kind: 'ratio', numerator: 'count',
        numerator_predicates: [toPredicate(form.num, false)].filter(Boolean),
        denominator_predicates: [toPredicate(form.den, false)].filter(Boolean)
      }
    }
  }
  if (form.kind === 'count') {
    return {
      metric_id: form.metric_id, name: form.name, kind: 'count', dataset_id: form.dataset_id,
      time_basis: form.time_basis, timezone: form.timezone, eligibility: elig,
      expression: { kind: 'count', predicates: [toPredicate(form.cnt, false)].filter(Boolean) }
    }
  }
  return {
    metric_id: form.metric_id, name: form.name, kind: 'duration_percentile', dataset_id: form.dataset_id,
    time_basis: form.time_basis, timezone: form.timezone, eligibility: elig,
    expression: { kind: 'duration_percentile', start_field: form.start_field, end_field: form.end_field, unit: form.unit, quantile: Number(form.quantile) }
  }
}

async function propose() {
  busy.value = true; error.value = null; notice.value = null
  try {
    const r = await post<MetricDefinition>('/metrics/definitions', buildContent())
    notice.value = `Proposed ${r.metric_id} v${r.version} as ${r.status}. Switch to a manager to approve.`
    form.open = false
    await load()
  } catch (e) { error.value = e instanceof Error ? e.message : String(e) }
  finally { busy.value = false }
}

// ---- list & actions -------------------------------------------------------
async function load() {
  loading.value = true; error.value = null
  try {
    const [d, ds] = await Promise.all([
      get<MetricDefinition[]>('/metrics/definitions'),
      get<Dataset[]>('/datasets')
    ])
    defs.value = d
    datasets.value = ds
    ds.filter(x => x.revision != null).forEach(x => loadSchema(x.dataset_id))
  } catch (e) { error.value = e instanceof Error ? e.message : String(e) }
  finally { loading.value = false }
}
onMounted(load)

async function approve(m: MetricDefinition) {
  busy.value = true; error.value = null; notice.value = null
  try {
    await post(`/metrics/definitions/${m.metric_id}/approve`, {
      version: m.version, change_reason: 'Owner reviewed expression, eligibility and time basis', semantic_release_id: 'release-dev'
    })
    notice.value = `Approved ${m.metric_id} v${m.version}.`
    await load()
  } catch (e) { error.value = e instanceof Error ? e.message : String(e) }
  finally { busy.value = false }
}

async function withdraw(m: MetricDefinition) {
  busy.value = true; error.value = null; notice.value = null
  try {
    await post(`/metrics/definitions/${m.metric_id}/withdraw`, { change_reason: 'Retired pending review' })
    notice.value = `Withdrew ${m.metric_id}. Queries now refuse until re-approved.`
    await load()
  } catch (e) { error.value = e instanceof Error ? e.message : String(e) }
  finally { busy.value = false }
}

// ---- query runner ---------------------------------------------------------
const q = reactive({
  metric_id: '',
  start: '2026-01-01T00:00',
  end: '2026-04-01T00:00',
  timezone: 'Asia/Bahrain',
  dimensions: [] as string[],
  limit: 50
})
const result = ref<MetricQueryResult | null>(null)
const approvedDefs = computed(() => defs.value.filter(d => d.status === 'approved'))
const qFields = computed(() => {
  const def = defs.value.find(d => d.metric_id === q.metric_id)
  const s = def ? schemas.value[def.dataset_id] : undefined
  return s ? Object.keys(s.columns) : []
})

async function runQuery() {
  busy.value = true; error.value = null; result.value = null
  try {
    result.value = await post<MetricQueryResult>('/metrics/query', {
      schema_version: '1.0', metric_id: q.metric_id,
      window: { start: q.start, end: q.end, timezone: q.timezone },
      dimensions: q.dimensions, limit: Number(q.limit)
    })
  } catch (e) { error.value = e instanceof Error ? e.message : String(e) }
  finally { busy.value = false }
}

const answered = computed<MetricQueryAnswered | null>(() =>
  result.value && result.value.status === 'answered' ? result.value as MetricQueryAnswered : null)
const insufficient = computed<MetricQueryInsufficient | null>(() =>
  result.value && result.value.status === 'insufficient_data' ? result.value as MetricQueryInsufficient : null)

function statusBadge(s: MetricDefinition['status']) {
  return s === 'approved' ? 'ok' : s === 'proposed' ? 'warn' : s === 'withdrawn' ? 'warn' : 'err'
}
</script>

<template>
  <section>
    <div class="row" style="justify-content: space-between">
      <h1>Metric definitions</h1>
      <div class="row">
        <button class="secondary" :disabled="loading" @click="load">{{ loading ? 'Loading…' : 'Refresh' }}</button>
        <button @click="form.open = !form.open">{{ form.open ? 'Close' : 'Propose metric' }}</button>
      </div>
    </div>
    <p class="muted">Certified metrics require an approved definition version. Ratios aggregate numerator and denominator before division. Propose as a modeler, approve as a manager.</p>

    <div v-if="error" class="card"><span class="badge err">{{ error }}</span></div>
    <div v-if="notice" class="card"><span class="badge ok">{{ notice }}</span></div>

    <!-- propose -->
    <div v-if="form.open" class="card">
      <h2>Propose a definition</h2>
      <div class="grid cols-3">
        <label class="field">Metric ID<code>*</code>
          <input v-model="form.metric_id" placeholder="metric-first-response-rate" />
        </label>
        <label class="field">Name<input v-model="form.name" placeholder="First response rate" /></label>
        <label class="field">Dataset
          <select v-model="form.dataset_id">
            <option value="" disabled>Select published dataset…</option>
            <option v-for="d in publishedDatasets" :key="d.dataset_id" :value="d.dataset_id">{{ d.name }} (rev {{ d.revision }})</option>
          </select>
        </label>
        <label class="field">Kind
          <select v-model="form.kind">
            <option value="ratio">ratio</option>
            <option value="count">count</option>
            <option value="duration_percentile">duration_percentile</option>
          </select>
        </label>
        <label class="field">Time basis
          <select v-model="form.time_basis">
            <option value="" disabled>Select field…</option>
            <option v-for="[c] in formFields" :key="c" :value="c">{{ c }}</option>
          </select>
        </label>
        <label class="field">Timezone<input v-model="form.timezone" /></label>
      </div>

      <div v-if="form.kind === 'ratio'" class="grid cols-3">
        <fieldset><legend class="muted">Numerator predicate</legend>
          <select v-model="form.num.field"><option value="">(all eligible)</option><option v-for="[c] in formFields" :key="c" :value="c">{{ c }}</option></select>
          <select v-model="form.num.op"><option v-for="o in OPS" :key="o" :value="o">{{ o }}</option></select>
          <input v-model="form.num.value" placeholder="value (CSV for in/not_in)" :disabled="form.num.op==='is_not_null'||form.num.op==='is_null'" />
        </fieldset>
        <fieldset><legend class="muted">Denominator predicate</legend>
          <select v-model="form.den.field"><option value="">(all eligible)</option><option v-for="[c] in formFields" :key="c" :value="c">{{ c }}</option></select>
          <select v-model="form.den.op"><option v-for="o in OPS" :key="o" :value="o">{{ o }}</option></select>
          <input v-model="form.den.value" :disabled="form.den.op==='is_not_null'||form.den.op==='is_null'" />
        </fieldset>
        <fieldset><legend class="muted">Eligibility (value = CSV list)</legend>
          <select v-model="form.elig.field"><option value="">(none)</option><option v-for="[c] in formFields" :key="c" :value="c">{{ c }}</option></select>
          <select v-model="form.elig.op"><option v-for="o in OPS" :key="o" :value="o">{{ o }}</option></select>
          <input v-model="form.elig.value" :disabled="form.elig.op==='is_not_null'||form.elig.op==='is_null'" />
        </fieldset>
      </div>
      <div v-else-if="form.kind === 'count'" class="grid cols-3">
        <fieldset><legend class="muted">Count predicate</legend>
          <select v-model="form.cnt.field"><option value="">(all eligible)</option><option v-for="[c] in formFields" :key="c" :value="c">{{ c }}</option></select>
          <select v-model="form.cnt.op"><option v-for="o in OPS" :key="o" :value="o">{{ o }}</option></select>
          <input v-model="form.cnt.value" :disabled="form.cnt.op==='is_not_null'||form.cnt.op==='is_null'" />
        </fieldset>
        <fieldset><legend class="muted">Eligibility</legend>
          <select v-model="form.elig.field"><option value="">(none)</option><option v-for="[c] in formFields" :key="c" :value="c">{{ c }}</option></select>
          <select v-model="form.elig.op"><option v-for="o in OPS" :key="o" :value="o">{{ o }}</option></select>
          <input v-model="form.elig.value" :disabled="form.elig.op==='is_not_null'||form.elig.op==='is_null'" />
        </fieldset>
      </div>
      <div v-else class="grid cols-3">
        <label class="field">Start field<select v-model="form.start_field"><option value="" disabled>…</option><option v-for="[c] in formFields" :key="c" :value="c">{{ c }}</option></select></label>
        <label class="field">End field<select v-model="form.end_field"><option value="" disabled>…</option><option v-for="[c] in formFields" :key="c" :value="c">{{ c }}</option></select></label>
        <label class="field">Unit<select v-model="form.unit"><option value="hours">hours</option><option value="minutes">minutes</option><option value="days">days</option></select></label>
        <label class="field">Quantile<input v-model="form.quantile" type="number" step="0.05" min="0.01" max="0.99" /></label>
      </div>

      <div class="row" style="margin-top:0.6rem">
        <button :disabled="!form.metric_id || !form.name || !form.dataset_id || !form.time_basis || busy" @click="propose">Submit proposal</button>
        <button class="secondary" @click="form.open = false">Cancel</button>
      </div>
    </div>

    <!-- list -->
    <div v-if="!defs.length && !loading" class="card muted">No definitions yet. Propose one to begin.</div>
    <div v-for="m in defs" :key="m.metric_id + '@' + m.version" class="card">
      <div class="row" style="justify-content: space-between">
        <h2 style="margin:0">{{ m.name }}
          <span :class="['badge', statusBadge(m.status)]">{{ m.status }} v{{ m.version }}</span>
        </h2>
        <div class="row">
          <button v-if="m.status === 'proposed' || m.status === 'withdrawn'" :disabled="busy" @click="approve(m)">{{ m.status === 'withdrawn' ? 'Re-approve' : 'Approve' }}</button>
          <button v-if="m.status === 'approved'" class="secondary" :disabled="busy" @click="withdraw(m)">Withdraw</button>
        </div>
      </div>
      <p class="muted"><code>{{ m.metric_id }}</code> · {{ m.kind }} · dataset <code>{{ m.dataset_id.slice(0, 8) }}</code> · time basis: {{ m.time_basis }} ({{ m.timezone }})</p>
      <p class="muted">eligibility: {{ m.eligibility.length ? JSON.stringify(m.eligibility) : '(all)' }} · expression: <code>{{ JSON.stringify(m.expression) }}</code></p>
    </div>

    <!-- query -->
    <div class="card">
      <h2>Query a certified metric</h2>
      <div class="grid cols-3">
        <label class="field">Metric
          <select v-model="q.metric_id">
            <option value="" disabled>Select approved metric…</option>
            <option v-for="m in approvedDefs" :key="m.metric_id" :value="m.metric_id">{{ m.name }} ({{ m.metric_id }})</option>
          </select>
        </label>
        <label class="field">Window start<input v-model="q.start" type="datetime-local" /></label>
        <label class="field">Window end<input v-model="q.end" type="datetime-local" /></label>
        <label class="field">Timezone<input v-model="q.timezone" /></label>
        <label class="field">Dimensions
          <select v-model="q.dimensions" multiple size="3">
            <option v-for="f in qFields" :key="f" :value="f">{{ f }}</option>
          </select>
        </label>
        <label class="field">Limit<input v-model="q.limit" type="number" min="1" max="500" /></label>
      </div>
      <button :disabled="!q.metric_id || busy" @click="runQuery" style="margin-top:0.5rem">Run query</button>

      <div v-if="answered" style="margin-top:0.8rem">
        <h3>Result <span class="badge ok">answered</span></h3>
        <p class="muted">Definition v{{ answered.definition_version }} · release {{ answered.semantic_release_id }} · evidence <code>{{ answered.evidence_ref }}</code> · {{ answered.row_count }} rows</p>
        <table>
          <thead><tr><th v-for="k in Object.keys(answered.rows[0] ?? {})" :key="k">{{ k }}</th></tr></thead>
          <tbody><tr v-for="(r, i) in answered.rows" :key="i"><td v-for="(v, k) in r" :key="String(k)">{{ v }}</td></tr></tbody>
        </table>
        <p v-if="answered.quality_flags.length" class="muted">Quality flags: {{ answered.quality_flags.join(', ') }}</p>
      </div>

      <div v-if="insufficient" style="margin-top:0.8rem">
        <h3>Refused <span class="badge warn">{{ insufficient.reason_code }}</span></h3>
        <p class="muted">Missing: {{ insufficient.missing_requirements.join(', ') }} · next actions: {{ insufficient.next_actions.join(', ') }}</p>
      </div>
    </div>
  </section>
</template>
