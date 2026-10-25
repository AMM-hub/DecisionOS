<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import type {
  ConnectorTable,
  ConnectorTestResult,
  DataProfileColumn,
  DataSource,
  Dataset,
  DatasetQualityResponse,
  IngestJob,
  IngestRun,
  QualityRule,
  QualityRuleKind,
  QualityRuleState,
  TablePreview,
} from '~/shared/types'
import { ApiError, useApi } from '~/composables/api'
import { t, useLocale } from '~/composables/locale'
import { formatDateTime, num } from '~/composables/format'
import PageHeader from '~/components/PageHeader.vue'
import DcCard from '~/components/DcCard.vue'

type SourceKind = 'postgres' | 'rest'

const { get, dataApi } = useApi()
const { locale } = useLocale()

const runtimeConfig = useRuntimeConfig()
const publicConfig = runtimeConfig.public as unknown as Record<string, unknown>
const pollIntervalMs = Math.max(1, Number(publicConfig.dataPollIntervalMs ?? 2500))
const pollBudgetMs = Math.max(pollIntervalMs, Number(publicConfig.dataPollBudgetMs ?? 120000))

const RUN_STATUS_KEYS: Record<string, string> = {
  queued: 'data.runStatus.queued',
  running: 'data.runStatus.running',
  succeeded: 'data.runStatus.succeeded',
  failed: 'data.runStatus.failed',
}

const RULE_KIND_KEYS: Record<string, string> = {
  not_null: 'data.ruleKindLabels.not_null',
  unique: 'data.ruleKindLabels.unique',
  range: 'data.ruleKindLabels.range',
  regex: 'data.ruleKindLabels.regex',
}

const SEVERITY_KEYS: Record<string, string> = {
  error: 'data.severityLabels.error',
  warn: 'data.severityLabels.warn',
  info: 'data.severityLabels.info',
}

const sources = ref<DataSource[]>([])
const jobs = ref<IngestJob[]>([])
const datasets = ref<Dataset[]>([])

const loadingSources = ref(false)
const loadingJobs = ref(false)
const loadingDatasets = ref(false)
const error = ref<{ code?: string; detail: string } | null>(null)
const notice = ref<string | null>(null)

const sourceForm = reactive({
  name: '',
  kind: 'postgres' as SourceKind,
  dsn: '',
  schema: 'public',
  base_url: '',
  auth_header: 'Authorization',
  token: '',
  records_path: '',
})
const sourceFieldErrors = reactive<Record<string, string>>({})
const savingSource = ref(false)
const nameInput = ref<HTMLInputElement | null>(null)

const testingId = ref<string | null>(null)
const testResults = ref<Record<string, ConnectorTestResult>>({})
const testErrors = ref<Record<string, string>>({})
const deletingId = ref<string | null>(null)

const browsingSource = ref<DataSource | null>(null)
const browseTables = ref<ConnectorTable[]>([])
const loadingTables = ref(false)
const selectedTable = ref<ConnectorTable | null>(null)
const preview = ref<TablePreview | null>(null)
const loadingPreview = ref(false)
const previewError = ref<string | null>(null)
const creatingJob = ref(false)

const runningJobId = ref<string | null>(null)
const runTimeouts = ref<Record<string, boolean>>({})
const expandedJobId = ref<string | null>(null)
const runsByJob = ref<Record<string, IngestRun[]>>({})
const loadingRuns = ref<string | null>(null)
let unmounted = false

const selectedDatasetId = ref('')
const quality = ref<DatasetQualityResponse | null>(null)
const loadingQuality = ref(false)
const qualityError = ref<string | null>(null)
const profiling = ref(false)
const showAddRule = ref(false)
const savingRule = ref(false)
const ruleFieldError = ref('')
const removingRuleId = ref<string | null>(null)
const ruleDraft = reactive({
  column_name: '',
  kind: 'not_null' as QualityRuleKind,
  severity: 'error',
  min: '',
  max: '',
  pattern: '',
})

const qualityRules = computed<QualityRuleState[]>(
  () => quality.value?.rules ?? quality.value?.results ?? [],
)
const qualityProfile = computed<DataProfileColumn[]>(() => quality.value?.profile ?? [])
const hasProfile = computed(() => qualityProfile.value.length > 0)

function detailText(e: unknown): string {
  if (e instanceof ApiError) {
    const detail = e.detail
    if (typeof detail === 'string' && detail.trim()) return detail
    if (detail && typeof detail === 'object') {
      const record = detail as Record<string, unknown>
      if (typeof record.message === 'string' && record.message) return record.message
      if (typeof record.detail === 'string' && record.detail) return record.detail
      try {
        return JSON.stringify(detail)
      } catch {
        return e.message
      }
    }
    return e.message
  }
  if (e instanceof Error) return e.message
  return String(e)
}

function setError(e: unknown) {
  if (e instanceof ApiError) {
    error.value = { code: e.code, detail: detailText(e) }
  } else {
    error.value = { detail: detailText(e) }
  }
}

function clearNotice() {
  notice.value = null
}

async function loadSources() {
  loadingSources.value = true
  try {
    sources.value = await dataApi.sources.list()
  } catch (e) {
    setError(e)
  } finally {
    loadingSources.value = false
  }
}

async function loadJobs() {
  loadingJobs.value = true
  try {
    const list = await dataApi.jobs.list()
    jobs.value = await Promise.all(
      list.map(async (job) => {
        if (job.latest_run !== undefined) return job
        try {
          const detail = await dataApi.jobs.getById(job.id)
          if (detail && typeof detail === 'object' && typeof detail.id === 'string') return detail
          return job
        } catch {
          return job
        }
      }),
    )
    for (const item of jobs.value) {
      const status = item.latest_run?.status
      if (status === 'succeeded' || status === 'failed') delete runTimeouts.value[item.id]
    }
    runTimeouts.value = { ...runTimeouts.value }
  } catch (e) {
    setError(e)
  } finally {
    loadingJobs.value = false
  }
}

async function loadDatasets() {
  loadingDatasets.value = true
  try {
    datasets.value = await get<Dataset[]>('/datasets')
  } catch (e) {
    setError(e)
  } finally {
    loadingDatasets.value = false
  }
}

async function refreshAll() {
  clearNotice()
  error.value = null
  await Promise.all([loadSources(), loadJobs(), loadDatasets()])
  if (selectedDatasetId.value) await loadQuality(selectedDatasetId.value)
}

function initialDatasetId(): string {
  try {
    if (typeof useRoute === 'function') {
      const route = useRoute() as unknown as {
        query?: Record<string, string | string[] | undefined>
      }
      const raw = route?.query?.dataset
      const value = Array.isArray(raw) ? raw[0] : raw
      if (typeof value === 'string' && value) return value
    }
  } catch {
    // Not mounted inside a Nuxt router (unit tests use window.location).
  }
  if (typeof window !== 'undefined') {
    return new URLSearchParams(window.location.search).get('dataset') ?? ''
  }
  return ''
}

onMounted(() => {
  void loadSources()
  void loadJobs()
  void loadDatasets()
  const initial = initialDatasetId()
  if (initial) {
    selectedDatasetId.value = initial
    void loadQuality(initial)
  }
})

onBeforeUnmount(() => {
  unmounted = true
})

function focusConnect() {
  nameInput.value?.focus()
}

function clearSourceFieldErrors() {
  for (const key of Object.keys(sourceFieldErrors)) delete sourceFieldErrors[key]
}

function sourceFieldForKey(detail: string): string | null {
  const lower = detail.toLowerCase()
  if (lower.includes('base_url')) return 'base_url'
  if (lower.includes('records_path')) return 'records_path'
  if (lower.includes('auth_header')) return 'auth_header'
  if (lower.includes('dsn')) return 'dsn'
  if (lower.includes('schema')) return 'schema'
  if (lower.includes('token') || lower.includes('secret')) return 'token'
  if (lower.includes('password') || lower.includes('host') || lower.includes('dbname')) return 'dsn'
  if (lower.includes("'name'") || lower.includes('"name"') || /\bname\b/.test(lower)) return 'name'
  return null
}

function resetSourceForm() {
  sourceForm.name = ''
  sourceForm.kind = 'postgres'
  sourceForm.dsn = ''
  sourceForm.schema = 'public'
  sourceForm.base_url = ''
  sourceForm.auth_header = 'Authorization'
  sourceForm.token = ''
  sourceForm.records_path = ''
}

async function submitSource() {
  if (savingSource.value) return
  clearSourceFieldErrors()
  error.value = null
  notice.value = null
  if (!sourceForm.name.trim()) {
    sourceFieldErrors.name = t('data.required', locale.value)
    return
  }
  if (sourceForm.kind === 'postgres' && !sourceForm.dsn.trim()) {
    sourceFieldErrors.dsn = t('data.required', locale.value)
    return
  }
  if (sourceForm.kind === 'rest' && !sourceForm.base_url.trim()) {
    sourceFieldErrors.base_url = t('data.required', locale.value)
    return
  }
  savingSource.value = true
  try {
    const config: Record<string, unknown> = {}
    let secret: string | undefined
    if (sourceForm.kind === 'postgres') {
      config.dsn = sourceForm.dsn.trim()
      if (sourceForm.schema.trim()) config.schema = sourceForm.schema.trim()
    } else {
      config.base_url = sourceForm.base_url.trim()
      if (sourceForm.auth_header.trim()) config.auth_header = sourceForm.auth_header.trim()
      if (sourceForm.records_path.trim()) config.records_path = sourceForm.records_path.trim()
      if (sourceForm.token) secret = sourceForm.token
    }
    await dataApi.sources.create({
      name: sourceForm.name.trim(),
      kind: sourceForm.kind,
      config,
      secret,
      read_only: true,
    })
    resetSourceForm()
    notice.value = t('data.sourceCreated', locale.value)
    await Promise.all([loadSources(), loadDatasets()])
  } catch (e) {
    if (e instanceof ApiError && e.status === 422) {
      const field = sourceFieldForKey(detailText(e))
      if (field) {
        sourceFieldErrors[field] = detailText(e)
        savingSource.value = false
        return
      }
    }
    setError(e)
  } finally {
    savingSource.value = false
  }
}

function safeUrl(raw: unknown): string {
  if (typeof raw !== 'string' || !raw) return ''
  try {
    const parsed = new URL(raw)
    const path = parsed.pathname === '/' ? '' : parsed.pathname
    return `${parsed.protocol}//${parsed.host}${path}`
  } catch {
    return raw.replace(/\/\/[^@/]*@/, '//')
  }
}

function sourceTarget(source: DataSource): string {
  const config = source.config ?? {}
  if (source.kind === 'postgres') {
    const rawHost = typeof config.host === 'string' ? config.host : ''
    const host = rawHost.replace(/^.*@/, '')
    const dbname = typeof config.dbname === 'string' ? config.dbname : ''
    if (host) return dbname ? `${host}/${dbname}` : host
    if (typeof config.dsn === 'string' && config.dsn) return safeUrl(config.dsn) || '—'
    return '—'
  }
  return safeUrl(config.base_url) || '—'
}

function sourceStatusLabel(source: DataSource): string {
  if (source.status === 'connected') return t('data.statusConnected', locale.value)
  if (source.status === 'failed' || source.status === 'error') return t('data.statusFailed', locale.value)
  return t('data.statusUntested', locale.value)
}

function sourceStatusTone(source: DataSource): string {
  if (source.status === 'connected') return 'ok'
  if (source.status === 'failed' || source.status === 'error') return 'err'
  return 'plain'
}

async function testSource(source: DataSource) {
  if (testingId.value) return
  testingId.value = source.id
  error.value = null
  notice.value = null
  const nextErrors = { ...testErrors.value }
  delete nextErrors[source.id]
  testErrors.value = nextErrors
  try {
    const result = await dataApi.sources.test(source.id)
    testResults.value = { ...testResults.value, [source.id]: result }
  } catch (e) {
    testErrors.value = { ...testErrors.value, [source.id]: detailText(e) }
  } finally {
    try {
      await loadSources()
    } catch {
      // surfacing the test result is more useful than a refresh failure
    }
    testingId.value = null
  }
}

async function deleteSource(source: DataSource) {
  if (!window.confirm(t('data.deleteSourceConfirm', locale.value))) return
  deletingId.value = source.id
  error.value = null
  notice.value = null
  try {
    await dataApi.sources.remove(source.id)
    if (browsingSource.value?.id === source.id) closeBrowse()
    notice.value = t('data.sourceDeleted', locale.value)
    await Promise.all([loadSources(), loadJobs()])
  } catch (e) {
    setError(e)
  } finally {
    deletingId.value = null
  }
}

async function openBrowse(source: DataSource) {
  browsingSource.value = source
  browseTables.value = []
  selectedTable.value = null
  preview.value = null
  previewError.value = null
  loadingTables.value = true
  error.value = null
  notice.value = null
  try {
    browseTables.value = await dataApi.sources.tables(source.id)
  } catch (e) {
    previewError.value = detailText(e)
  } finally {
    loadingTables.value = false
  }
}

function closeBrowse() {
  browsingSource.value = null
  browseTables.value = []
  selectedTable.value = null
  preview.value = null
  previewError.value = null
  loadingTables.value = false
  loadingPreview.value = false
}

function tableIdentifier(table: ConnectorTable): string {
  if (table.schema && table.schema !== 'rest') return `${table.schema}.${table.name}`
  return table.name
}

function tableKey(table: ConnectorTable): string {
  return `${table.schema}.${table.name}`
}

function isSelectedTable(table: ConnectorTable): boolean {
  return selectedTable.value !== null && tableKey(selectedTable.value) === tableKey(table)
}

async function selectTable(table: ConnectorTable) {
  if (!browsingSource.value) return
  selectedTable.value = table
  preview.value = null
  previewError.value = null
  loadingPreview.value = true
  try {
    preview.value = await dataApi.sources.preview(
      browsingSource.value.id,
      tableIdentifier(table),
      50,
    )
  } catch (e) {
    previewError.value = detailText(e)
  } finally {
    loadingPreview.value = false
  }
}

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'object') {
    try {
      return JSON.stringify(value)
    } catch {
      return String(value)
    }
  }
  return String(value)
}

async function createJobFromPreview() {
  if (!browsingSource.value || !selectedTable.value || creatingJob.value) return
  creatingJob.value = true
  error.value = null
  notice.value = null
  try {
    const table = selectedTable.value
    await dataApi.jobs.create({
      data_source_id: browsingSource.value.id,
      name: `${table.name} ${t('data.ingestSuffix', locale.value)}`,
      target_table: tableIdentifier(table),
      mode: 'full',
    })
    notice.value = t('data.jobCreated', locale.value)
    closeBrowse()
    await loadJobs()
  } catch (e) {
    setError(e)
  } finally {
    creatingJob.value = false
  }
}

function sourceName(id: string): string {
  return sources.value.find(source => source.id === id)?.name ?? id
}

function latestRunOf(job: IngestJob): IngestRun | null {
  return job.latest_run ?? null
}

function runStatusLabel(job: IngestJob): string {
  const run = latestRunOf(job)
  if (!run) return t('data.noRunsYet', locale.value)
  const key = RUN_STATUS_KEYS[run.status]
  return key ? t(key, locale.value) : String(run.status)
}

function runTone(job: IngestJob): string {
  const status = latestRunOf(job)?.status
  if (status === 'succeeded') return 'ok'
  if (status === 'failed') return 'err'
  if (status === 'running') return 'blue'
  if (status === 'queued') return 'warn'
  return 'plain'
}

function rowsWrittenLabel(job: IngestJob): string {
  const run = latestRunOf(job)
  if (!run) return t('data.unknown', locale.value)
  if (run.status === 'queued' || run.status === 'running') {
    return t('data.notMeasured', locale.value)
  }
  return `${num(run.rows_written)} ${t('data.rowsWritten', locale.value)}`
}

function lastRunAt(job: IngestJob): string | null {
  const run = latestRunOf(job)
  if (!run) return null
  return run.finished_at ?? run.started_at ?? run.created_at ?? null
}

function jobError(job: IngestJob): string | null {
  const run = latestRunOf(job)
  return run && run.status === 'failed' ? run.error : null
}

function modeLabel(job: IngestJob): string {
  return job.mode === 'incremental'
    ? t('data.modeIncremental', locale.value)
    : t('data.modeFull', locale.value)
}

function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms))
}

function replaceJobRun(jobId: string, run: IngestRun) {
  jobs.value = jobs.value.map(job => (job.id === jobId ? { ...job, latest_run: run } : job))
}

async function runNow(job: IngestJob) {
  if (runningJobId.value) return
  runningJobId.value = job.id
  delete runTimeouts.value[job.id]
  runTimeouts.value = { ...runTimeouts.value }
  error.value = null
  notice.value = null
  try {
    const enqueued = await dataApi.jobs.run(job.id)
    const queued: IngestRun = {
      id: enqueued.run_id,
      job_id: job.id,
      status: 'queued',
      started_at: null,
      finished_at: null,
      rows_read: 0,
      rows_written: 0,
      dataset_id: null,
      upload_id: null,
      error: null,
    }
    replaceJobRun(job.id, queued)
    notice.value = t('data.runQueued', locale.value)
    await pollRun(job.id)
  } catch (e) {
    setError(e)
  } finally {
    if (runningJobId.value === job.id) runningJobId.value = null
  }
}

async function pollRun(jobId: string) {
  const startedAt = Date.now()
  while (!unmounted && Date.now() - startedAt < pollBudgetMs) {
    await sleep(pollIntervalMs)
    if (unmounted) return
    let detail: IngestJob
    try {
      detail = await dataApi.jobs.getById(jobId)
    } catch (e) {
      setError(e)
      return
    }
    const run = detail.latest_run ?? null
    if (!run) continue
    replaceJobRun(jobId, run)
    const terminal = run.status === 'succeeded' || run.status === 'failed'
    if (terminal) {
      notice.value = run.status === 'succeeded'
        ? t('data.runSucceeded', locale.value)
        : t('data.runFailed', locale.value)
      if (expandedJobId.value === jobId) await loadRuns(jobId)
      return
    }
  }
  if (unmounted) return
  runTimeouts.value = { ...runTimeouts.value, [jobId]: true }
}

async function toggleRuns(job: IngestJob) {
  if (expandedJobId.value === job.id) {
    expandedJobId.value = null
    return
  }
  expandedJobId.value = job.id
  await loadRuns(job.id)
}

async function loadRuns(jobId: string) {
  loadingRuns.value = jobId
  try {
    runsByJob.value = { ...runsByJob.value, [jobId]: await dataApi.jobs.runs(jobId) }
  } catch (e) {
    setError(e)
  } finally {
    if (loadingRuns.value === jobId) loadingRuns.value = null
  }
}

function durationSeconds(run: IngestRun): number | null {
  if (!run.started_at || !run.finished_at) return null
  const duration = new Date(run.finished_at).getTime() - new Date(run.started_at).getTime()
  if (!Number.isFinite(duration) || duration < 0) return null
  return duration / 1000
}

async function loadQuality(datasetId: string) {
  if (!datasetId) {
    quality.value = null
    return
  }
  loadingQuality.value = true
  qualityError.value = null
  try {
    quality.value = await dataApi.quality.get(datasetId)
  } catch (e) {
    quality.value = null
    qualityError.value = detailText(e)
  } finally {
    loadingQuality.value = false
  }
}

function onDatasetChange() {
  showAddRule.value = false
  ruleFieldError.value = ''
  void loadQuality(selectedDatasetId.value)
}

async function profileNow() {
  if (!selectedDatasetId.value || profiling.value) return
  profiling.value = true
  qualityError.value = null
  notice.value = null
  error.value = null
  try {
    quality.value = await dataApi.quality.profile(selectedDatasetId.value)
    notice.value = t('data.profileReady', locale.value)
    await loadQuality(selectedDatasetId.value)
  } catch (e) {
    qualityError.value = detailText(e)
  } finally {
    profiling.value = false
  }
}

function openAddRule() {
  showAddRule.value = true
  ruleFieldError.value = ''
  ruleDraft.column_name = qualityProfile.value[0]?.column_name ?? ''
  ruleDraft.kind = 'not_null'
  ruleDraft.severity = 'error'
  ruleDraft.min = ''
  ruleDraft.max = ''
  ruleDraft.pattern = ''
}

function closeAddRule() {
  showAddRule.value = false
  ruleFieldError.value = ''
}

async function saveRule() {
  if (savingRule.value || !selectedDatasetId.value) return
  ruleFieldError.value = ''
  if (!ruleDraft.column_name.trim()) {
    ruleFieldError.value = t('data.ruleColumnRequired', locale.value)
    return
  }
  const params: { min?: number | null; max?: number | null; pattern?: string } = {}
  if (ruleDraft.kind === 'range') {
    const min = ruleDraft.min.trim() ? Number(ruleDraft.min) : null
    const max = ruleDraft.max.trim() ? Number(ruleDraft.max) : null
    if (min === null && max === null) {
      ruleFieldError.value = t('data.rangeRequired', locale.value)
      return
    }
    if (min !== null) params.min = min
    if (max !== null) params.max = max
  }
  if (ruleDraft.kind === 'regex') {
    if (!ruleDraft.pattern.trim()) {
      ruleFieldError.value = t('data.patternRequired', locale.value)
      return
    }
    params.pattern = ruleDraft.pattern
  }
  savingRule.value = true
  error.value = null
  notice.value = null
  try {
    await dataApi.quality.createRule(selectedDatasetId.value, {
      column_name: ruleDraft.column_name.trim(),
      kind: ruleDraft.kind,
      params,
      severity: ruleDraft.severity as 'error' | 'warn' | 'info',
    })
    notice.value = t('data.ruleAdded', locale.value)
    closeAddRule()
    await loadQuality(selectedDatasetId.value)
  } catch (e) {
    if (e instanceof ApiError && e.status === 422) {
      const message = detailText(e)
      if (/column|pattern|min|max|params/i.test(message)) {
        ruleFieldError.value = message
        savingRule.value = false
        return
      }
    }
    setError(e)
  } finally {
    savingRule.value = false
  }
}

async function deleteRule(rule: QualityRule) {
  if (!selectedDatasetId.value) return
  if (!window.confirm(t('data.deleteRuleConfirm', locale.value))) return
  removingRuleId.value = rule.id
  error.value = null
  notice.value = null
  try {
    await dataApi.quality.deleteRule(selectedDatasetId.value, rule.id)
    notice.value = t('data.ruleDeleted', locale.value)
    await loadQuality(selectedDatasetId.value)
  } catch (e) {
    setError(e)
  } finally {
    removingRuleId.value = null
  }
}

function ruleKindLabel(kind: string): string {
  const key = RULE_KIND_KEYS[kind]
  return key ? t(key, locale.value) : kind
}

function severityLabel(severity: string): string {
  const key = SEVERITY_KEYS[severity]
  return key ? t(key, locale.value) : severity
}

function ruleStatus(state: QualityRuleState): string | null {
  return state.latest_result?.status ?? null
}

function ruleStatusLabel(state: QualityRuleState): string {
  const status = ruleStatus(state)
  if (!status) return t('data.notMeasured', locale.value)
  if (status === 'pass') return t('data.statusPass', locale.value)
  if (status === 'fail') return t('data.statusFail', locale.value)
  return t('data.statusError', locale.value)
}

function ruleStatusTone(state: QualityRuleState): string {
  const status = ruleStatus(state)
  if (status === 'pass') return 'ok'
  if (status === 'fail') return 'err'
  if (status === 'error') return 'warn'
  return 'plain'
}

function ruleViolations(state: QualityRuleState): number | null {
  const value = state.latest_result?.observed?.violations
  return typeof value === 'number' ? value : null
}

function ruleCheckedAt(state: QualityRuleState): string | null {
  return state.latest_result?.checked_at ?? null
}
</script>

<template>
  <section class="data-page">
    <PageHeader :title="t('data.title', locale)" :subtitle="t('data.subtitle', locale)">
      <template #actions>
        <button class="btn-secondary" type="button" :disabled="loadingSources || loadingJobs" @click="refreshAll">
          {{ t('data.refreshAll', locale) }}
        </button>
        <button class="btn-primary" type="button" @click="focusConnect">
          {{ t('data.connectSource', locale) }}
        </button>
      </template>
    </PageHeader>

    <div v-if="error" class="banner error-banner-row" data-tone="warn" role="alert">
      <span class="badge err">{{ error.code ?? t('common.error', locale) }}</span>
      <span>{{ error.detail }}</span>
      <button class="btn-ghost btn-xs" type="button" @click="error = null">
        {{ t('common.close', locale) }}
      </button>
    </div>

    <div v-if="notice" class="banner notice-row" role="status">
      <span class="badge ok">{{ t('data.ok', locale) }}</span>
      <span>{{ notice }}</span>
    </div>

    <DcCard :title="t('data.sources', locale)">
      <template #actions>
        <span class="badge plain">{{ sources.length }}</span>
      </template>

      <p class="muted panel-note">{{ t('data.sourcesHelp', locale) }}</p>

      <div v-if="loadingSources" class="skeleton-stack" aria-hidden="true">
        <span /><span /><span />
      </div>

      <div v-else-if="!sources.length" class="empty sources-empty">
        <div class="e-ico"><svg aria-hidden="true"><use href="#i-database" /></svg></div>
        <h3>{{ t('data.noSources', locale) }}</h3>
        <p class="muted">{{ t('data.noSourcesHelp', locale) }}</p>
      </div>

      <div v-else class="table-scroll">
        <table class="dt data-table sources-table">
          <thead>
            <tr>
              <th scope="col">{{ t('data.name', locale) }}</th>
              <th scope="col">{{ t('data.kind', locale) }}</th>
              <th scope="col">{{ t('data.target', locale) }}</th>
              <th scope="col">{{ t('data.readOnly', locale) }}</th>
              <th scope="col">{{ t('data.status', locale) }}</th>
              <th scope="col">{{ t('common.actions', locale) }}</th>
            </tr>
          </thead>
          <tbody>
            <template v-for="source in sources" :key="source.id">
              <tr class="source-row">
                <td>
                  <div class="cell-stack">
                    <span class="cell-strong" :title="source.name">{{ source.name }}</span>
                    <span class="muted mono" :title="source.id">{{ source.id }}</span>
                  </div>
                </td>
                <td>
                  <span class="badge plain">
                    {{ source.kind === 'postgres' ? t('data.kindPostgres', locale) : t('data.kindRest', locale) }}
                  </span>
                </td>
                <td>
                  <code class="mono target-cell" :title="sourceTarget(source)">{{ sourceTarget(source) }}</code>
                </td>
                <td>
                  <span v-if="source.read_only" class="badge ok">{{ t('data.readOnly', locale) }}</span>
                  <span v-else class="muted">{{ t('data.unknown', locale) }}</span>
                </td>
                <td>
                  <div class="cell-stack">
                    <span class="badge" :class="sourceStatusTone(source)">{{ sourceStatusLabel(source) }}</span>
                    <span class="muted tested-at">
                      {{ formatDateTime(source.last_tested_at, locale) }}
                    </span>
                  </div>
                </td>
                <td>
                  <div class="row source-actions">
                    <button
                      class="btn-secondary btn-xs"
                      type="button"
                      :disabled="testingId === source.id"
                      @click="testSource(source)"
                    >
                      {{ testingId === source.id ? t('data.testing', locale) : t('data.test', locale) }}
                    </button>
                    <button class="btn-secondary btn-xs" type="button" @click="openBrowse(source)">
                      {{ t('data.browse', locale) }}
                    </button>
                    <button
                      class="btn-danger btn-xs"
                      type="button"
                      :disabled="deletingId === source.id"
                      @click="deleteSource(source)"
                    >
                      {{ t('common.delete', locale) }}
                    </button>
                  </div>
                </td>
              </tr>
              <tr
                v-if="testResults[source.id] || testErrors[source.id] || source.last_error"
                class="detail-row"
              >
                <td colspan="6">
                  <div v-if="testResults[source.id]" class="test-result">
                    <span class="badge ok">{{ t('data.statusConnected', locale) }}</span>
                    ·
                    <span class="mono">
                      {{ num(testResults[source.id]?.latency_ms) }} {{ t('data.milliseconds', locale) }}
                    </span>
                    <span v-if="testResults[source.id]?.server_version" class="muted mono">
                      {{ testResults[source.id]?.server_version }}
                    </span>
                  </div>
                  <div v-else-if="testErrors[source.id]" class="test-result" role="alert">
                    <span class="badge err">{{ t('data.statusFailed', locale) }}</span>
                    <span class="muted">{{ testErrors[source.id] }}</span>
                  </div>
                  <div v-if="source.last_error" class="last-error">
                    <span class="trace-k">{{ t('data.lastError', locale) }}</span>
                    <span class="mono">{{ source.last_error }}</span>
                  </div>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>

      <form class="source-form" @submit.prevent="submitSource">
        <h3 class="form-title">{{ t('data.connectTitle', locale) }}</h3>
        <div class="form-grid">
          <label class="field">
            <span>{{ t('data.name', locale) }}</span>
            <input
              ref="nameInput"
              v-model="sourceForm.name"
              type="text"
              :placeholder="t('data.sourceNamePlaceholder', locale)"
            />
            <span v-if="sourceFieldErrors.name" class="field-error" role="alert">{{ sourceFieldErrors.name }}</span>
          </label>
          <label class="field">
            <span>{{ t('data.kind', locale) }}</span>
            <select v-model="sourceForm.kind">
              <option value="postgres">{{ t('data.kindPostgres', locale) }}</option>
              <option value="rest">{{ t('data.kindRest', locale) }}</option>
            </select>
          </label>

          <template v-if="sourceForm.kind === 'postgres'">
            <label class="field field-wide">
              <span>{{ t('data.dsn', locale) }}</span>
              <input
                v-model="sourceForm.dsn"
                type="password"
                autocomplete="new-password"
                :placeholder="t('data.dsnPlaceholder', locale)"
              />
              <span class="field-help">{{ t('data.dsnHelp', locale) }}</span>
              <span v-if="sourceFieldErrors.dsn" class="field-error" role="alert">{{ sourceFieldErrors.dsn }}</span>
            </label>
            <label class="field">
              <span>{{ t('data.schema', locale) }}</span>
              <input v-model="sourceForm.schema" type="text" />
              <span class="field-help">{{ t('data.schemaHelp', locale) }}</span>
              <span v-if="sourceFieldErrors.schema" class="field-error" role="alert">{{ sourceFieldErrors.schema }}</span>
            </label>
            <label class="field checkbox-field">
              <span class="row readonly-row">
                <input type="checkbox" checked disabled />
                <span>{{ t('data.readOnlyNote', locale) }}</span>
              </span>
            </label>
          </template>

          <template v-else>
            <label class="field field-wide">
              <span>{{ t('data.baseUrl', locale) }}</span>
              <input
                v-model="sourceForm.base_url"
                type="url"
                autocomplete="url"
                :placeholder="t('data.baseUrlPlaceholder', locale)"
              />
              <span v-if="sourceFieldErrors.base_url" class="field-error" role="alert">{{ sourceFieldErrors.base_url }}</span>
            </label>
            <label class="field">
              <span>{{ t('data.authHeader', locale) }}</span>
              <input v-model="sourceForm.auth_header" type="text" />
              <span class="field-help">{{ t('data.authHeaderHelp', locale) }}</span>
              <span v-if="sourceFieldErrors.auth_header" class="field-error" role="alert">{{ sourceFieldErrors.auth_header }}</span>
            </label>
            <label class="field">
              <span>{{ t('data.token', locale) }}</span>
              <input
                v-model="sourceForm.token"
                type="password"
                autocomplete="new-password"
                :placeholder="t('data.tokenPlaceholder', locale)"
              />
              <span class="field-help">{{ t('data.tokenHelp', locale) }}</span>
              <span v-if="sourceFieldErrors.token" class="field-error" role="alert">{{ sourceFieldErrors.token }}</span>
            </label>
            <label class="field">
              <span>{{ t('data.recordsPath', locale) }}</span>
              <input
                v-model="sourceForm.records_path"
                type="text"
                :placeholder="t('data.recordsPathPlaceholder', locale)"
              />
              <span class="field-help">{{ t('data.recordsPathHelp', locale) }}</span>
              <span v-if="sourceFieldErrors.records_path" class="field-error" role="alert">{{ sourceFieldErrors.records_path }}</span>
            </label>
          </template>
        </div>
        <div class="row">
          <button class="btn-primary" type="submit" :disabled="savingSource">
            {{ savingSource ? t('data.connecting', locale) : t('data.connectSource', locale) }}
          </button>
        </div>
      </form>
    </DcCard>

    <DcCard :title="t('data.jobs', locale)">
      <template #actions>
        <span class="badge plain">{{ jobs.length }}</span>
      </template>

      <p class="muted panel-note">{{ t('data.jobsHelp', locale) }}</p>

      <div v-if="loadingJobs" class="skeleton-stack" aria-hidden="true">
        <span /><span /><span />
      </div>

      <div v-else-if="!jobs.length" class="empty jobs-empty">
        <div class="e-ico"><svg aria-hidden="true"><use href="#i-layers" /></svg></div>
        <h3>{{ t('data.noJobs', locale) }}</h3>
        <p class="muted">{{ t('data.noJobsHelp', locale) }}</p>
      </div>

      <div v-else class="table-scroll">
        <table class="dt data-table jobs-table">
          <thead>
            <tr>
              <th scope="col">{{ t('data.job', locale) }}</th>
              <th scope="col">{{ t('data.source', locale) }}</th>
              <th scope="col">{{ t('data.table', locale) }}</th>
              <th scope="col">{{ t('data.mode', locale) }}</th>
              <th scope="col">{{ t('data.schedule', locale) }}</th>
              <th scope="col">{{ t('data.latestRun', locale) }}</th>
              <th scope="col">{{ t('data.rows', locale) }}</th>
              <th scope="col">{{ t('data.lastRun', locale) }}</th>
              <th scope="col">{{ t('common.actions', locale) }}</th>
            </tr>
          </thead>
          <tbody>
            <template v-for="job in jobs" :key="job.id">
              <tr class="job-row">
                <td>
                  <div class="cell-stack">
                    <span class="cell-strong" :title="job.name">{{ job.name }}</span>
                    <span class="muted mono" :title="job.id">{{ job.id }}</span>
                  </div>
                </td>
                <td><span class="ellipsis" :title="sourceName(job.data_source_id)">{{ sourceName(job.data_source_id) }}</span></td>
                <td><code class="mono ellipsis" :title="job.target_table">{{ job.target_table }}</code></td>
                <td>
                  <div class="cell-stack">
                    <span class="badge plain">{{ modeLabel(job) }}</span>
                    <span v-if="job.watermark_column" class="muted mono ellipsis" :title="job.watermark_column">
                      {{ job.watermark_column }}
                    </span>
                  </div>
                </td>
                <td><span class="mono ellipsis" :title="job.schedule_cron ?? ''">{{ job.schedule_cron ?? t('data.manual', locale) }}</span></td>
                <td>
                  <div class="cell-stack">
                    <span class="badge" :class="runTone(job)">{{ runStatusLabel(job) }}</span>
                    <span v-if="runTimeouts[job.id]" class="still-running">{{ t('data.stillRunning', locale) }}</span>
                  </div>
                </td>
                <td><span class="mono">{{ rowsWrittenLabel(job) }}</span></td>
                <td>
                  <span class="muted run-time">
                    {{ latestRunOf(job) ? formatDateTime(lastRunAt(job), locale) : t('data.unknown', locale) }}
                  </span>
                </td>
                <td>
                  <div class="row job-actions">
                    <button
                      class="btn-secondary btn-xs"
                      type="button"
                      :disabled="runningJobId !== null"
                      @click="runNow(job)"
                    >
                      {{ runningJobId === job.id ? t('data.runStatus.running', locale) : t('data.runNow', locale) }}
                    </button>
                    <button class="btn-ghost btn-xs" type="button" @click="toggleRuns(job)">
                      {{ expandedJobId === job.id ? t('data.hideRuns', locale) : t('data.viewRuns', locale) }}
                    </button>
                  </div>
                </td>
              </tr>
              <tr v-if="jobError(job) || expandedJobId === job.id" class="detail-row">
                <td colspan="9">
                  <div v-if="jobError(job)" class="job-error" role="alert">
                    <span class="badge err">{{ t('data.statusFailed', locale) }}</span>
                    <span class="mono">{{ jobError(job) }}</span>
                  </div>

                  <div v-if="expandedJobId === job.id" class="runs-panel">
                    <h4 class="table-title">{{ t('data.runs', locale) }}</h4>
                    <div v-if="loadingRuns === job.id" class="muted">{{ t('common.loading', locale) }}</div>
                    <div v-else-if="!runsByJob[job.id]?.length" class="muted">
                      {{ t('data.noRunHistory', locale) }}
                    </div>
                    <div v-else class="table-scroll">
                      <table class="dt data-table runs-table">
                        <thead>
                          <tr>
                            <th scope="col">{{ t('data.job', locale) }}</th>
                            <th scope="col">{{ t('data.status', locale) }}</th>
                            <th scope="col">{{ t('data.started', locale) }}</th>
                            <th scope="col">{{ t('data.finished', locale) }}</th>
                            <th scope="col">{{ t('data.duration', locale) }}</th>
                            <th scope="col">{{ t('data.rowsRead', locale) }}</th>
                            <th scope="col">{{ t('data.rowsWritten', locale) }}</th>
                            <th scope="col">{{ t('data.dataset', locale) }}</th>
                          </tr>
                        </thead>
                        <tbody>
                          <template v-for="run in runsByJob[job.id]" :key="run.id">
                            <tr>
                              <td><code class="mono" :title="run.id">{{ run.id }}</code></td>
                              <td>
                                <span class="badge" :class="run.status === 'succeeded' ? 'ok' : run.status === 'failed' ? 'err' : run.status === 'running' ? 'blue' : 'warn'">
                                  {{ RUN_STATUS_KEYS[run.status] ? t(RUN_STATUS_KEYS[run.status], locale) : run.status }}
                                </span>
                              </td>
                              <td><span class="muted">{{ formatDateTime(run.started_at, locale) }}</span></td>
                              <td><span class="muted">{{ formatDateTime(run.finished_at, locale) }}</span></td>
                              <td>
                                <span v-if="durationSeconds(run) !== null" class="mono">
                                  {{ num(durationSeconds(run), 1) }} {{ t('data.seconds', locale) }}
                                </span>
                                <span v-else class="muted">{{ t('data.notMeasured', locale) }}</span>
                              </td>
                              <td><span class="mono">{{ num(run.rows_read) }}</span></td>
                              <td><span class="mono">{{ num(run.rows_written) }}</span></td>
                              <td>
                                <NuxtLink
                                  v-if="run.dataset_id"
                                  class="dataset-link mono"
                                  :to="`/data?dataset=${run.dataset_id}`"
                                  :title="run.dataset_id"
                                >
                                  {{ run.dataset_id }}
                                </NuxtLink>
                                <span v-else class="muted">{{ t('data.unknown', locale) }}</span>
                              </td>
                            </tr>
                            <tr v-if="run.error" class="run-error-row">
                              <td colspan="8">
                                <span class="trace-k">{{ t('data.error', locale) }}</span>
                                <span class="mono job-error-text">{{ run.error }}</span>
                              </td>
                            </tr>
                          </template>
                        </tbody>
                      </table>
                    </div>
                  </div>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
    </DcCard>

    <DcCard :title="t('data.qualityTitle', locale)">
      <p class="muted panel-note">{{ t('data.qualityHelp', locale) }}</p>

      <div class="quality-toolbar">
        <label class="field quality-dataset-field">
          <span>{{ t('data.dataset', locale) }}</span>
          <select v-model="selectedDatasetId" @change="onDatasetChange">
            <option value="">{{ t('data.selectDataset', locale) }}</option>
            <option v-for="dataset in datasets" :key="dataset.dataset_id" :value="dataset.dataset_id">
              {{ dataset.name }}
            </option>
          </select>
        </label>
      </div>

      <div v-if="loadingDatasets" class="muted">{{ t('common.loading', locale) }}</div>

      <div v-else-if="!selectedDatasetId" class="empty quality-empty">
        <div class="e-ico"><svg aria-hidden="true"><use href="#i-check-square" /></svg></div>
        <h3>{{ t('data.selectDataset', locale) }}</h3>
        <p class="muted">{{ t('data.selectDatasetHelp', locale) }}</p>
      </div>

      <div v-else-if="loadingQuality" class="skeleton-stack" aria-hidden="true">
        <span /><span /><span />
      </div>

      <div v-else-if="qualityError" class="banner quality-error" data-tone="warn" role="alert">
        <span class="badge err">{{ t('data.loadError', locale) }}</span>
        <span>{{ qualityError }}</span>
      </div>

      <template v-else-if="quality">
        <div v-if="!hasProfile" class="empty quality-empty no-profile">
          <div class="e-ico"><svg aria-hidden="true"><use href="#i-pulse" /></svg></div>
          <h3>{{ t('data.noProfile', locale) }}</h3>
          <p class="muted">{{ t('data.noProfileHelp', locale) }}</p>
          <button class="btn-primary" type="button" :disabled="profiling" @click="profileNow">
            {{ profiling ? t('data.profiling', locale) : t('data.profileNow', locale) }}
          </button>
        </div>

        <template v-else>
          <h3 class="table-title">{{ t('data.profile', locale) }}</h3>
          <div class="table-scroll">
            <table class="dt data-table profile-table">
              <thead>
                <tr>
                  <th scope="col">{{ t('data.column', locale) }}</th>
                  <th scope="col">{{ t('data.dtype', locale) }}</th>
                  <th scope="col">{{ t('data.nullPercent', locale) }}</th>
                  <th scope="col">{{ t('data.distinct', locale) }}</th>
                  <th scope="col">{{ t('data.min', locale) }}</th>
                  <th scope="col">{{ t('data.max', locale) }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="column in qualityProfile" :key="column.column_name">
                  <td><span class="cell-strong" :title="column.column_name">{{ column.column_name }}</span></td>
                  <td><span class="badge plain">{{ column.dtype }}</span></td>
                  <td><span class="mono">{{ num(column.null_rate * 100, 1) }}%</span></td>
                  <td><span class="mono">{{ num(column.distinct_count) }}</span></td>
                  <td><span class="mono ellipsis" :title="column.min_value === null ? '' : String(column.min_value)">{{ column.min_value ?? '—' }}</span></td>
                  <td><span class="mono ellipsis" :title="column.max_value === null ? '' : String(column.max_value)">{{ column.max_value ?? '—' }}</span></td>
                </tr>
              </tbody>
            </table>
          </div>

          <div class="rules-head">
            <h3 class="table-title">{{ t('data.rules', locale) }}</h3>
            <button v-if="!showAddRule" class="btn-secondary btn-sm" type="button" @click="openAddRule">
              + {{ t('data.addRule', locale) }}
            </button>
          </div>

          <form v-if="showAddRule" class="rule-form" @submit.prevent="saveRule">
            <div class="form-grid rule-grid">
              <label class="field">
                <span>{{ t('data.ruleColumn', locale) }}</span>
                <select v-model="ruleDraft.column_name">
                  <option v-for="column in qualityProfile" :key="column.column_name" :value="column.column_name">
                    {{ column.column_name }}
                  </option>
                </select>
              </label>
              <label class="field">
                <span>{{ t('data.ruleKind', locale) }}</span>
                <select v-model="ruleDraft.kind">
                  <option value="not_null">{{ t('data.ruleKindLabels.not_null', locale) }}</option>
                  <option value="unique">{{ t('data.ruleKindLabels.unique', locale) }}</option>
                  <option value="range">{{ t('data.ruleKindLabels.range', locale) }}</option>
                  <option value="regex">{{ t('data.ruleKindLabels.regex', locale) }}</option>
                </select>
              </label>
              <label class="field">
                <span>{{ t('data.severity', locale) }}</span>
                <select v-model="ruleDraft.severity">
                  <option value="error">{{ t('data.severityLabels.error', locale) }}</option>
                  <option value="warn">{{ t('data.severityLabels.warn', locale) }}</option>
                  <option value="info">{{ t('data.severityLabels.info', locale) }}</option>
                </select>
              </label>
              <template v-if="ruleDraft.kind === 'range'">
                <label class="field">
                  <span>{{ t('data.minValue', locale) }}</span>
                  <input v-model="ruleDraft.min" type="number" step="any" />
                </label>
                <label class="field">
                  <span>{{ t('data.maxValue', locale) }}</span>
                  <input v-model="ruleDraft.max" type="number" step="any" />
                </label>
              </template>
              <label v-if="ruleDraft.kind === 'regex'" class="field">
                <span>{{ t('data.pattern', locale) }}</span>
                <input v-model="ruleDraft.pattern" type="text" />
              </label>
            </div>
            <span v-if="ruleFieldError" class="field-error" role="alert">{{ ruleFieldError }}</span>
            <div class="row rule-form-actions">
              <button class="btn-primary btn-sm" type="submit" :disabled="savingRule">
                {{ savingRule ? t('data.savingRule', locale) : t('data.saveRule', locale) }}
              </button>
              <button class="btn-ghost btn-sm" type="button" @click="closeAddRule">
                {{ t('data.cancelAddRule', locale) }}
              </button>
            </div>
          </form>

          <div v-if="!qualityRules.length" class="empty quality-empty no-rules">
            <h3>{{ t('data.noRules', locale) }}</h3>
            <p class="muted">{{ t('data.noRulesHelp', locale) }}</p>
          </div>

          <div v-else class="table-scroll">
            <table class="dt data-table quality-table">
              <thead>
                <tr>
                  <th scope="col">{{ t('data.column', locale) }}</th>
                  <th scope="col">{{ t('data.ruleKind', locale) }}</th>
                  <th scope="col">{{ t('data.severity', locale) }}</th>
                  <th scope="col">{{ t('data.status', locale) }}</th>
                  <th scope="col">{{ t('data.violations', locale) }}</th>
                  <th scope="col">{{ t('data.checkedAt', locale) }}</th>
                  <th scope="col">{{ t('common.actions', locale) }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="state in qualityRules" :key="state.rule.id">
                  <td><span class="cell-strong" :title="state.rule.column_name">{{ state.rule.column_name }}</span></td>
                  <td><span class="badge plain">{{ ruleKindLabel(state.rule.kind) }}</span></td>
                  <td><span class="muted">{{ severityLabel(state.rule.severity) }}</span></td>
                  <td>
                    <span class="badge rule-status" :class="ruleStatusTone(state)" :data-status="ruleStatus(state) ?? 'unknown'">
                      {{ ruleStatusLabel(state) }}
                    </span>
                  </td>
                  <td>
                    <span v-if="ruleViolations(state) !== null" class="mono violations">
                      {{ num(ruleViolations(state)) }} {{ t('data.violations', locale) }}
                    </span>
                    <span v-else class="muted">{{ t('data.notMeasured', locale) }}</span>
                  </td>
                  <td>
                    <span class="muted">{{ ruleCheckedAt(state) ? formatDateTime(ruleCheckedAt(state), locale) : t('data.notMeasured', locale) }}</span>
                  </td>
                  <td>
                    <button
                      class="btn-danger btn-xs"
                      type="button"
                      :disabled="removingRuleId === state.rule.id"
                      @click="deleteRule(state.rule)"
                    >
                      {{ t('common.delete', locale) }}
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>
      </template>
    </DcCard>

    <template v-if="browsingSource">
      <div class="scrim" @click="closeBrowse" />
      <aside
        class="drawer browse-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="browse-title"
      >
        <div class="drawer-head">
          <div class="dh-top">
            <div>
              <h2 id="browse-title">{{ t('data.browseTitle', locale) }}</h2>
              <p class="muted">{{ browsingSource.name }}</p>
            </div>
            <button class="icon-btn" type="button" :aria-label="t('common.close', locale)" @click="closeBrowse">
              ×
            </button>
          </div>
        </div>
        <div class="drawer-body">
          <section>
            <h3 class="table-title">{{ t('data.tables', locale) }}</h3>
            <div v-if="loadingTables" class="muted">{{ t('common.loading', locale) }}</div>
            <div v-else-if="!browseTables.length" class="empty browse-empty">
              <h3>{{ t('data.noTables', locale) }}</h3>
              <p class="muted">{{ t('data.noTablesHelp', locale) }}</p>
            </div>
            <div v-else class="table-list">
              <button
                v-for="table in browseTables"
                :key="tableKey(table)"
                class="table-option"
                type="button"
                :aria-pressed="isSelectedTable(table)"
                :class="{ active: isSelectedTable(table) }"
                @click="selectTable(table)"
              >
                <span class="mono">{{ tableKey(table) }}</span>
                <span class="badge plain">{{ table.kind }}</span>
              </button>
            </div>
          </section>

          <section>
            <h3 class="table-title">{{ t('data.preview', locale) }}</h3>
            <p class="muted panel-note">{{ t('data.previewHelp', locale) }}</p>
            <div v-if="loadingPreview" class="muted">{{ t('common.loading', locale) }}</div>
            <div v-else-if="previewError" class="banner" data-tone="warn" role="alert">
              <span class="badge err">{{ t('data.error', locale) }}</span>
              <span>{{ previewError }}</span>
            </div>
            <div v-else-if="!selectedTable" class="empty browse-empty">
              <p class="muted">{{ t('data.selectTable', locale) }}</p>
            </div>
            <template v-else-if="preview">
              <div v-if="preview.truncated" class="banner truncated-notice" data-tone="warn" role="status">
                <span class="badge warn">{{ t('data.truncated', locale) }}</span>
              </div>
              <div v-if="!preview.columns.length" class="empty browse-empty">
                <p class="muted">{{ t('data.noRows', locale) }}</p>
              </div>
              <div v-else class="table-scroll">
                <table class="dt preview-table">
                  <thead>
                    <tr>
                      <th v-for="column in preview.columns" :key="column" scope="col" :title="column">
                        {{ column }}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(row, rowIndex) in preview.rows" :key="rowIndex">
                      <td v-for="(cell, cellIndex) in row" :key="cellIndex" :title="formatCell(cell)">
                        <span class="mono">{{ formatCell(cell) }}</span>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </template>
          </section>
        </div>
        <div v-if="selectedTable" class="drawer-foot">
          <button class="btn-primary btn-sm" type="button" :disabled="creatingJob" @click="createJobFromPreview">
            {{ creatingJob ? t('data.creatingJob', locale) : t('data.createIngestJob', locale) }}
          </button>
        </div>
      </aside>
    </template>
  </section>
</template>

<style scoped>
.error-banner-row,
.notice-row {
  margin-bottom: 14px;
}
.error-banner-row > span:nth-child(2),
.notice-row > span:nth-child(2) {
  flex: 1;
  min-width: 0;
}
.panel-note {
  font-size: 11.5px;
  margin-bottom: 10px;
}
.sources-empty,
.jobs-empty,
.qual-empty,
.quality-empty,
.browse-empty {
  padding: 20px 12px;
}
.table-title {
  font-size: 12px;
  font-weight: 650;
  letter-spacing: 0.03em;
  text-transform: uppercase;
  color: var(--muted);
  margin-bottom: 9px;
}
.form-title {
  font-size: 12px;
  font-weight: 650;
  letter-spacing: 0.03em;
  text-transform: uppercase;
  color: var(--muted);
  margin-bottom: 9px;
}
.data-table {
  table-layout: fixed;
  width: 100%;
}
.data-table th,
.data-table td {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: top;
}
.sources-table th:nth-child(1) { width: 18%; }
.sources-table th:nth-child(2) { width: 8%; }
.sources-table th:nth-child(3) { width: 22%; }
.sources-table th:nth-child(4) { width: 9%; }
.sources-table th:nth-child(5) { width: 15%; }
.sources-table th:nth-child(6) { width: 28%; }
.target-cell {
  font-size: 11.5px;
  display: block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tested-at {
  font-size: 10.5px;
  white-space: nowrap;
}
.source-actions,
.job-actions {
  flex-wrap: nowrap;
  gap: 4px;
}
.source-actions .btn,
.job-actions .btn {
  flex: 0 0 auto;
}
.detail-row td {
  background: var(--surface-2);
  padding-top: 7px;
  padding-bottom: 7px;
}
.test-result {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 11.5px;
}
.last-error {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 7px;
  font-size: 11.5px;
  color: var(--crit-ink);
  margin-top: 4px;
}
.trace-k {
  font-family: var(--font-mono);
  font-size: 9.5px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--faint);
}
.source-form {
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px solid var(--border);
}
.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 14px;
}
.field-wide {
  grid-column: 1 / -1;
}
.field-help {
  font-size: 10.5px;
  font-weight: 400;
  color: var(--faint);
  line-height: 1.4;
}
.field-error {
  font-size: 10.5px;
  font-weight: 500;
  color: var(--crit-ink);
}
.checkbox-field {
  justify-content: flex-end;
}
.readonly-row {
  gap: 7px;
  font-weight: 500;
  color: var(--muted);
  font-size: 12px;
}
.jobs-table th:nth-child(1) { width: 17%; }
.jobs-table th:nth-child(2) { width: 10%; }
.jobs-table th:nth-child(3) { width: 12%; }
.jobs-table th:nth-child(4) { width: 10%; }
.jobs-table th:nth-child(5) { width: 8%; }
.jobs-table th:nth-child(6) { width: 10%; }
.jobs-table th:nth-child(7) { width: 10%; }
.jobs-table th:nth-child(8) { width: 10%; }
.jobs-table th:nth-child(9) { width: 13%; }
.ellipsis {
  display: block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.run-time {
  font-size: 10.5px;
  white-space: nowrap;
}
.still-running {
  display: block;
  font-size: 10px;
  line-height: 1.3;
  color: var(--warn-ink);
  white-space: normal;
}
.job-error {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 8px;
  color: var(--crit-ink);
  font-size: 11.5px;
}
.job-error-text {
  overflow-wrap: anywhere;
}
.runs-panel {
  margin-top: 8px;
}
.runs-table th:nth-child(1) { width: 18%; }
.runs-table th:nth-child(2) { width: 10%; }
.runs-table th:nth-child(3) { width: 14%; }
.runs-table th:nth-child(4) { width: 14%; }
.runs-table th:nth-child(5) { width: 10%; }
.runs-table th:nth-child(6) { width: 9%; }
.runs-table th:nth-child(7) { width: 10%; }
.runs-table th:nth-child(8) { width: 15%; }
.dataset-link {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--accent-ink);
}
.run-error-row td {
  background: var(--crit-soft);
  padding-top: 5px;
  padding-bottom: 5px;
}
.quality-toolbar {
  margin-bottom: 12px;
}
.quality-dataset-field {
  max-width: 340px;
  margin-bottom: 0;
}
.quality-error {
  margin-bottom: 12px;
}
.rules-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 16px;
}
.rules-head .table-title {
  margin-bottom: 0;
}
.quality-table th:nth-child(1) { width: 20%; }
.quality-table th:nth-child(2) { width: 12%; }
.quality-table th:nth-child(3) { width: 10%; }
.quality-table th:nth-child(4) { width: 10%; }
.quality-table th:nth-child(5) { width: 16%; }
.quality-table th:nth-child(6) { width: 20%; }
.quality-table th:nth-child(7) { width: 12%; }
.profile-table th:nth-child(1) { width: 24%; }
.profile-table th:nth-child(2) { width: 14%; }
.profile-table th:nth-child(3) { width: 12%; }
.profile-table th:nth-child(4) { width: 12%; }
.profile-table th:nth-child(5) { width: 19%; }
.profile-table th:nth-child(6) { width: 19%; }
.rule-form {
  margin: 10px 0 14px;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: var(--r);
  background: var(--surface-2);
}
.rule-grid .field {
  margin-bottom: 8px;
}
.rule-form-actions {
  margin-top: 4px;
}
.table-list {
  display: flex;
  flex-direction: column;
  gap: 3px;
  max-height: 260px;
  overflow-y: auto;
}
.table-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  width: 100%;
  padding: 6px 9px;
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  background: var(--surface);
  font-size: 12px;
  text-align: start;
}
.table-option:hover {
  background: var(--surface-2);
}
.table-option.active {
  border-color: var(--accent);
  background: var(--accent-soft);
  color: var(--accent-ink);
}
.truncated-notice {
  margin-bottom: 8px;
}
.preview-table {
  table-layout: auto;
  min-width: 100%;
}
.preview-table th,
.preview-table td {
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.skeleton-stack {
  display: flex;
  flex-direction: column;
  gap: 9px;
  padding: 4px 0;
}
.skeleton-stack span {
  display: block;
  height: 13px;
  border-radius: var(--r-sm);
  background: linear-gradient(90deg, var(--surface-2), var(--surface-3), var(--surface-2));
  background-size: 200% 100%;
  animation: data-shimmer 1.2s ease-in-out infinite;
}
.skeleton-stack span:nth-child(2n) {
  width: 72%;
}
.skeleton-stack span:nth-child(3n) {
  width: 84%;
}
@keyframes data-shimmer {
  from { background-position: 200% 0; }
  to { background-position: -200% 0; }
}
.browse-drawer .drawer-body {
  gap: 20px;
}
@media (max-width: 820px) {
  .form-grid {
    grid-template-columns: 1fr;
  }
  .field-wide {
    grid-column: auto;
  }
}
</style>
