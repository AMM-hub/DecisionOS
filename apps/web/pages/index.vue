<script setup lang="ts">
import type { Dataset, MetricDefinition, OutboxEvent, UploadListItem } from '~/shared/types'

const { get } = useApi()

const datasets = ref<Dataset[]>([])
const definitions = ref<MetricDefinition[]>([])
const uploads = ref<UploadListItem[]>([])
const events = ref<OutboxEvent[]>([])
const loading = ref(false)
const error = ref<string | null>(null)

const published = computed(() => datasets.value.filter(d => d.revision != null).length)
const grainConfirmed = computed(() => datasets.value.filter(d => d.grain_confirmed).length)
const approved = computed(() => definitions.value.filter(d => d.status === 'approved'))
const lastUpload = computed(() => uploads.value[0]?.created_at ?? null)
const recentEvents = computed(() => events.value.slice(-6).reverse())

function fmt(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString()
}

async function load() {
  loading.value = true
  error.value = null
  try {
    const [d, m, u, e] = await Promise.all([
      get<Dataset[]>('/datasets'),
      get<MetricDefinition[]>('/metrics/definitions'),
      get<UploadListItem[]>('/uploads'),
      get<OutboxEvent[]>('/jobs/outbox')
    ])
    datasets.value = d
    definitions.value = m
    uploads.value = u
    events.value = e
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
  } finally {
    loading.value = false
  }
}
onMounted(load)
</script>

<template>
  <section>
    <div class="row" style="justify-content: space-between">
      <h1>Operational overview</h1>
      <button class="secondary" :disabled="loading" @click="load">{{ loading ? 'Refreshing…' : 'Refresh' }}</button>
    </div>
    <p class="muted">Ask, investigate, monitor, predict, compare, and decide — on approved definitions with reproducible evidence.</p>

    <div v-if="error" class="card"><span class="badge err">{{ error }}</span></div>

    <div class="grid cols-3">
      <div class="card stat">
        <div class="n">{{ datasets.length }}</div>
        <div class="muted">datasets · {{ published }} published · {{ grainConfirmed }} grain-confirmed</div>
      </div>
      <div class="card stat">
        <div class="n">{{ approved.length }}</div>
        <div class="muted">certified metrics (of {{ definitions.length }} definitions)</div>
      </div>
      <div class="card stat">
        <div class="n" style="font-size:1.1rem">{{ fmt(lastUpload) }}</div>
        <div class="muted">last upload · {{ uploads.length }} total</div>
      </div>
    </div>

    <div class="card">
      <h2>Getting started</h2>
      <ol class="muted">
        <li><NuxtLink to="/uploads">Upload</NuxtLink> a ticket CSV → quarantine → safe parse → grain candidates.</li>
        <li><NuxtLink to="/datasets">Confirm the grain</NuxtLink> over the full dataset, then publish a revision.</li>
        <li><NuxtLink to="/metrics">Propose a metric</NuxtLink> as the modeler, approve as the manager, then query it.</li>
      </ol>
      <p class="muted">Switch the <em>acting user</em> in the header to see separation-of-duties enforced (self-approval is refused).</p>
    </div>

    <div class="card">
      <h2>Recent activity <span class="muted">(outbox)</span></h2>
      <div v-if="!recentEvents.length" class="muted">No events yet — publish a dataset revision to emit one.</div>
      <table v-else>
        <thead><tr><th>Event</th><th>Aggregate</th><th>Occurred</th></tr></thead>
        <tbody>
          <tr v-for="e in recentEvents" :key="e.event_id">
            <td><code>{{ e.event_type }}</code></td>
            <td class="muted">{{ e.aggregate_id.slice(0, 8) }} @{{ e.aggregate_version }}</td>
            <td class="muted">{{ fmt(e.occurred_at) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>
