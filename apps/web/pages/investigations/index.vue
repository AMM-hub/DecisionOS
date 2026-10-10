<template>
  <div class="investigations-page">
    <div class="page-head" style="margin-bottom: 16px; display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; flex-wrap: wrap;">
      <div>
        <div class="eyebrow" style="font-family: var(--font-mono); font-size: 11px; color: var(--faint); text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 2px;">Diagnostics &amp; Root Cause</div>
        <h1 style="font-size: 20px; font-weight: 700; color: var(--fg-strong); margin: 0;">{{ t('investigations.title', locale) }}</h1>
        <p class="muted" style="font-size: 13px; margin-top: 2px;">{{ t('investigations.description', locale) }}</p>
      </div>
      <button class="btn btn-primary btn-sm" @click="showNewModal = true">
        <svg><use href="#i-flask"/></svg>
        <span>{{ t('investigations.newInvestigation', locale) }}</span>
      </button>
    </div>

    <!-- Filter Bar -->
    <div class="panel" style="margin-bottom: 14px;">
      <div class="panel-body" style="padding: 10px 14px; display: flex; gap: 16px; align-items: center; flex-wrap: wrap;">
        <label class="field" style="margin: 0; flex-direction: row; align-items: center; gap: 8px;">
          <span class="muted" style="font-size: 12px; font-weight: 550;">{{ t('common.status', locale) }}:</span>
          <select v-model="statusFilter" @change="loadInvestigations" style="font-size: 12.5px; height: 30px; padding: 2px 8px;">
            <option value="">All Statuses</option>
            <option value="open">Open</option>
            <option value="in_progress">In Progress</option>
            <option value="resolved">Resolved</option>
            <option value="closed">Closed</option>
          </select>
        </label>
        <label class="field" style="margin: 0; flex-direction: row; align-items: center; gap: 8px;">
          <span class="muted" style="font-size: 12px; font-weight: 550;">{{ t('investigations.sourceType', locale) }}:</span>
          <select v-model="sourceFilter" @change="loadInvestigations" style="font-size: 12.5px; height: 30px; padding: 2px 8px;">
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
    <div v-else-if="investigations.length === 0" class="panel text-center" style="padding: 3rem 1.5rem; text-align: center;">
      <div style="font-size: 2.2rem; margin-bottom: 0.75rem;">🔍</div>
      <h3 style="margin-bottom: 0.5rem; font-size: 15px; font-weight: 650; color: var(--fg-strong);">
        {{ locale === 'ar' ? 'لا توجد تحقيقات حالية' : 'No Operational Investigations Found' }}
      </h3>
      <p class="muted" style="max-width: 500px; margin: 0 auto 1.5rem auto; font-size: 13px;">
        {{ locale === 'ar' ? 'ابدأ تحقيقاً جديداً لفحص الانحرافات التشغيلية، وصياغة الفرضيات، وربط الأدلة المقارنة.' : 'Launch an investigation to diagnose operational bottlenecks, formulate root-cause hypotheses, and capture reproducible evidence.' }}
      </p>
      <button class="btn btn-primary btn-sm" @click="showNewModal = true">
        {{ t('investigations.newInvestigation', locale) }}
      </button>
    </div>
    
    <!-- Enterprise Table of Investigations -->
    <div v-else class="panel table-scroll">
      <div class="panel-head">
        <h3 style="font-size: 13.5px; margin: 0;">Operational Investigations Queue</h3>
        <span class="faint mono isolate" style="font-size: 11.5px;">{{ investigations.length }} active tracks</span>
      </div>
      <table class="dt">
        <thead>
          <tr>
            <th style="width: 130px;">ID</th>
            <th>Title &amp; Question</th>
            <th style="width: 140px;">Source</th>
            <th style="width: 120px;">Owner</th>
            <th class="num" style="width: 80px;">Claims</th>
            <th class="num" style="width: 80px;">Evidence</th>
            <th style="width: 110px;">Status</th>
            <th style="width: 120px;">Updated</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="inv in investigations" :key="inv.id" @click="navigateTo(`/investigations/${inv.id}`)">
            <td>
              <code class="id isolate">{{ inv.id }}</code>
            </td>
            <td>
              <div style="font-weight: 600; color: var(--fg-strong);">{{ inv.title }}</div>
              <div class="muted" style="font-size: 11.5px; margin-top: 2px;">{{ inv.question }}</div>
            </td>
            <td>
              <code class="isolate" style="font-size: 11px;">{{ inv.source_type }}</code>
            </td>
            <td class="isolate" style="font-size: 12px; color: var(--fg);">{{ inv.owner }}</td>
            <td class="num isolate">{{ inv.claims?.length ?? 0 }}</td>
            <td class="num isolate">{{ inv.evidence?.length ?? 0 }}</td>
            <td>
              <span class="status-cell" :data-tone="statusBadgeTone(inv.status)">
                <span class="status-dot"></span>
                <span style="font-family: var(--font-mono); font-size: 11px; text-transform: uppercase;">{{ inv.status }}</span>
              </span>
            </td>
            <td class="faint isolate" style="font-size: 11.5px;">{{ formatDate(inv.updated_at) }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Create Modal -->
    <div v-if="showNewModal" class="modal-backdrop" @click.self="showNewModal = false">
      <div class="modal">
        <h2 style="font-size: 16px; font-weight: 650; margin-bottom: 14px; color: var(--fg-strong);">{{ t('investigations.createTitle', locale) }}</h2>
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
          <div style="display: flex; justify-content: flex-end; gap: 8px; margin-top: 18px;">
            <button type="button" class="btn btn-secondary btn-sm" @click="showNewModal = false">{{ t('common.cancel', locale) }}</button>
            <button type="submit" class="btn btn-primary btn-sm">{{ t('common.create', locale) }}</button>
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

function statusBadgeTone(status: string): string {
  switch (status) {
    case 'resolved': return 'ok'
    case 'in_progress': return 'accent'
    case 'open': return 'warn'
    default: return 'muted'
  }
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
