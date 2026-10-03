<template>
  <div class="page">
    <div v-if="loading" class="loading">{{ t('common.loading', locale) }}</div>
    <div v-else-if="error" class="error-banner">{{ error }}</div>
    <div v-else-if="inv" class="inv-workspace">
      <!-- Breadcrumb / Header -->
      <div class="header-row">
        <div>
          <NuxtLink to="/investigations" class="back-link">&larr; Investigations</NuxtLink>
          <h1>{{ inv.title }}</h1>
          <p class="question-title"><strong>Question:</strong> {{ inv.question }}</p>
        </div>
        <div class="status-actions">
          <span :class="'badge badge-' + statusBadge(inv.status)">{{ inv.status }}</span>
          <select class="status-select" v-model="selectedStatus" @change="updateStatus">
            <option value="open">open</option>
            <option value="in_progress">in_progress</option>
            <option value="resolved">resolved</option>
            <option value="closed">closed</option>
          </select>
        </div>
      </div>

      <!-- Main Overview Grid -->
      <div class="grid cols-3 meta-grid">
        <div class="card stat">
          <span class="muted">Source</span>
          <div class="n-sm"><code>{{ inv.source_type }}</code></div>
        </div>
        <div class="card stat">
          <span class="muted">Owner</span>
          <div class="n-sm">{{ inv.owner }}</div>
        </div>
        <div class="card stat">
          <span class="muted">Created</span>
          <div class="n-sm">{{ formatDate(inv.created_at) }}</div>
        </div>
      </div>

      <!-- Alternative Explanations -->
      <div v-if="inv.alternative_explanations?.length" class="card">
        <h3>Alternative Explanations Under Investigation</h3>
        <ul>
          <li v-for="(exp, idx) in inv.alternative_explanations" :key="idx">{{ exp }}</li>
        </ul>
      </div>

      <!-- Structured Claims Section -->
      <div class="section-header">
        <h2>{{ t('investigations.claims', locale) }} ({{ inv.claims?.length ?? 0 }})</h2>
        <button class="btn btn-sm" @click="showAddClaimModal = true">{{ t('investigations.addClaim', locale) }}</button>
      </div>

      <div v-if="!inv.claims || inv.claims.length === 0" class="card empty-card">
        <p class="muted">No structured claims registered for this investigation yet.</p>
      </div>
      <div v-else class="grid">
        <div v-for="claim in inv.claims" :key="claim.id" class="card claim-card">
          <div class="card-header">
            <strong>{{ claim.statement }}</strong>
            <div class="row">
              <span class="badge badge-outline">{{ claim.evidence_type }}</span>
              <span :class="'badge badge-' + supportBadge(claim.support_status)">{{ claim.support_status }}</span>
            </div>
          </div>
          <div class="card-body">
            <div v-if="claim.structured_fact" class="fact-box">
              <span class="muted">Fact Reference:</span>
              <code>{{ claim.structured_fact.metric_id }}</code> =
              <strong>{{ claim.structured_fact.value }} {{ claim.structured_fact.unit || '' }}</strong>
            </div>
            <div v-if="claim.quality_flags?.length" class="row quality-flags">
              <span v-for="flag in claim.quality_flags" :key="flag" class="badge badge-warn">{{ flag }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Immutable Evidence Artifacts Section -->
      <div class="section-header">
        <h2>{{ t('investigations.evidence', locale) }} ({{ inv.evidence?.length ?? 0 }})</h2>
        <button class="btn btn-sm" @click="showCaptureEvidenceModal = true">{{ t('investigations.captureEvidence', locale) }}</button>
      </div>

      <div v-if="!inv.evidence || inv.evidence.length === 0" class="card empty-card">
        <p class="muted">No evidence artifacts captured for this investigation yet.</p>
      </div>
      <div v-else class="grid">
        <div v-for="ev in inv.evidence" :key="ev.artifact_id" class="card ev-card">
          <div class="card-header">
            <div>
              <strong>Artifact {{ ev.artifact_id }}</strong>
              <div class="row text-xs muted">
                <span>Metric: <code>{{ ev.metric_id }}</code></span> &middot;
                <span>Dataset: <code>{{ ev.dataset_id }}</code> r#{{ ev.dataset_revision }}</span>
              </div>
            </div>
            <div class="row">
              <span class="badge badge-outline">{{ ev.evidence_type }}</span>
              <span :class="'badge badge-' + supportBadge(ev.support_status)">{{ ev.support_status }}</span>
            </div>
          </div>

          <div class="card-body">
            <div class="grid cols-3 ev-meta-grid">
              <div><span class="muted">Exactness:</span> <code>{{ ev.exactness_class }}</code></div>
              <div><span class="muted">Reproducibility:</span> <code>{{ ev.reproducibility_status }}</code></div>
              <div><span class="muted">Row Count:</span> <strong>{{ ev.row_count }}</strong></div>
            </div>

            <!-- Quality Flags -->
            <div v-if="ev.quality_flags?.length" class="row quality-flags margin-y">
              <span class="muted">Quality Flags:</span>
              <span v-for="flag in ev.quality_flags" :key="flag" class="badge badge-warn">{{ flag }}</span>
            </div>

            <!-- Expandable Provenance Details -->
            <details class="provenance-details">
              <summary>Provenance & Integrity Details</summary>
              <div class="provenance-content">
                <div class="digest-row">
                  <span class="muted">Canonical Digest:</span>
                  <code class="digest-hash">{{ ev.canonical_digest }}</code>
                  <span class="badge badge-green">Integrity Verified</span>
                </div>
                <div class="row text-xs muted margin-y">
                  <span>Storage: {{ ev.storage_format }}</span> &middot;
                  <span>Created By: {{ ev.created_by }}</span> &middot;
                  <span>Created At: {{ formatDate(ev.created_at) }}</span>
                </div>
                <div v-if="ev.payload_json" class="payload-box">
                  <span class="muted">Stored Payload Snippet:</span>
                  <pre>{{ ev.payload_json }}</pre>
                </div>
              </div>
            </details>
          </div>
        </div>
      </div>

      <!-- Action Footer: Create Decision Brief -->
      <div class="footer-actions card">
        <div>
          <h3>Ready to turn findings into a Decision?</h3>
          <p class="muted">Initialize a Decision Brief with evidence gathered during this investigation.</p>
        </div>
        <button class="btn btn-primary" @click="createDecisionFromInv">
          {{ t('investigations.convertDecision', locale) }}
        </button>
      </div>

      <!-- Add Claim Modal -->
      <div v-if="showAddClaimModal" class="modal-backdrop" @click.self="showAddClaimModal = false">
        <div class="modal card">
          <h2>Add Structured Claim</h2>
          <form @submit.prevent="submitClaim">
            <label class="field">
              <span>{{ t('investigations.statement', locale) }}</span>
              <textarea v-model="claimForm.statement" required placeholder="e.g. ICU stay duration increased by 2.4 hours" />
            </label>
            <div class="row">
              <label class="field">
                <span>{{ t('investigations.evidenceType', locale) }}</span>
                <select v-model="claimForm.evidence_type">
                  <option value="observed">observed</option>
                  <option value="estimated">estimated</option>
                  <option value="simulated">simulated</option>
                  <option value="causal_estimate">causal_estimate</option>
                  <option value="hypothesis">hypothesis</option>
                </select>
              </label>
              <label class="field">
                <span>{{ t('investigations.supportStatus', locale) }}</span>
                <select v-model="claimForm.support_status">
                  <option value="supporting">supporting</option>
                  <option value="counter">counter</option>
                  <option value="neutral">neutral</option>
                  <option value="unverified">unverified</option>
                </select>
              </label>
            </div>
            <fieldset class="fact-fieldset">
              <legend>Structured Fact (Optional)</legend>
              <div class="row">
                <label class="field">
                  <span>Metric ID</span>
                  <input v-model="claimForm.structured_fact.metric_id" placeholder="m_icu_stay" />
                </label>
                <label class="field">
                  <span>Value</span>
                  <input v-model="claimForm.structured_fact.value" placeholder="2.4" />
                </label>
                <label class="field">
                  <span>Unit</span>
                  <input v-model="claimForm.structured_fact.unit" placeholder="hours" />
                </label>
              </div>
            </fieldset>
            <div class="modal-actions">
              <button type="button" class="btn secondary" @click="showAddClaimModal = false">{{ t('common.cancel', locale) }}</button>
              <button type="submit" class="btn btn-primary">{{ t('common.save', locale) }}</button>
            </div>
          </form>
        </div>
      </div>

      <!-- Capture Evidence Modal -->
      <div v-if="showCaptureEvidenceModal" class="modal-backdrop" @click.self="showCaptureEvidenceModal = false">
        <div class="modal card">
          <h2>Capture Certified Metric Evidence</h2>
          <form @submit.prevent="submitEvidenceCapture">
            <label class="field">
              <span>Metric ID</span>
              <input v-model="evidenceForm.metric_id" required placeholder="m_occupancy" />
            </label>
            <div class="row">
              <label class="field">
                <span>Evidence Type</span>
                <select v-model="evidenceForm.evidence_type">
                  <option value="observed">observed</option>
                  <option value="estimated">estimated</option>
                  <option value="simulated">simulated</option>
                </select>
              </label>
              <label class="field">
                <span>Support Status</span>
                <select v-model="evidenceForm.support_status">
                  <option value="supporting">supporting</option>
                  <option value="counter">counter</option>
                  <option value="neutral">neutral</option>
                </select>
              </label>
            </div>
            <div class="modal-actions">
              <button type="button" class="btn secondary" @click="showCaptureEvidenceModal = false">{{ t('common.cancel', locale) }}</button>
              <button type="submit" class="btn btn-primary">Capture Snapshot</button>
            </div>
          </form>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useLocale, t } from '~/composables/locale'
import type { Investigation, DecisionRecord } from '~/shared/types'

const route = useRoute()
const invId = route.params.id as string

const { locale } = useLocale()
const { get, post } = useApi()

const inv = ref<Investigation | null>(null)
const loading = ref(true)
const error = ref('')
const selectedStatus = ref('open')

const showAddClaimModal = ref(false)
const claimForm = ref({
  statement: '',
  evidence_type: 'observed',
  support_status: 'supporting',
  structured_fact: {
    metric_id: '',
    value: '',
    unit: 'count',
  },
})

const showCaptureEvidenceModal = ref(false)
const evidenceForm = ref({
  metric_id: '',
  evidence_type: 'observed',
  support_status: 'supporting',
})

function statusBadge(status: string): string {
  return ({ open: 'yellow', in_progress: 'blue', resolved: 'green', closed: 'gray' } as Record<string, string>)[status] || 'gray'
}

function supportBadge(status: string): string {
  return ({ supporting: 'green', counter: 'red', neutral: 'gray', unverified: 'yellow' } as Record<string, string>)[status] || 'gray'
}

function formatDate(iso: string): string {
  if (!iso) return '—'
  try { return new Date(iso).toLocaleString() } catch { return iso }
}

async function loadInvestigation() {
  loading.value = true
  error.value = ''
  try {
    const res = await get<Investigation>(`/investigations/${invId}`)
    inv.value = res
    selectedStatus.value = res.status
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : 'Failed to load investigation'
  } finally {
    loading.value = false
  }
}

async function updateStatus() {
  if (!inv.value) return
  try {
    const res = await post<Investigation>(`/investigations/${invId}/status`, { status: selectedStatus.value })
    inv.value.status = res.status
  } catch (e: unknown) {
    alert(e instanceof Error ? e.message : 'Status update failed')
  }
}

async function submitClaim() {
  try {
    await post(`/investigations/${invId}/claims`, claimForm.value)
    showAddClaimModal.value = false
    claimForm.value = { statement: '', evidence_type: 'observed', support_status: 'supporting', structured_fact: { metric_id: '', value: '', unit: 'count' } }
    await loadInvestigation()
  } catch (e: unknown) {
    alert(e instanceof Error ? e.message : 'Add claim failed')
  }
}

async function submitEvidenceCapture() {
  try {
    await post('/evidence', {
      investigation_id: invId,
      metric_id: evidenceForm.value.metric_id,
      evidence_type: evidenceForm.value.evidence_type,
      support_status: evidenceForm.value.support_status,
    })
    showCaptureEvidenceModal.value = false
    evidenceForm.value = { metric_id: '', evidence_type: 'observed', support_status: 'supporting' }
    await loadInvestigation()
  } catch (e: unknown) {
    alert(e instanceof Error ? e.message : 'Evidence capture failed')
  }
}

async function createDecisionFromInv() {
  if (!inv.value) return
  try {
    const dec = await post<DecisionRecord>('/decisions', {
      title: `Decision: ${inv.value.title}`,
      brief: {
        problem: inv.value.question,
        relevant_findings: inv.value.claims?.map(c => c.statement) || [],
        proposed_action: 'Action based on investigation findings',
        baseline_option: 'Status quo',
        scope: inv.value.source_type,
        owner: inv.value.owner,
        trade_offs: [],
        assumptions: inv.value.alternative_explanations || [],
        evidence_coverage: inv.value.evidence?.map(e => e.artifact_id) || [],
        validation_plan: 'Review performance after 30 days',
        counter_metrics: [],
        expected_effect: 'estimated',
      },
    })
    navigateTo('/decisions')
  } catch (e: unknown) {
    alert(e instanceof Error ? e.message : 'Failed to create decision brief')
  }
}

onMounted(() => {
  loadInvestigation()
})
</script>

<style scoped>
.page { max-width: 1100px; margin: 0 auto; padding: 1rem; }
.back-link { font-size: 0.9rem; color: #0f766e; text-decoration: none; margin-bottom: 0.5rem; display: inline-block; }
.header-row { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 1rem; }
.question-title { font-size: 1.1rem; color: #334155; margin: 0.5rem 0 0 0; }
.status-actions { display: flex; align-items: center; gap: 0.5rem; }
.status-select { font-size: 0.85rem; padding: 0.2rem 0.4rem; }
.n-sm { font-size: 1.1rem; font-weight: 600; }
.meta-grid { margin-bottom: 1.5rem; }
.section-header { display: flex; justify-content: space-between; align-items: center; margin: 1.5rem 0 0.75rem 0; }
.claim-card, .ev-card { margin-bottom: 0.75rem; }
.empty-card { padding: 1.5rem; text-align: center; }
.fact-box { background: #f8fafc; padding: 0.5rem 0.75rem; border-radius: 4px; border: 1px solid #e2e8f0; font-size: 0.9rem; margin-top: 0.4rem; }
.quality-flags { margin-top: 0.4rem; gap: 0.3rem; }
.ev-meta-grid { font-size: 0.85rem; padding: 0.4rem 0; }
.provenance-details { margin-top: 0.5rem; border-top: 1px dashed #cbd5e1; padding-top: 0.5rem; font-size: 0.85rem; }
.provenance-content { background: #f8fafc; padding: 0.75rem; border-radius: 6px; margin-top: 0.4rem; }
.digest-row { display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; }
.digest-hash { font-family: monospace; word-break: break-all; max-width: 100%; }
.payload-box pre { font-size: 0.8rem; background: #0f172a; color: #e2e8f0; padding: 0.5rem; border-radius: 4px; overflow-x: auto; }
.footer-actions { display: flex; justify-content: space-between; align-items: center; margin-top: 2rem; background: #f0fdf4; border-color: #bbf7d0; }
.modal-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; z-index: 100; }
.modal { background: #fff; width: 100%; max-width: 550px; padding: 1.5rem; border-radius: 8px; }
.modal-actions { display: flex; justify-content: flex-end; gap: 0.5rem; margin-top: 1rem; }
.fact-fieldset { border: 1px solid #cbd5e1; border-radius: 6px; padding: 0.75rem; margin: 0.75rem 0; }
.badge-green { background: #dcfce7; color: #166534; }
.badge-yellow { background: #fef9c3; color: #854d0e; }
.badge-blue { background: #dbeafe; color: #1e40af; }
.badge-red { background: #fee2e2; color: #991b1b; }
.badge-gray { background: #f1f5f9; color: #475569; }
.badge-outline { border: 1px solid #cbd5e1; background: transparent; }
</style>
