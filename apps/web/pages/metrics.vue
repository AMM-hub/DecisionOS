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

const openRaw = reactive<Record<string, boolean>>({})
function toggleRaw(id: string, ev: Event) {
  const el = ev.target as HTMLDetailsElement | null
  openRaw[id] = !!el?.open
}

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

// ---- definition rendering -------------------------------------------------
const OP_LABELS: Record<string, string> = {
  is_not_null: 'is not null',
  is_null: 'is null',
  eq: 'equals',
  not_in: 'not in',
  in: 'in',
  lt: 'less than',
  gte: 'at least',
  between: 'between'
}

function opLabel(op: string): string {
  return OP_LABELS[op] ?? op.replace(/_/g, ' ')
}

function predicateHasValue(p: Predicate): boolean {
  return p.value !== undefined && p.value !== null
}

function predicateValue(p: Predicate): string {
  if (Array.isArray(p.value)) return p.value.map(v => String(v)).join(', ')
  return p.value == null ? '' : String(p.value)
}

function predicateText(p: Predicate): string {
  const base = `${p.field} ${opLabel(p.op)}`
  return predicateHasValue(p) ? `${base} ${predicateValue(p)}` : base
}

function predicatePhrase(preds: Predicate[]): string {
  return preds.length ? preds.map(predicateText).join(' and ') : 'all rows'
}

function expressionLines(expr: MetricDefinition['expression']): string[] {
  if (expr.kind === 'ratio') {
    return [
      `numerator: count where ${predicatePhrase(expr.numerator_predicates)}`,
      `denominator: count where ${predicatePhrase(expr.denominator_predicates)}`
    ]
  }
  if (expr.kind === 'count') {
    return [`count where ${predicatePhrase(expr.predicates)}`]
  }
  const quantile = Math.round(expr.quantile * 100)
  return [`p${quantile} ${expr.unit} between ${expr.start_field} and ${expr.end_field}`]
}

function rawDefinition(m: MetricDefinition): string {
  return JSON.stringify({ eligibility: m.eligibility, expression: m.expression }, null, 2)
}
</script>

<template>
  <section>
    <PageHeader
      title="Metric definitions"
      subtitle="Certified metrics require an approved definition version. Ratios aggregate numerator and denominator before division. Propose as a modeler, approve as a manager."
    >
      <template #actions>
        <button class="secondary" :disabled="loading" @click="load">{{ loading ? 'Loading…' : 'Refresh' }}</button>
        <button @click="form.open = !form.open">{{ form.open ? 'Close' : 'Propose metric' }}</button>
      </template>
    </PageHeader>

    <DcCard v-if="error"><span class="badge err">{{ error }}</span></DcCard>
    <DcCard v-if="notice"><span class="badge ok">{{ notice }}</span></DcCard>

    <!-- propose -->
    <DcCard v-if="form.open" title="Propose a definition">
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
    </DcCard>

    <!-- list -->
    <DcCard v-if="!defs.length && !loading">
      <div class="muted">No definitions yet. Propose one to begin.</div>
    </DcCard>
    <DcCard v-for="m in defs" :key="m.metric_id + '@' + m.version" :title="m.name">
      <template #actions>
        <span :class="['badge', statusBadge(m.status)]">{{ m.status }} v{{ m.version }}</span>
        <button v-if="m.status === 'proposed' || m.status === 'withdrawn'" :disabled="busy" @click="approve(m)">{{ m.status === 'withdrawn' ? 'Re-approve' : 'Approve' }}</button>
        <button v-if="m.status === 'approved'" class="secondary" :disabled="busy" @click="withdraw(m)">Withdraw</button>
      </template>
      <div class="def-meta">
        <span class="chip" data-tone="accent">{{ m.kind }}</span>
        <span class="chip plain mono">{{ m.dataset_id.slice(0, 8) }}</span>
        <span class="chip plain">{{ m.time_basis }} · {{ m.timezone }}</span>
        <span class="def-id mono">{{ m.metric_id }}</span>
      </div>

      <div class="def-grid">
        <section class="def-sect">
          <h4 class="def-k">Eligibility</h4>
          <div v-if="m.eligibility.length" class="rule-list">
            <div v-for="(p, i) in m.eligibility" :key="i" class="rule-row">
              <span class="chip plain mono">{{ p.field }}</span>
              <span class="rule-op">{{ opLabel(p.op) }}</span>
              <span v-if="predicateHasValue(p)" class="chip mono">{{ predicateValue(p) }}</span>
            </div>
          </div>
          <p v-else class="muted def-line">All rows eligible</p>
        </section>

        <section class="def-sect">
          <h4 class="def-k">Expression</h4>
          <p v-for="(line, i) in expressionLines(m.expression)" :key="i" class="def-line">{{ line }}</p>
        </section>
      </div>

      <details class="raw-def" @toggle="toggleRaw(m.metric_id, $event)">
        <summary>Raw definition</summary>
        <pre v-if="openRaw[m.metric_id]" class="mono">{{ rawDefinition(m) }}</pre>
      </details>
    </DcCard>

    <!-- query -->
    <DcCard title="Query a certified metric">
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
        <label v-if="qFields.length" class="field">Dimensions
          <select v-model="q.dimensions" multiple size="3">
            <option v-for="f in qFields" :key="f" :value="f">{{ f }}</option>
          </select>
        </label>
        <div v-else class="fld">
          <span class="muted">Dimensions</span>
          <span class="muted dims-hint">No dimensions available for this dataset</span>
        </div>
        <label class="field">Limit<input v-model="q.limit" type="number" min="1" max="500" /></label>
      </div>
      <div class="row" style="margin-top:0.5rem">
        <button
          :disabled="!q.metric_id || busy"
          :title="q.metric_id ? undefined : 'Select a certified metric to run a query'"
          @click="runQuery"
        >Run query</button>
        <span v-if="!q.metric_id" class="muted">Select a certified metric to run a query</span>
      </div>

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
    </DcCard>
  </section>
</template>

<style scoped>
.def-meta { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; margin-bottom: 12px; }
.def-id { margin-inline-start: auto; font-size: 12px; color: var(--muted); }
.def-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }
.def-sect { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.def-k {
  font-family: var(--font-mono); font-size: 10.5px; font-weight: 600; letter-spacing: 0.09em;
  text-transform: uppercase; color: var(--faint);
}
.def-line { font-size: 12.5px; color: var(--fg); line-height: 1.45; }
.rule-list { display: flex; flex-direction: column; gap: 5px; }
.rule-row { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; }
.rule-op { font-size: 12px; color: var(--muted); }
.raw-def { margin-top: 12px; padding-top: 8px; border-top: 1px solid var(--border); }
.raw-def summary { cursor: pointer; font-size: 11.5px; color: var(--muted); }
.raw-def pre {
  margin: 8px 0 0; padding: 10px; background: var(--surface-2);
  border: 1px solid var(--border); border-radius: var(--r);
  font-size: 11px; line-height: 1.5; white-space: pre-wrap; word-break: break-word; overflow-x: auto;
}
.dims-hint { font-size: 12px; }
@media (max-width: 720px) {
  .def-grid { grid-template-columns: 1fr; }
  .def-id { margin-inline-start: 0; }
}
</style>
