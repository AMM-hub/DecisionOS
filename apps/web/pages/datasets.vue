<script setup lang="ts">
import type { Dataset, GrainCandidate, PublishResponse } from '~/shared/types'

const { get, post } = useApi()

const datasets = ref<Dataset[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
const openGrain = ref<string | null>(null)
const candidates = ref<Record<string, GrainCandidate[]>>({})
const chosen = ref<Record<string, number | null>>({})
const busyId = ref<string | null>(null)

async function load() {
  loading.value = true
  error.value = null
  try { datasets.value = await get<Dataset[]>('/datasets') }
  catch (e) { error.value = e instanceof Error ? e.message : String(e) }
  finally { loading.value = false }
}
onMounted(load)

async function toggleGrain(d: Dataset) {
  if (openGrain.value === d.dataset_id) { openGrain.value = null; return }
  openGrain.value = d.dataset_id
  if (!candidates.value[d.dataset_id]) {
    try { candidates.value[d.dataset_id] = await get<GrainCandidate[]>(`/datasets/${d.dataset_id}/grain-candidates`) }
    catch (e) { error.value = e instanceof Error ? e.message : String(e) }
  }
}

async function confirmGrain(d: Dataset) {
  const pick = chosen.value[d.dataset_id]
  if (pick == null) return
  busyId.value = d.dataset_id
  error.value = null
  try {
    await post(`/datasets/${d.dataset_id}/grain-confirmation`, {
      key_columns: candidates.value[d.dataset_id][pick].key_columns
    })
    await load()
    openGrain.value = null
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally { busyId.value = null }
}

async function publish(d: Dataset) {
  if (d.latest_revision == null) return
  busyId.value = d.dataset_id
  error.value = null
  try {
    await post<PublishResponse>(`/datasets/${d.dataset_id}/revisions/${d.latest_revision}/publish`)
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally { busyId.value = null }
}

function stateBadge(s: Dataset['latest_revision_state']) {
  return s === 'published' ? 'ok' : s === 'validated' ? 'warn' : s === 'failed' || s === 'validating' ? 'err' : 'warn'
}
</script>

<template>
  <section>
    <div class="row" style="justify-content: space-between">
      <h1>Datasets</h1>
      <button class="secondary" :disabled="loading" @click="load">{{ loading ? 'Loading…' : 'Refresh' }}</button>
    </div>
    <p class="muted">Confirm the business grain over the full dataset, then publish an immutable revision. Publishing is refused until the grain is confirmed (§9.2).</p>

    <div v-if="error" class="card"><span class="badge err">{{ error }}</span></div>
    <div v-if="!datasets.length && !loading" class="card muted">No datasets yet. <NuxtLink to="/uploads">Upload and parse a file</NuxtLink> first.</div>

    <div v-for="d in datasets" :key="d.dataset_id" class="card">
      <div class="row" style="justify-content: space-between">
        <h2 style="margin:0">{{ d.name }}
          <span :class="['badge', d.grain_confirmed ? 'ok' : 'warn']">{{ d.grain_confirmed ? 'grain confirmed' : 'grain unconfirmed' }}</span>
          <span :class="['badge', stateBadge(d.latest_revision_state)]">rev {{ d.latest_revision }} · {{ d.latest_revision_state }}</span>
          <span v-if="d.revision != null" class="badge ok">published rev {{ d.revision }}</span>
        </h2>
      </div>
      <p class="muted">
        <code>{{ d.dataset_id.slice(0, 8) }}</code>
        · {{ d.row_count ?? '—' }} rows (published)
        <template v-if="d.grain"> · grain: <code>{{ d.grain.join(' + ') }}</code></template>
      </p>

      <div class="row">
        <button class="secondary" :disabled="d.grain_confirmed" @click="toggleGrain(d)">
          {{ d.grain_confirmed ? 'Grain locked' : (openGrain === d.dataset_id ? 'Hide candidates' : 'Confirm grain…') }}
        </button>
        <button v-if="d.latest_revision_state === 'validated' && d.grain_confirmed" :disabled="busyId === d.dataset_id" @click="publish(d)">
          Publish rev {{ d.latest_revision }}
        </button>
      </div>

      <div v-if="openGrain === d.dataset_id && candidates[d.dataset_id]" style="margin-top:0.6rem">
        <table>
          <thead><tr><th></th><th>Candidate key</th><th>Unique (full)</th><th>Nulls</th><th>Duplicates</th></tr></thead>
          <tbody>
            <tr v-for="(g, i) in candidates[d.dataset_id]" :key="i">
              <td><input type="radio" :name="`g-${d.dataset_id}`" :value="i" v-model="chosen[d.dataset_id]" :disabled="!g.unique_over_full_data" /></td>
              <td><code>{{ g.key_columns.join(' + ') }}</code></td>
              <td><span :class="['badge', g.unique_over_full_data ? 'ok' : 'err']">{{ g.unique_over_full_data ? 'yes' : 'no' }}</span></td>
              <td>{{ g.null_components }}</td>
              <td class="muted">{{ g.duplicate_examples.length || '—' }}</td>
            </tr>
          </tbody>
        </table>
        <button :disabled="chosen[d.dataset_id] == null || busyId === d.dataset_id" @click="confirmGrain(d)" style="margin-top:0.5rem">Confirm grain</button>
      </div>
    </div>
  </section>
</template>
