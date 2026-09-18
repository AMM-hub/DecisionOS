<script setup lang="ts">
import type {
  GrainCandidate, ParsePreview, PutContentResponse, UploadFinalizeResponse,
  UploadInitResponse, UploadListItem
} from '~/shared/types'

const { get, post, postWithKey, putBytes, base } = useApi()

const file = ref<File | null>(null)
const busy = ref(false)
const error = ref<string | null>(null)
const notice = ref<string | null>(null)
const step = ref<'pick' | 'uploading' | 'preview' | 'grain'>('pick')

const uploadId = ref<string | null>(null)
const datasetId = ref<string | null>(null)
const revision = ref<number | null>(null)
const preview = ref<ParsePreview | null>(null)
const grainCandidates = ref<GrainCandidate[]>([])
const chosenKey = ref<number | null>(null)
const grainConfirmed = ref(false)
const history = ref<UploadListItem[]>([])

function onPick(e: Event) {
  const input = e.target as HTMLInputElement
  file.value = input.files?.[0] ?? null
}

async function loadHistory() {
  try { history.value = await get<UploadListItem[]>('/uploads') } catch { /* non-fatal */ }
}
onMounted(loadHistory)

async function start() {
  if (!file.value) return
  busy.value = true
  error.value = null
  notice.value = null
  try {
    step.value = 'uploading'
    const init = await postWithKey<UploadInitResponse>('/uploads', crypto.randomUUID(), {
      filename: file.value.name,
      size_bytes: file.value.size,
      workspace_id: 'ws-support-ops'
    })
    uploadId.value = init.upload_id
    const bytes = await file.value.arrayBuffer()
    // target_path is server-absolute (includes /v1); strip it to rebase on our API base.
    const contentPath = init.target_path.replace(/^\/v1/, '')
    const put = await putBytes<PutContentResponse>(contentPath, bytes)
    notice.value = `Quarantined · sha256 ${put.sha256.slice(0, 12)}…`
    const fin = await post<UploadFinalizeResponse>(`/uploads/${init.upload_id}/finalize`)
    if (fin.status === 'rejected') {
      error.value = 'Upload rejected by scan: ' + (fin.scan?.reasons.join(', ') ?? 'unknown')
      step.value = 'pick'
      return
    }
    datasetId.value = fin.dataset_id ?? null
    revision.value = fin.revision ?? null
    preview.value = await get<ParsePreview>(`/uploads/${init.upload_id}/preview`)
    step.value = 'preview'
    await loadHistory()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
    step.value = 'pick'
  } finally {
    busy.value = false
  }
}

async function loadGrain() {
  if (!uploadId.value) return
  busy.value = true
  error.value = null
  try {
    grainCandidates.value = await get<GrainCandidate[]>(`/uploads/${uploadId.value}/grain-candidates`)
    step.value = 'grain'
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    busy.value = false
  }
}

async function confirmGrain() {
  if (!datasetId.value || chosenKey.value === null) return
  busy.value = true
  error.value = null
  try {
    // Grain is confirmed on the DATASET (spec §9.2), not the upload.
    await post(`/datasets/${datasetId.value}/grain-confirmation`, {
      key_columns: grainCandidates.value[chosenKey.value].key_columns
    })
    grainConfirmed.value = true
    await loadHistory()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    busy.value = false
  }
}

function reset() {
  file.value = null
  uploadId.value = null
  datasetId.value = null
  revision.value = null
  preview.value = null
  grainCandidates.value = []
  chosenKey.value = null
  grainConfirmed.value = false
  error.value = null
  notice.value = null
  step.value = 'pick'
}
</script>

<template>
  <section>
    <h1>Upload → parse → confirm grain</h1>

    <div class="card" v-if="step === 'pick' || step === 'uploading'">
      <p class="muted">Step 1 — choose a CSV/XLSX ticket file. It is uploaded to quarantine, scanned, then parsed under resource limits. Raw bytes are retained per policy. Try <code>fixtures/support-tickets/data/tenant_alpha/tickets_cases.csv</code>.</p>
      <input type="file" accept=".csv,.xlsx" @change="onPick" />
      <div class="row" style="margin-top:0.6rem">
        <button :disabled="!file || busy" @click="start">
          {{ busy && step === 'uploading' ? 'Uploading…' : 'Upload & parse' }}
        </button>
        <span v-if="notice" class="muted">{{ notice }}</span>
      </div>
    </div>

    <div v-if="error" class="card"><span class="badge err">{{ error }}</span></div>

    <div v-if="preview" class="card">
      <h2>Parse preview <span class="badge ok">{{ preview.detected.encoding }} · {{ preview.detected.delimiter === '\t' ? 'TAB' : preview.detected.delimiter }}</span></h2>
      <p class="muted">Header row {{ preview.detected.header_row }} · {{ preview.row_count }} rows · dialect confidence: {{ preview.detected.dialect_confidence }} · dataset <code>{{ datasetId?.slice(0, 8) }}</code> revision {{ revision }} ({{ 'validated' }})</p>
      <table>
        <thead><tr><th>Column</th><th>Type</th><th>Null rate</th><th>Sample</th></tr></thead>
        <tbody>
          <tr v-for="c in preview.columns" :key="c.name">
            <td>{{ c.name }}</td><td>{{ c.inferred_type }}</td>
            <td>{{ (c.null_rate * 100).toFixed(1) }}%</td>
            <td class="muted">{{ c.sample.join(', ') }}</td>
          </tr>
        </tbody>
      </table>
      <p v-if="preview.rejected_rows.length" class="muted">
        Rejected rows: {{ preview.rejected_rows.length }} —
        <span v-for="r in preview.rejected_rows.slice(0, 3)" :key="r.line">line {{ r.line }} ({{ r.reason }}) </span>
      </p>
      <ul v-if="preview.issues.length"><li v-for="i in preview.issues" :key="i" class="muted">{{ i }}</li></ul>
      <div class="row">
        <button :disabled="busy" @click="loadGrain">Continue to grain confirmation →</button>
        <button class="secondary" @click="reset">Start over</button>
      </div>
    </div>

    <div v-if="step === 'grain'" class="card">
      <h2>Confirm the business grain</h2>
      <p class="muted">Uniqueness is checked over the <em>complete</em> candidate dataset, then you confirm business meaning. A unique row id is not a grain proof.</p>
      <table>
        <thead><tr><th></th><th>Candidate key</th><th>Unique (full data)</th><th>Null components</th><th>Duplicates</th></tr></thead>
        <tbody>
          <tr v-for="(g, i) in grainCandidates" :key="i">
            <td><input type="radio" name="grain" :value="i" v-model="chosenKey" :disabled="!g.unique_over_full_data" /></td>
            <td><code>{{ g.key_columns.join(' + ') }}</code></td>
            <td><span :class="['badge', g.unique_over_full_data ? 'ok' : 'err']">{{ g.unique_over_full_data ? 'yes' : 'no' }}</span></td>
            <td>{{ g.null_components }}</td>
            <td class="muted">{{ g.duplicate_examples.length || '—' }}</td>
          </tr>
        </tbody>
      </table>
      <div class="row" style="margin-top:0.6rem">
        <button :disabled="chosenKey === null || busy || grainConfirmed" @click="confirmGrain">Confirm grain</button>
        <NuxtLink class="btn" to="/datasets" v-if="grainConfirmed">Go publish →</NuxtLink>
      </div>
      <p v-if="grainConfirmed" class="badge ok" style="margin-top:0.6rem">Grain confirmed — dataset revision is publishable. Proceed to <NuxtLink to="/datasets">Datasets</NuxtLink> to publish, then <NuxtLink to="/metrics">Metrics</NuxtLink> to approve a definition.</p>
    </div>

    <div class="card">
      <h2>Upload history</h2>
      <div v-if="!history.length" class="muted">No uploads yet.</div>
      <table v-else>
        <thead><tr><th>File</th><th>Status</th><th>Dataset</th><th>Created</th></tr></thead>
        <tbody>
          <tr v-for="u in history" :key="u.id">
            <td>{{ u.filename }}</td>
            <td><span :class="['badge', u.status === 'parsed' || u.status === 'scanned' ? 'ok' : u.status === 'rejected' ? 'err' : 'warn']">{{ u.status }}</span></td>
            <td class="muted">{{ u.dataset_id ? u.dataset_id.slice(0, 8) : '—' }}</td>
            <td class="muted">{{ new Date(u.created_at).toLocaleString() }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>
