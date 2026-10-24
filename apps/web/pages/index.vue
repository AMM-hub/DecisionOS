<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useApi } from '~/composables/api'
import { useLocale } from '~/composables/locale'
import { formatDateTime, formatRelative } from '~/composables/format'
import PageHeader from '~/components/PageHeader.vue'
import DcCard from '~/components/DcCard.vue'
import type {
  Dataset, DecisionRecord, MetricDefinition, MonitoringAlertEpisode,
  MonitoringEpisodeListResponse, OutboxEvent, UploadListItem
} from '~/shared/types'

const { get } = useApi()
const { locale } = useLocale()

const datasets = ref<Dataset[]>([])
const definitions = ref<MetricDefinition[]>([])
const uploads = ref<UploadListItem[]>([])
const events = ref<OutboxEvent[]>([])
const decisions = ref<DecisionRecord[]>([])
const episodes = ref<MonitoringAlertEpisode[]>([])
const loading = ref(false)
const error = ref<string | null>(null)

const published = computed(() => datasets.value.filter(d => d.revision != null).length)
const grainConfirmed = computed(() => datasets.value.filter(d => d.grain_confirmed).length)
const approved = computed(() => definitions.value.filter(d => d.status === 'approved'))
const openDecisions = computed(() => decisions.value.filter(d => !['closed', 'rejected', 'abandoned'].includes(d.status)))
const openAlerts = computed(() => episodes.value.filter(e => !['closed', 'resolved', 'dismissed'].includes(e.workflow_status)))
const recentEvents = computed(() => events.value.slice(-6).reverse())
const hasData = computed(() => datasets.value.length > 0 || definitions.value.length > 0)

const nextActions = computed(() => [
  { id: 'upload', text: 'Upload ticket data', to: '/uploads', done: uploads.value.length > 0 },
  { id: 'dataset', text: 'Confirm grain and publish', to: '/datasets', done: published.value > 0 },
  { id: 'metric', text: 'Propose and approve a metric', to: '/metrics', done: approved.value.length > 0 },
  { id: 'decision', text: 'Record and review a decision', to: '/decisions', done: decisions.value.length > 0 },
])

async function load() {
  loading.value = true
  error.value = null
  try {
    const [d, m, u, e, dec, eps] = await Promise.all([
      get<Dataset[]>('/datasets'),
      get<MetricDefinition[]>('/metrics/definitions'),
      get<UploadListItem[]>('/uploads'),
      get<OutboxEvent[]>('/jobs/outbox'),
      get<DecisionRecord[]>('/decisions').catch(() => []),
      get<MonitoringEpisodeListResponse | MonitoringAlertEpisode[]>('/monitoring/episodes')
        .catch(() => ({ episodes: [] }))
    ])
    datasets.value = d
    definitions.value = m
    uploads.value = u
    events.value = e
    decisions.value = Array.isArray(dec) ? dec : []
    episodes.value = Array.isArray(eps) ? eps : (eps?.episodes ?? [])
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
    <PageHeader
      title="Operational overview"
      subtitle="Ask, investigate, monitor, predict, compare, and decide — on approved definitions with reproducible evidence."
    >
      <template #actions>
        <button class="secondary" :disabled="loading" @click="load">{{ loading ? 'Refreshing…' : 'Refresh' }}</button>
      </template>
    </PageHeader>

    <DcCard v-if="error">
      <span class="badge err">{{ error }}</span>
    </DcCard>

    <div class="kpi-band">
      <div class="kpi" data-tone="accent">
        <div class="k-label"><span class="mark" />Datasets</div>
        <div class="k-val">{{ datasets.length }}</div>
        <div class="k-foot">{{ published }} published · {{ grainConfirmed }} grain-confirmed</div>
      </div>
      <div class="kpi" data-tone="ok">
        <div class="k-label"><span class="mark" />Certified metrics</div>
        <div class="k-val">{{ approved.length }}</div>
        <div class="k-foot">of {{ definitions.length }} definitions</div>
      </div>
      <div class="kpi" data-tone="warn">
        <div class="k-label"><span class="mark" />Open decisions</div>
        <div class="k-val">{{ openDecisions.length }}</div>
        <div class="k-foot">{{ decisions.length }} total</div>
      </div>
      <div class="kpi" data-tone="crit">
        <div class="k-label"><span class="mark" />Open alerts</div>
        <div class="k-val">{{ openAlerts.length }}</div>
        <div class="k-foot">{{ episodes.length }} episodes</div>
      </div>
    </div>

    <DcCard v-if="loading">
      <div v-for="row in 3" :key="row" class="skeleton" />
    </DcCard>

    <DcCard v-else-if="!hasData">
      <div class="empty">
        <div class="e-ico">
          <svg><use href="#i-upload" /></svg>
        </div>
        <h3>No data yet</h3>
        <p class="muted">Upload a ticket file to quarantine, confirm its grain, and publish your first dataset revision.</p>
        <NuxtLink to="/uploads" class="btn btn-primary">Upload ticket data</NuxtLink>
      </div>
    </DcCard>

    <div v-else class="grid cols-2">
      <DcCard title="Next actions">
        <div class="next-actions">
          <div
            v-for="step in nextActions"
            :key="step.id"
            class="status-cell"
            :data-tone="step.done ? 'ok' : 'muted'"
          >
            <span class="status-dot" />
            <NuxtLink :to="step.to">{{ step.text }}</NuxtLink>
          </div>
        </div>
      </DcCard>

      <DcCard title="Recent activity">
        <div v-if="!recentEvents.length" class="muted">No events yet — publish a dataset revision to emit one.</div>
        <table v-else>
          <thead><tr><th>Event</th><th>Aggregate</th><th>Occurred</th></tr></thead>
          <tbody>
            <tr v-for="e in recentEvents" :key="e.event_id">
              <td><code>{{ e.event_type }}</code></td>
              <td class="muted">{{ e.aggregate_id.slice(0, 8) }} @{{ e.aggregate_version }}</td>
              <td>
                <div class="cell-stack">
                  <span>{{ formatDateTime(e.occurred_at, locale) }}</span>
                  <span class="muted">{{ formatRelative(e.occurred_at, locale) }}</span>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </DcCard>
    </div>
  </section>
</template>

<style scoped>
.skeleton {
  height: 14px;
  border-radius: var(--r-sm);
  background: var(--surface-2);
  margin-bottom: 10px;
}
.skeleton:nth-child(2) { width: 82%; }
.skeleton:nth-child(3) { width: 64%; margin-bottom: 0; }
.empty { padding: 28px 16px; }
.next-actions { display: flex; flex-direction: column; gap: 11px; }
.next-actions .status-cell[data-tone="muted"] { color: var(--muted); }
.next-actions .status-cell[data-tone="muted"] .status-dot { background: var(--faint); }
.next-actions a { font-weight: 550; }
.next-actions a:hover { color: var(--accent-ink); }
</style>
