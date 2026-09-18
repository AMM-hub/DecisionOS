<script setup lang="ts">
import type {
  Dataset, ForecastComparison, ForecastEvaluation, ForecastPredictResponse,
  ForecastSuitability, ForecastTrainResponse, MetricDefinition
} from '~/shared/types'

const { get, post } = useApi()

const datasets = ref<Dataset[]>([])
const defs = ref<MetricDefinition[]>([])
const loading = ref(false)
const busy = ref(false)
const error = ref<string | null>(null)

const form = reactive({
  dataset_id: '',
  metric_id: '',
  frequency: 'D' as 'D' | 'W' | 'MS' | 'H',
  season_length: 7,
  horizon: 14,
  test_size: 0.2
})

const publishedDatasets = computed(() => datasets.value.filter(d => d.revision != null))
const approvedDefs = computed(() =>
  defs.value.filter(d => d.status === 'approved' && (!form.dataset_id || d.dataset_id === form.dataset_id)))
const selectedDef = computed(() => defs.value.find(d => d.metric_id === form.metric_id && d.status === 'approved'))

watch(() => form.dataset_id, () => {
  if (selectedDef.value && selectedDef.value.dataset_id !== form.dataset_id) form.metric_id = ''
})

const suitability = ref<ForecastSuitability | null>(null)
const evaluation = ref<ForecastEvaluation | null>(null)
const trained = ref<ForecastTrainResponse | null>(null)
const prediction = ref<ForecastPredictResponse | null>(null)

function payload() {
  return {
    dataset_id: form.dataset_id,
    metric_id: form.metric_id,
    time_basis: selectedDef.value?.time_basis,
    frequency: form.frequency,
    season_length: Number(form.season_length) || undefined
  }
}

async function checkSuitability() {
  busy.value = true; error.value = null
  try {
    suitability.value = await post<ForecastSuitability>('/forecasts/suitability', payload())
  } catch (e) { error.value = e instanceof Error ? e.message : String(e) }
  finally { busy.value = false }
}

async function compareModels() {
  busy.value = true; error.value = null; evaluation.value = null
  try {
    const r = await post<ForecastEvaluation & { status: string; reason?: string }>('/forecasts/evaluate',
      { ...payload(), test_size: Number(form.test_size) })
    if (r.status === 'answered' && Array.isArray(r.comparisons)) evaluation.value = r as ForecastEvaluation
    else error.value = `Refused: ${r.reason ?? 'insufficient data'}`
  } catch (e) { error.value = e instanceof Error ? e.message : String(e) }
  finally { busy.value = false }
}

async function train() {
  busy.value = true; error.value = null; trained.value = null; prediction.value = null
  try {
    const r = await post<ForecastTrainResponse>('/forecasts/train', { ...payload(), horizon: Number(form.horizon) })
    trained.value = r
    if (r.status !== 'trained') error.value = `Refused: ${r.reason ?? 'insufficient data'}`
  } catch (e) { error.value = e instanceof Error ? e.message : String(e) }
  finally { busy.value = false }
}

async function runPredict() {
  if (!trained.value?.model_spec_id) return
  busy.value = true; error.value = null; prediction.value = null
  try {
    prediction.value = await post<ForecastPredictResponse>('/forecasts/predict', {
      model_spec_id: trained.value.model_spec_id,
      horizon: Number(form.horizon),
      prediction_intervals: true
    })
  } catch (e) { error.value = e instanceof Error ? e.message : String(e) }
  finally { busy.value = false }
}

async function load() {
  loading.value = true; error.value = null
  try {
    const [ds, d] = await Promise.all([get<Dataset[]>('/datasets'), get<MetricDefinition[]>('/metrics/definitions')])
    datasets.value = ds
    defs.value = d
  } catch (e) { error.value = e instanceof Error ? e.message : String(e) }
  finally { loading.value = false }
}
onMounted(load)

// ---- canvas chart: history + forecast with uncertainty band -----------------
const canvas = ref<HTMLCanvasElement | null>(null)

function fmt(v: number | null | undefined): string {
  if (v == null || !isFinite(v)) return '–'
  return Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(2)
}

function drawChart() {
  const el = canvas.value
  if (!el) return
  const hist = trained.value?.history ?? []
  const preds = prediction.value?.predictions ?? []
  const dpr = window.devicePixelRatio || 1
  const W = el.clientWidth, H = 340
  el.width = W * dpr; el.height = H * dpr
  const g = el.getContext('2d')!
  g.scale(dpr, dpr)
  g.clearRect(0, 0, W, H)
  const padL = 56, padR = 12, padT = 12, padB = 28
  const n = hist.length + preds.length
  if (!n) { g.fillStyle = '#64748b'; g.fillText('Train a model to see the chart.', 20, 40); return }

  const vals: number[] = []
  hist.forEach(p => vals.push(p.y))
  preds.forEach(p => { vals.push(p.yhat ?? 0, p.yhat_lower ?? p.yhat ?? 0, p.yhat_upper ?? p.yhat ?? 0) })
  let lo = Math.min(...vals), hi = Math.max(...vals)
  const span = hi - lo || 1
  lo -= span * 0.08; hi += span * 0.08
  const x = (i: number) => padL + (W - padL - padR) * (n === 1 ? 0.5 : i / (n - 1))
  const y = (v: number) => padT + (H - padT - padB) * (1 - (v - lo) / (hi - lo))

  // grid + y labels
  g.strokeStyle = '#e2e8f0'; g.fillStyle = '#64748b'; g.font = '11px system-ui'
  for (let k = 0; k <= 4; k++) {
    const v = lo + (hi - lo) * k / 4, yy = y(v)
    g.beginPath(); g.moveTo(padL, yy); g.lineTo(W - padR, yy); g.stroke()
    g.fillText(fmt(v), 6, yy + 4)
  }

  // uncertainty band (95%)
  if (preds.length) {
    g.fillStyle = 'rgba(15, 118, 110, 0.14)'
    g.beginPath()
    preds.forEach((p, i) => { const X = x(hist.length + i); const Y = y(p.yhat_upper ?? p.yhat ?? 0); i ? g.lineTo(X, Y) : g.moveTo(X, Y) })
    for (let i = preds.length - 1; i >= 0; i--) {
      const p = preds[i]
      g.lineTo(x(hist.length + i), y(p.yhat_lower ?? p.yhat ?? 0))
    }
    g.closePath(); g.fill()
  }

  // history line
  g.strokeStyle = '#334155'; g.lineWidth = 1.6; g.beginPath()
  hist.forEach((p, i) => i ? g.lineTo(x(i), y(p.y)) : g.moveTo(x(i), y(p.y)))
  g.stroke()

  // forecast line (dashed), anchored to last history point
  if (preds.length) {
    g.strokeStyle = '#0f766e'; g.lineWidth = 1.8; g.setLineDash([5, 4]); g.beginPath()
    g.moveTo(x(hist.length - 1), y(hist[hist.length - 1]?.y ?? 0))
    preds.forEach((p, i) => g.lineTo(x(hist.length + i), y(p.yhat ?? 0)))
    g.stroke(); g.setLineDash([])
    // split marker
    g.strokeStyle = '#cbd5e1'; g.setLineDash([2, 3]); g.beginPath()
    g.moveTo(x(hist.length - 1), padT); g.lineTo(x(hist.length - 1), H - padB); g.stroke(); g.setLineDash([])
  }

  // x labels (first / split / last)
  const labelAt = (i: number, ds: string) => {
    const t = ds.slice(0, 10)
    g.fillStyle = '#64748b'; g.fillText(t, Math.min(Math.max(x(i) - 30, 2), W - 70), H - 8)
  }
  if (hist.length) labelAt(0, hist[0].ds)
  if (hist.length) labelAt(hist.length - 1, hist[hist.length - 1].ds)
  if (preds.length) labelAt(n - 1, preds[preds.length - 1].ds)
}

watch([trained, prediction], () => nextTick(drawChart))
onMounted(() => nextTick(drawChart))

function maseOf(c: ForecastComparison) { return c.mase == null ? '–' : c.mase.toFixed(3) }
function bestModel(comps: ForecastComparison[]): string | null {
  const scored = comps.filter(c => c.mase != null)
  if (!scored.length) return null
  return scored.reduce((a, b) => (a.mase as number) <= (b.mase as number) ? a : b).model_name
}
</script>

<template>
  <section>
    <div class="row" style="justify-content: space-between">
      <h1>Forecasting lab</h1>
      <button class="secondary" :disabled="loading" @click="load">{{ loading ? 'Loading…' : 'Refresh' }}</button>
    </div>
    <p class="muted">Forecasts are refused when history is too thin. A complex model is only selected if it beats the naive baseline on a holdout — every result shows horizon, assumptions, evaluation, and limitations.</p>

    <div v-if="error" class="card"><span class="badge err">{{ error }}</span></div>

    <!-- setup -->
    <div class="card">
      <h2>1 · Source &amp; horizon</h2>
      <div class="grid cols-3">
        <label class="field">Dataset
          <select v-model="form.dataset_id">
            <option value="" disabled>Select published dataset…</option>
            <option v-for="d in publishedDatasets" :key="d.dataset_id" :value="d.dataset_id">{{ d.name }} (rev {{ d.revision }})</option>
          </select>
        </label>
        <label class="field">Certified metric
          <select v-model="form.metric_id">
            <option value="" disabled>Select approved metric…</option>
            <option v-for="m in approvedDefs" :key="m.metric_id" :value="m.metric_id">{{ m.name }}</option>
          </select>
        </label>
        <label class="field">Frequency
          <select v-model="form.frequency">
            <option value="D">daily (D)</option>
            <option value="W">weekly (W)</option>
            <option value="MS">monthly (MS)</option>
            <option value="H">hourly (H)</option>
          </select>
        </label>
        <label class="field">Season length
          <select v-model.number="form.season_length">
            <option :value="1">1 (none)</option>
            <option :value="7">7 (days/week)</option>
            <option :value="12">12 (months)</option>
            <option :value="24">24 (hours)</option>
            <option :value="52">52 (weeks)</option>
          </select>
        </label>
        <label class="field">Horizon (periods)<input v-model.number="form.horizon" type="number" min="1" max="365" /></label>
        <label class="field">Holdout share<input v-model.number="form.test_size" type="number" min="0.1" max="0.5" step="0.05" /></label>
      </div>
      <div class="row" style="margin-top:0.6rem">
        <button :disabled="!form.dataset_id || !form.metric_id || busy" @click="checkSuitability">{{ busy ? 'Working…' : 'Check suitability' }}</button>
        <button class="secondary" :disabled="!form.dataset_id || !form.metric_id || busy" @click="compareModels">Compare models</button>
        <button :disabled="!form.dataset_id || !form.metric_id || busy" @click="train">Train model</button>
      </div>
      <p v-if="selectedDef" class="muted">time basis: <code>{{ selectedDef.time_basis }}</code> ({{ selectedDef.timezone }}) · v{{ selectedDef.version }}</p>
    </div>

    <!-- suitability -->
    <div v-if="suitability" class="card">
      <h2>2 · Suitability
        <span :class="['badge', suitability.sufficient ? 'ok' : 'warn']">{{ suitability.sufficient ? 'supported' : 'refused' }}</span>
      </h2>
      <p v-if="!suitability.sufficient" class="muted">{{ suitability.reason }}
        <template v-if="suitability.missing_requirements?.length"> · missing: {{ suitability.missing_requirements.join(', ') }}</template>
      </p>
      <p v-else class="muted">{{ suitability.observations }} periods · coverage {{ suitability.coverage != null ? (suitability.coverage * 100).toFixed(0) + '%' : '–' }}</p>
      <ul>
        <li v-for="a in suitability.recommended_actions" :key="a" class="muted">{{ a }}</li>
      </ul>
      <p v-for="w in suitability.warnings" :key="w"><span class="badge warn">{{ w }}</span></p>
    </div>

    <!-- evaluation -->
    <div v-if="evaluation" class="card">
      <h2>3 · Model comparison (holdout of {{ evaluation.holdout_size }} periods)</h2>
      <table>
        <thead><tr><th>Model</th><th>MASE ↓</th><th>MAPE %</th><th>RMSE</th><th></th></tr></thead>
        <tbody>
          <tr v-for="c in evaluation.comparisons" :key="c.model_name">
            <td><code>{{ c.model_name }}</code></td>
            <td>{{ maseOf(c) }}</td>
            <td>{{ c.mape == null ? '–' : c.mape.toFixed(2) }}</td>
            <td>{{ c.rmse == null ? '–' : c.rmse.toFixed(3) }}</td>
            <td>
              <span v-if="c.model_name === evaluation.baseline_model" class="badge">baseline</span>
              <span v-else-if="c.model_name === bestModel(evaluation.comparisons)" class="badge ok">best holdout</span>
              <span v-if="c.error" class="badge err">{{ c.error }}</span>
            </td>
          </tr>
        </tbody>
      </table>
      <p class="muted">MASE &lt; 1 beats the seasonal naive scaling. A complex model is kept only if it clearly beats the baseline.</p>
    </div>

    <!-- trained -->
    <div v-if="trained && trained.status === 'trained'" class="card">
      <h2>4 · Trained model <span class="badge ok">{{ trained.model_name }}</span></h2>
      <p class="muted">
        {{ trained.training_points }} periods through <code>{{ trained.training_end?.slice(0, 10) }}</code> ·
        horizon {{ trained.horizon }} · holdout MASE {{ fmt(trained.evaluation?.metrics.mase) }} ·
        baseline <code>{{ trained.baseline_model }}</code>
      </p>
      <button :disabled="busy" @click="runPredict">{{ busy ? 'Predicting…' : 'Generate forecast' }}</button>

      <h3>Assumptions</h3>
      <ul><li v-for="a in trained.assumptions" :key="a" class="muted">{{ a }}</li></ul>
      <h3>Limitations</h3>
      <ul><li v-for="l in trained.limitations" :key="l" class="muted">{{ l }}</li></ul>
    </div>

    <!-- prediction chart -->
    <div v-if="prediction && prediction.status === 'answered'" class="card">
      <h2>5 · Forecast <span class="badge">evidence <code>{{ prediction.evidence_ref }}</code></span></h2>
      <canvas ref="canvas" style="width:100%;height:340px;display:block"></canvas>
      <p class="muted">solid = observed · dashed = forecast · shaded band = 95% prediction interval</p>
      <table>
        <thead><tr><th>ds</th><th>yhat</th><th>lower 95%</th><th>upper 95%</th></tr></thead>
        <tbody>
          <tr v-for="p in prediction.predictions" :key="p.ds">
            <td>{{ p.ds.slice(0, 10) }}</td><td>{{ fmt(p.yhat) }}</td><td>{{ fmt(p.yhat_lower) }}</td><td>{{ fmt(p.yhat_upper) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-else-if="trained && trained.status === 'trained'" class="card muted">
      <h2>5 · Forecast</h2>
      Generate a forecast to see predictions with uncertainty bands.
    </div>
  </section>
</template>
