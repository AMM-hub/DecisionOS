<script setup lang="ts">
import type {
  AnalysisArtifact,
  AnalyticsAggregation,
  AnalyticsFilter,
  AnalyticsFilterOperator,
  AnalyticsQuery,
  AnalyticsQueryResponse,
  Dataset,
  DatasetSchema,
} from '~/shared/types'
import { ApiError } from '~/composables/api'
import { formatDateTime, num, titleCase } from '~/composables/format'

const { get, post, call } = useApi()
const { locale } = useLocale()

interface MeasureDraft {
  column: string
  agg: AnalyticsAggregation
  alias: string
}

const datasets = ref<Dataset[]>([])
const schemas = ref<Record<string, DatasetSchema>>({})
const loadingDatasets = ref(false)
const running = ref(false)
const saving = ref(false)
const analysesLoading = ref(false)
const error = ref<{ code?: string; detail: string } | null>(null)
const notice = ref<string | null>(null)

const selectedDataset = ref('')
const dimensions = ref<string[]>(['', ''])
const measures = ref<MeasureDraft[]>([{ column: '*', agg: 'count', alias: '' }])
const filter = reactive({
  enabled: false,
  column: '',
  op: 'eq' as AnalyticsFilterOperator,
  value: '',
})
const limit = ref(200)

const result = ref<AnalyticsQueryResponse | null>(null)
const resultDimensions = ref<string[]>([])
const analyses = ref<AnalysisArtifact[]>([])
const selectedId = ref<string | null>(null)
const saveName = ref('')

const AGGREGATIONS: AnalyticsAggregation[] = ['count', 'sum', 'avg', 'min', 'max', 'count_distinct']
const FILTER_OPS: AnalyticsFilterOperator[] = [
  'eq', 'neq', 'in', 'not_in', 'gt', 'gte', 'lt', 'lte', 'is_null', 'is_not_null',
]

const publishedDatasets = computed(() => datasets.value.filter(d => d.revision != null))
const schemaColumns = computed(() => {
  const schema = schemas.value[selectedDataset.value]
  return schema ? Object.entries(schema.columns) : []
})
const hasQuery = computed(() => !!selectedDataset.value && measures.value.some(m => m.column))

function setError(e: unknown) {
  if (e instanceof ApiError) {
    const detail = typeof e.detail === 'string' ? e.detail : e.message
    error.value = { code: e.code, detail }
  } else if (e instanceof Error) {
    error.value = { detail: e.message }
  } else {
    error.value = { detail: String(e) }
  }
}

async function loadDatasets() {
  loadingDatasets.value = true
  try {
    datasets.value = await get<Dataset[]>('/datasets?limit=500')
    if (!selectedDataset.value && publishedDatasets.value.length) {
      selectedDataset.value = publishedDatasets.value[0].dataset_id
    }
  } catch (e) {
    setError(e)
  } finally {
    loadingDatasets.value = false
  }
}

async function loadSchema(id: string) {
  if (!id || schemas.value[id]) return
  try {
    schemas.value[id] = await get<DatasetSchema>(`/datasets/${id}/schema`)
  } catch (e) {
    setError(e)
  }
}

watch(selectedDataset, async (id) => {
  result.value = null
  resultDimensions.value = []
  if (id) await loadSchema(id)
})

async function loadAnalyses() {
  analysesLoading.value = true
  try {
    analyses.value = await get<AnalysisArtifact[]>('/analytics/analyses?limit=100')
  } catch (e) {
    setError(e)
  } finally {
    analysesLoading.value = false
  }
}

onMounted(async () => {
  await Promise.all([loadDatasets(), loadAnalyses()])
})

function columnType(column: string): string | undefined {
  return schemas.value[selectedDataset.value]?.columns[column]
}

function coerce(value: string, column: string): unknown {
  const type = columnType(column)
  const trimmed = value.trim()
  if (type === 'integer' && /^-?\d+$/.test(trimmed)) return Number(trimmed)
  if (type === 'float' && trimmed !== '' && !Number.isNaN(Number(trimmed))) return Number(trimmed)
  return value
}

function currentQuery(): AnalyticsQuery {
  const filters: AnalyticsFilter[] = []
  if (filter.enabled && filter.column) {
    let value: unknown = null
    if (filter.op === 'in' || filter.op === 'not_in') {
      value = filter.value.split(',').map(v => coerce(v.trim(), filter.column)).filter(v => v !== '')
    } else if (filter.op !== 'is_null' && filter.op !== 'is_not_null') {
      value = coerce(filter.value, filter.column)
    }
    filters.push({ column: filter.column, op: filter.op, value })
  }
  return {
    dataset_id: selectedDataset.value,
    revision: null,
    dimensions: dimensions.value.map(d => d.trim()).filter(Boolean),
    measures: measures.value
      .filter(m => m.column)
      .map(m => ({ column: m.column, agg: m.agg, alias: m.alias.trim() || null })),
    filters,
    time_column: null,
    time_from: null,
    time_to: null,
    limit: Number(limit.value),
    order_by: null,
    order_dir: 'asc',
  }
}

async function run() {
  if (!hasQuery.value) return
  running.value = true
  error.value = null
  notice.value = null
  const query = currentQuery()
  try {
    result.value = await post<AnalyticsQueryResponse>('/analytics/query', query)
    resultDimensions.value = query.dimensions
  } catch (e) {
    result.value = null
    setError(e)
  } finally {
    running.value = false
  }
}

const rowObjects = computed(() => {
  if (!result.value) return [] as Array<Record<string, unknown>>
  const names = result.value.columns.map(c => c.name)
  return result.value.rows.map(row =>
    Object.fromEntries(names.map((name, i) => [name, row[i]])) as Record<string, unknown>,
  )
})
const tableRows = computed(() => rowObjects.value.slice(0, 50))

const measureColumns = computed(() => {
  if (!result.value) return []
  return result.value.columns.slice(resultDimensions.value.length)
})
const isScalar = computed(() => !!result.value && resultDimensions.value.length === 0)
const kpiTiles = computed(() => {
  if (!result.value || !isScalar.value) return []
  return measureColumns.value.map((column, i) => ({
    label: column.name,
    value: result.value?.rows[0]?.[resultDimensions.value.length + i] ?? null,
  }))
})

const groupedRows = computed(() => {
  if (!result.value || isScalar.value) return []
  const dims = resultDimensions.value
  const measureIndex = dims.length
  return result.value.rows
    .map(row => ({
      label: dims.map((name, i) => `${name}: ${fmtCell(row[i])}`).join(' · '),
      value: Number(row[measureIndex] ?? 0),
    }))
    .sort((a, b) => b.value - a.value)
})
const chartTruncated = computed(() => groupedRows.value.length > 12)
const chartRows = computed(() => groupedRows.value.slice(0, 12))
const chartMax = computed(() => Math.max(1, ...chartRows.value.map(r => Math.abs(r.value))))
const chartHeight = computed(() => Math.max(110, chartRows.value.length * 30 + 16))

function barWidth(value: number): number {
  return Math.max(2, (Math.abs(value) / chartMax.value) * 360)
}

function fmtCell(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'number') return num(value, Number.isInteger(value) ? 0 : 3)
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  return String(value)
}

function fmtKpi(value: unknown): string {
  if (typeof value === 'number') return num(value, Number.isInteger(value) ? 0 : 3)
  return fmtCell(value)
}

function onAggChange(measure: MeasureDraft) {
  if (measure.agg !== 'count' && measure.column === '*') {
    measure.column = schemaColumns.value[0]?.[0] ?? ''
  }
}

function addMeasure() {
  if (measures.value.length < 3) {
    measures.value.push({ column: '*', agg: 'count', alias: '' })
  }
}

function removeMeasure(index: number) {
  if (measures.value.length > 1) measures.value.splice(index, 1)
}

async function loadArtifactIntoForm(artifact: AnalysisArtifact) {
  selectedDataset.value = artifact.query.dataset_id
  await loadSchema(artifact.query.dataset_id)
  dimensions.value = [artifact.query.dimensions[0] ?? '', artifact.query.dimensions[1] ?? '']
  measures.value = artifact.query.measures.slice(0, 3).map(m => ({
    column: m.column,
    agg: m.agg,
    alias: m.alias ?? '',
  }))
  if (!measures.value.length) {
    measures.value = [{ column: '*', agg: 'count', alias: '' }]
  }
  const firstFilter = artifact.query.filters[0]
  if (firstFilter) {
    filter.enabled = true
    filter.column = firstFilter.column
    filter.op = firstFilter.op
    const raw = firstFilter.value
    filter.value = Array.isArray(raw) ? raw.join(', ') : raw == null ? '' : String(raw)
  } else {
    filter.enabled = false
    filter.column = ''
    filter.op = 'eq'
    filter.value = ''
  }
  limit.value = artifact.query.limit ?? 200
  selectedId.value = artifact.id
}

async function saveAnalysis() {
  if (!saveName.value.trim() || !hasQuery.value) return
  saving.value = true
  error.value = null
  notice.value = null
  const query = currentQuery()
  try {
    const artifact = await post<AnalysisArtifact>('/analytics/analyses', {
      name: saveName.value.trim(),
      query,
      run_now: true,
    })
    saveName.value = ''
    selectedId.value = artifact.id
    if (artifact.last_result) {
      result.value = artifact.last_result
      resultDimensions.value = artifact.query.dimensions
    }
    notice.value = `Saved analysis “${artifact.name}”.`
    await loadAnalyses()
  } catch (e) {
    setError(e)
  } finally {
    saving.value = false
  }
}

async function reopenAnalysis(artifact: AnalysisArtifact) {
  error.value = null
  notice.value = null
  try {
    const reopened = await get<AnalysisArtifact>(`/analytics/analyses/${artifact.id}`)
    await loadArtifactIntoForm(reopened)
    result.value = null
    resultDimensions.value = []
    notice.value = `Reopened “${reopened.name}”. Run the query to refresh the result.`
  } catch (e) {
    setError(e)
  }
}

async function rerunAnalysis(artifact: AnalysisArtifact) {
  error.value = null
  notice.value = null
  running.value = true
  try {
    const refreshed = await get<AnalysisArtifact>(`/analytics/analyses/${artifact.id}?run=true`)
    await loadArtifactIntoForm(refreshed)
    if (refreshed.last_result) {
      result.value = refreshed.last_result
      resultDimensions.value = refreshed.query.dimensions
    }
    notice.value = `Re-ran “${refreshed.name}” against revision ${refreshed.revision}.`
    await loadAnalyses()
  } catch (e) {
    setError(e)
  } finally {
    running.value = false
  }
}

async function deleteAnalysis(artifact: AnalysisArtifact) {
  error.value = null
  notice.value = null
  try {
    await call<{ status: string }>(`/analytics/analyses/${artifact.id}`, { method: 'DELETE' })
    if (selectedId.value === artifact.id) selectedId.value = null
    notice.value = `Deleted “${artifact.name}”.`
    await loadAnalyses()
  } catch (e) {
    setError(e)
  }
}
</script>

<template>
  <section>
    <PageHeader
      :title="t('studio.title', locale)"
      :subtitle="t('studio.subtitle', locale)"
    >
      <template #actions>
        <button class="secondary" :disabled="loadingDatasets" @click="loadDatasets">
          {{ loadingDatasets ? t('common.loading', locale) : t('studio.refresh', locale) }}
        </button>
      </template>
    </PageHeader>

    <DcCard v-if="error">
      <div class="banner" data-tone="warn" role="alert">
        <span class="badge err">{{ error.code ?? 'error' }}</span>
        <span>{{ error.detail }}</span>
      </div>
    </DcCard>

    <DcCard v-if="notice">
      <div class="banner">
        <span class="badge ok">ok</span>
        <span>{{ notice }}</span>
      </div>
    </DcCard>

    <DcCard :title="t('studio.build', locale)">
      <template #actions>
        <span class="badge plain">{{ t('studio.publishedOnly', locale) }}</span>
      </template>

      <div v-if="loadingDatasets" class="studio-skeleton" aria-hidden="true">
        <span></span><span></span><span></span>
      </div>

      <div v-else-if="!publishedDatasets.length" class="empty">
        <h3>{{ t('studio.noDatasets', locale) }}</h3>
        <p>
          {{ t('studio.noDatasetsHelp', locale) }}
          <NuxtLink to="/datasets">{{ t('nav.datasets', locale) }}</NuxtLink>
        </p>
      </div>

      <template v-else>
        <div class="studio-grid">
          <label class="field">
            <span>{{ t('studio.dataset', locale) }}</span>
            <select v-model="selectedDataset">
              <option v-for="d in publishedDatasets" :key="d.dataset_id" :value="d.dataset_id">
                {{ d.name }} · rev {{ d.revision }} · {{ num(d.row_count) }} rows
              </option>
            </select>
          </label>
          <label class="field">
            <span>{{ t('studio.dimensionOne', locale) }}</span>
            <select v-model="dimensions[0]">
              <option value="">{{ t('studio.none', locale) }}</option>
              <option v-for="[name] in schemaColumns" :key="`d1-${name}`" :value="name">{{ name }}</option>
            </select>
          </label>
          <label class="field">
            <span>{{ t('studio.dimensionTwo', locale) }}</span>
            <select v-model="dimensions[1]">
              <option value="">{{ t('studio.none', locale) }}</option>
              <option v-for="[name] in schemaColumns" :key="`d2-${name}`" :value="name">{{ name }}</option>
            </select>
          </label>
          <label class="field">
            <span>{{ t('studio.limit', locale) }}</span>
            <input v-model.number="limit" type="number" min="1" max="500" />
          </label>
        </div>

        <div class="studio-measures">
          <div class="studio-label">
            <span>{{ t('studio.measures', locale) }}</span>
            <button class="btn-secondary btn-sm" type="button" :disabled="measures.length >= 3" @click="addMeasure">
              {{ t('studio.addMeasure', locale) }}
            </button>
          </div>
          <div v-for="(measure, index) in measures" :key="`m-${index}`" class="studio-measure-row">
            <select v-model="measure.column">
              <option v-if="measure.agg === 'count'" value="*">{{ t('studio.allRows', locale) }}</option>
              <option v-for="[name] in schemaColumns" :key="`m-${index}-${name}`" :value="name">{{ name }}</option>
            </select>
            <select v-model="measure.agg" @change="onAggChange(measure)">
              <option v-for="agg in AGGREGATIONS" :key="agg" :value="agg">{{ agg }}</option>
            </select>
            <input v-model="measure.alias" type="text" :placeholder="t('studio.alias', locale)" />
            <button class="btn-ghost btn-sm" type="button" :disabled="measures.length === 1" @click="removeMeasure(index)">
              {{ t('common.delete', locale) }}
            </button>
          </div>
        </div>

        <div class="studio-filter">
          <label class="studio-check">
            <input v-model="filter.enabled" type="checkbox" />
            <span>{{ t('studio.filter', locale) }}</span>
          </label>
          <template v-if="filter.enabled">
            <select v-model="filter.column">
              <option value="">—</option>
              <option v-for="[name] in schemaColumns" :key="`f-${name}`" :value="name">{{ name }}</option>
            </select>
            <select v-model="filter.op">
              <option v-for="op in FILTER_OPS" :key="op" :value="op">{{ op }}</option>
            </select>
            <input
              v-if="filter.op !== 'is_null' && filter.op !== 'is_not_null'"
              v-model="filter.value"
              type="text"
              :placeholder="filter.op === 'in' || filter.op === 'not_in' ? 'a, b, c' : t('studio.value', locale)"
            />
          </template>
        </div>

        <div class="row studio-actions">
          <button class="btn-primary" :disabled="running || !hasQuery" @click="run">
            {{ running ? t('studio.running', locale) : t('studio.run', locale) }}
          </button>
          <template v-if="result">
            <span class="badge ok">{{ result.row_count }} {{ t('studio.rows', locale) }}</span>
            <span class="badge plain">{{ result.evidence_ref }}</span>
            <span class="badge plain">{{ result.took_ms }} ms</span>
          </template>
        </div>
      </template>
    </DcCard>

    <DcCard v-if="running" :title="t('studio.result', locale)">
      <div class="studio-skeleton" aria-hidden="true">
        <span></span><span></span><span></span><span></span>
      </div>
    </DcCard>

    <DcCard v-else-if="result && result.row_count === 0" :title="t('studio.result', locale)">
      <div class="empty">
        <h3>{{ t('studio.empty', locale) }}</h3>
        <p>{{ t('studio.emptyHelp', locale) }}</p>
      </div>
    </DcCard>

    <template v-else-if="result">
      <DcCard :title="t('studio.chart', locale)">
        <template #actions>
          <span class="badge plain">rev {{ result.revision }}</span>
        </template>
        <div v-if="isScalar" class="kpi-band studio-kpis" style="grid-template-columns: repeat(auto-fit, minmax(180px, 1fr))">
          <div v-for="tile in kpiTiles" :key="tile.label" class="kpi">
            <span class="k-label"><span class="mark" />{{ titleCase(tile.label) }}</span>
            <span class="k-val mono">{{ fmtKpi(tile.value) }}</span>
          </div>
        </div>
        <div v-else>
          <svg
            class="studio-bars"
            :viewBox="`0 0 640 ${chartHeight}`"
            role="img"
            :aria-label="t('studio.chart', locale)"
          >
            <g v-for="(row, index) in chartRows" :key="`bar-${index}`">
              <text class="bar-label" x="0" :y="index * 30 + 20">{{ row.label.slice(0, 30) }}</text>
              <rect
                x="196"
                :y="index * 30 + 6"
                :width="barWidth(row.value)"
                height="18"
                rx="3"
                class="bar-rect"
              />
              <text class="bar-value" :x="196 + barWidth(row.value) + 6" :y="index * 30 + 20">
                {{ fmtKpi(row.value) }}
              </text>
            </g>
          </svg>
          <p v-if="chartTruncated" class="muted studio-note">
            {{ t('studio.topTwelve', locale) }} ({{ chartRows.length }} / {{ groupedRows.length }})
          </p>
        </div>
      </DcCard>

      <DcCard :title="t('studio.table', locale)">
        <template #actions>
          <span class="badge plain">
            {{ t('studio.showing', locale) }} {{ Math.min(50, result.row_count) }} / {{ result.row_count }}
          </span>
          <span v-if="result.truncated" class="badge warn">{{ t('studio.truncated', locale) }}</span>
        </template>
        <div class="table-scroll">
          <table class="dt">
            <thead>
              <tr>
                <th v-for="column in result.columns" :key="column.name">{{ titleCase(column.name) }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, index) in tableRows" :key="`row-${index}`">
                <td v-for="column in result.columns" :key="`${index}-${column.name}`" :class="{ num: typeof row[column.name] === 'number' }">
                  {{ fmtCell(row[column.name]) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p class="muted studio-note">
          {{ t('studio.executed', locale) }} {{ formatDateTime(result.executed_at, locale) }} ·
          {{ result.evidence_ref }}
        </p>
      </DcCard>
    </template>

    <DcCard :title="t('studio.saved', locale)">
      <template #actions>
        <span class="badge plain">{{ analyses.length }}</span>
      </template>
      <div class="studio-save">
        <input v-model="saveName" type="text" :placeholder="t('studio.savePlaceholder', locale)" />
        <button class="btn-primary" :disabled="saving || !saveName.trim() || !hasQuery" @click="saveAnalysis">
          {{ saving ? t('studio.saving', locale) : t('common.save', locale) }}
        </button>
      </div>
      <div v-if="analysesLoading" class="studio-skeleton" aria-hidden="true">
        <span></span><span></span>
      </div>
      <div v-else-if="!analyses.length" class="muted studio-note">{{ t('studio.noSaved', locale) }}</div>
      <div v-else class="table-scroll">
        <table class="dt">
          <thead>
            <tr>
              <th>{{ t('studio.name', locale) }}</th>
              <th>{{ t('studio.dataset', locale) }}</th>
              <th>{{ t('studio.rows', locale) }}</th>
              <th>{{ t('studio.updated', locale) }}</th>
              <th>{{ t('common.actions', locale) }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="artifact in analyses" :key="artifact.id" :class="{ selected: artifact.id === selectedId }">
              <td>
                <div class="cell-stack">
                  <span class="cell-strong">{{ artifact.name }}</span>
                  <span class="muted mono">{{ artifact.id }}</span>
                </div>
              </td>
              <td>
                <div class="cell-stack">
                  <span class="mono">{{ artifact.dataset_id.slice(0, 8) }}</span>
                  <span class="muted">rev {{ artifact.revision }}</span>
                </div>
              </td>
              <td class="num">{{ num(artifact.row_count) }}</td>
              <td class="muted">{{ formatDateTime(artifact.updated_at, locale) }}</td>
              <td>
                <div class="row">
                  <button class="btn-secondary btn-xs" @click="reopenAnalysis(artifact)">{{ t('studio.reopen', locale) }}</button>
                  <button class="btn-secondary btn-xs" :disabled="running" @click="rerunAnalysis(artifact)">{{ t('studio.rerun', locale) }}</button>
                  <button class="btn-danger btn-xs" @click="deleteAnalysis(artifact)">{{ t('common.delete', locale) }}</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </DcCard>
  </section>
</template>

<style scoped>
.studio-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}
.studio-measures,
.studio-filter {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.studio-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  font-size: 12.5px;
  font-weight: 550;
  color: var(--fg);
}
.studio-measure-row {
  display: grid;
  grid-template-columns: minmax(140px, 1.2fr) minmax(110px, 0.8fr) minmax(140px, 1fr) auto;
  gap: 8px;
  align-items: center;
}
.studio-check {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  font-size: 12.5px;
  font-weight: 550;
}
.studio-filter {
  flex-direction: row;
  flex-wrap: wrap;
  align-items: center;
}
.studio-filter select,
.studio-filter input[type="text"] {
  min-width: 150px;
}
.studio-actions {
  margin-top: 14px;
}
.studio-skeleton {
  display: flex;
  flex-direction: column;
  gap: 9px;
  padding: 6px 0;
}
.studio-skeleton span {
  display: block;
  height: 14px;
  border-radius: var(--r-sm);
  background: linear-gradient(90deg, var(--surface-2), var(--surface-3), var(--surface-2));
  background-size: 200% 100%;
  animation: studio-shimmer 1.2s ease-in-out infinite;
}
.studio-skeleton span:nth-child(2n) { width: 72%; }
.studio-skeleton span:nth-child(3n) { width: 86%; }
@keyframes studio-shimmer {
  from { background-position: 200% 0; }
  to { background-position: -200% 0; }
}
.studio-kpis { margin-bottom: 0; }
.studio-bars {
  width: 100%;
  height: auto;
  display: block;
}
.bar-label,
.bar-value {
  font-family: var(--font-mono);
  font-size: 11px;
  fill: var(--muted);
}
.bar-value { fill: var(--fg-strong); font-weight: 600; }
.bar-rect { fill: var(--accent); opacity: 0.82; }
.studio-note {
  font-size: 11.5px;
  margin-top: 8px;
}
.studio-save {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.studio-save input { flex: 1 1 220px; }
@media (max-width: 920px) {
  .studio-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .studio-measure-row { grid-template-columns: 1fr 1fr; }
}
@media (max-width: 620px) {
  .studio-grid { grid-template-columns: 1fr; }
  .studio-measure-row { grid-template-columns: 1fr; }
}
</style>
