<template>
  <div class="page">
    <div class="header-row">
      <div>
        <h1>{{ t('investigations.title', locale) }}</h1>
        <p class="muted">{{ t('investigations.description', locale) }}</p>
      </div>
      <button class="btn btn-primary" @click="showNewModal = true">
        {{ t('investigations.newInvestigation', locale) }}
      </button>
    </div>

    <!-- Filter Bar -->
    <div class="filter-bar card">
      <div class="row">
        <label class="field">
          <span>{{ t('common.status', locale) }}</span>
          <select v-model="statusFilter" @change="loadInvestigations">
            <option value="">All Statuses</option>
            <option value="open">Open</option>
            <option value="in_progress">In Progress</option>
            <option value="resolved">Resolved</option>
            <option value="closed">Closed</option>
          </select>
        </label>
        <label class="field">
          <span>{{ t('investigations.sourceType', locale) }}</span>
          <select v-model="sourceFilter" @change="loadInvestigations">
            <option value="">All Sources</option>
            <option value="monitoring_episode">Monitoring Episode</option>
            <option value="workflow_bottleneck">Workflow Bottleneck</option>
            <option value="ad_hoc">Ad Hoc</option>
          </select>
        </label>
      </div>
    </div>

    <!-- Loading / Error / Empty States -->
    <div v-if="loading" class="loading">{{ t('common.loading', locale) }}</div>
    <div v-else-if="error" class="error-banner">{{ error }}</div>
    <div v-else-if="investigations.length === 0" class="empty-state card text-center" style="padding: 3rem 1.5rem; text-align: center;">
      <div style="font-size: 2.5rem; margin-bottom: 0.75rem;">🔍</div>
      <h3 style="margin-bottom: 0.5rem;">{{ locale === 'ar' ? 'لا توجد تحقيقات حالية' : 'No Operational Investigations Found' }}</h3>
      <p class="muted" style="max-width: 500px; margin: 0 auto 1.5rem auto;">
        {{ locale === 'ar' ? 'ابدأ تحقيقاً جديداً لفحص الانحرافات التشغيلية، وصياغة الفرضيات، وربط الأدلة المقارنة.' : 'Launch an investigation to diagnose operational bottlenecks, formulate root-cause hypotheses, and capture reproducible evidence.' }}
      </p>
      <button class="btn btn-primary" @click="showNewModal = true">
        {{ t('investigations.newInvestigation', locale) }}
      </button>
    </div>
    <div v-else class="grid">
      <div v-for="inv in investigations" :key="inv.id" class="card inv-card" @click="navigateTo(`/investigations/${inv.id}`)">
        <div class="card-header">
          <div>
            <h3>{{ inv.title }}</h3>
            <p class="question">{{ inv.question }}</p>
          </div>
          <span :class="'badge badge-' + statusBadge(inv.status)">{{ inv.status }}</span>
        </div>
        <div class="card-body row">
          <span class="muted">Source:</span> <code>{{ inv.source_type }}</code>
          <span class="muted">Owner:</span> <strong>{{ inv.owner }}</strong>
          <span class="muted">Claims:</span> <span>{{ inv.claims?.length ?? 0 }}</span>
          <span class="muted">Evidence:</span> <span>{{ inv.evidence?.length ?? 0 }}</span>
          <span class="spacer" />
          <span class="muted">{{ formatDate(inv.updated_at) }}</span>
        </div>
      </div>
    </div>

    <!-- Create Modal -->
    <div v-if="showNewModal" class="modal-backdrop" @click.self="showNewModal = false">
      <div class="modal card">
        <h2>{{ t('investigations.createTitle', locale) }}</h2>
        <form @submit.prevent="createInvestigation">
          <label class="field">
            <span>Title</span>
            <input v-model="newForm.title" required placeholder="e.g. Surgical Discharge Delay" />
          </label>
          <label class="field">
            <span>{{ t('investigations.question', locale) }}</span>
            <textarea v-model="newForm.question" required rows="3" placeholder="What is causing the backlog?" />
          </label>
          <label class="field">
            <span>{{ t('investigations.sourceType', locale) }}</span>
            <select v-model="newForm.source_type">
              <option value="ad_hoc">Ad Hoc</option>
              <option value="monitoring_episode">Monitoring Episode</option>
              <option value="workflow_bottleneck">Workflow Bottleneck</option>
            </select>
          </label>
          <div class="modal-actions">
            <button type="button" class="btn secondary" @click="showNewModal = false">{{ t('common.cancel', locale) }}</button>
            <button type="submit" class="btn btn-primary">{{ t('common.create', locale) }}</button>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useLocale, t } from '~/composables/locale'
import type { Investigation } from '~/shared/types'

const { locale } = useLocale()
const { get, post } = useApi()

const investigations = ref<Investigation[]>([])
const loading = ref(true)
const error = ref('')

const statusFilter = ref('')
const sourceFilter = ref('')

const showNewModal = ref(false)
const newForm = ref({
  title: '',
  question: '',
  source_type: 'ad_hoc',
  alternative_explanations: [],
})

function statusBadge(status: string): string {
  return ({ open: 'yellow', in_progress: 'blue', resolved: 'green', closed: 'gray' } as Record<string, string>)[status] || 'gray'
}

function formatDate(iso: string): string {
  if (!iso) return '—'
  try { return new Date(iso).toLocaleDateString() } catch { return iso }
}

async function loadInvestigations() {
  loading.value = true
  error.value = ''
  try {
    let query = '/investigations'
    const params = new URLSearchParams()
    if (statusFilter.value) params.append('status', statusFilter.value)
    if (sourceFilter.value) params.append('source_type', sourceFilter.value)
    if (params.toString()) query += '?' + params.toString()

    const res = await get<Investigation[]>(query)
    investigations.value = Array.isArray(res) ? res : []
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : 'Failed to load investigations'
  } finally {
    loading.value = false
  }
}

async function createInvestigation() {
  try {
    const created = await post<Investigation>('/investigations', newForm.value)
    showNewModal.value = false
    newForm.value = { title: '', question: '', source_type: 'ad_hoc', alternative_explanations: [] }
    navigateTo(`/investigations/${created.id}`)
  } catch (e: unknown) {
    alert(e instanceof Error ? e.message : 'Create failed')
  }
}

onMounted(() => {
  loadInvestigations()
})
</script>

<style scoped>
.page { max-width: 1100px; margin: 0 auto; padding: 1rem; }
.header-row { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 1rem; }
.inv-card { cursor: pointer; transition: border-color 0.15s; }
.inv-card:hover { border-color: #0f766e; }
.card-header { display: flex; justify-content: space-between; align-items: flex-start; }
.card-header h3 { margin: 0 0 0.2rem 0; font-size: 1.1rem; }
.question { margin: 0; color: #475569; font-size: 0.9rem; }
.badge-green { background: #dcfce7; color: #166534; }
.badge-yellow { background: #fef9c3; color: #854d0e; }
.badge-blue { background: #dbeafe; color: #1e40af; }
.badge-gray { background: #f1f5f9; color: #475569; }
.modal-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; z-index: 100; }
.modal { background: #fff; width: 100%; max-width: 500px; padding: 1.5rem; border-radius: 8px; }
.modal-actions { display: flex; justify-content: flex-end; gap: 0.5rem; margin-top: 1rem; }
.error-banner { background: #fee2e2; color: #991b1b; padding: 0.75rem; border-radius: 6px; }
</style>
