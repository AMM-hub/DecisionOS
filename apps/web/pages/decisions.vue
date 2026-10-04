<template>
  <div class="page">
    <div class="header-row">
      <div>
        <h1>{{ t('decisions.title', locale) }}</h1>
        <p class="muted">{{ t('decisions.description', locale) }}</p>
      </div>
      <button class="btn btn-primary" @click="showCreateModal = true">
        {{ t('decisions.newDecision', locale) }}
      </button>
    </div>

    <!-- Loading / Error / List -->
    <div v-if="loading" class="loading">{{ t('common.loading', locale) }}</div>
    <div v-else-if="error" class="error-banner">{{ error }}</div>
    <div v-else-if="decisions.length === 0" class="card empty-state">
      <p>{{ t('common.noData', locale) }}</p>
    </div>
    <div v-else class="grid">
      <div v-for="dec in decisions" :key="dec.id" class="card dec-card">
        <div class="card-header">
          <div>
            <h2>{{ dec.title }}</h2>
            <div class="row text-xs muted">
              <span>Owner: <strong>{{ dec.brief?.owner || dec.created_by }}</strong></span> &middot;
              <span>Scope: <code>{{ dec.brief?.scope || 'Global' }}</code></span> &middot;
              <span>Created: {{ formatDate(dec.created_at) }}</span>
            </div>
          </div>
          <div class="row">
            <span :class="'badge badge-' + statusBadge(dec.status)">{{ dec.status }}</span>
            <span v-if="isFrozen(dec.status)" class="badge badge-frozen" title="Decision context is frozen against direct modification">
              Frozen
            </span>
          </div>
        </div>

        <div class="card-body">
          <!-- Problem Brief Summary -->
          <div class="brief-box">
            <p><strong>Problem:</strong> {{ dec.brief?.problem }}</p>
            <p><strong>Proposed Action:</strong> {{ dec.brief?.proposed_action }}</p>
            <p><strong>Expected Effect:</strong> <code>{{ dec.brief?.expected_effect }}</code></p>
          </div>

          <!-- Counterevidence Checks Summary -->
          <div v-if="dec.counterevidence?.length" class="ce-box margin-y">
            <span class="muted">Counterevidence Checks:</span>
            <div class="row margin-y">
              <div v-for="(ce, idx) in dec.counterevidence" :key="idx" class="ce-chip">
                <span>{{ ce.hypothesis }}:</span>
                <span :class="'badge badge-' + ceBadge(ce.state)">{{ ce.state }}</span>
              </div>
            </div>
          </div>

          <!-- Bound Evidence Set -->
          <div class="evidence-section margin-y">
            <div class="section-subhead">
              <h4>{{ t('decisions.evidenceBindings', locale) }} ({{ boundEvidence[dec.id]?.length ?? 0 }})</h4>
              <button v-if="!isFrozen(dec.status)" class="btn btn-xs" @click="openBindModal(dec.id)">
                {{ t('decisions.bindEvidence', locale) }}
              </button>
            </div>

            <div v-if="boundEvidence[dec.id]?.length" class="grid ev-grid">
              <div v-for="b in boundEvidence[dec.id]" :key="b.id" class="bound-ev-card">
                <div class="row justify-between">
                  <div>
                    <strong>Artifact {{ b.evidence_id }}</strong>
                    <span class="badge badge-outline text-xs margin-x">{{ b.binding_role }}</span>
                  </div>
                  <span class="text-xs muted">Bound by {{ b.bound_by }}</span>
                </div>
                <div v-if="b.evidence" class="ev-summary text-xs">
                  <span>Digest: <code class="hash">{{ b.evidence.canonical_digest }}</code></span> &middot;
                  <span class="badge badge-green">Integrity Verified</span> &middot;
                  <span>Exactness: {{ b.evidence.exactness_class }}</span>
                </div>
              </div>
            </div>
            <p v-else class="text-xs muted">No evidence artifacts bound yet.</p>
          </div>

          <!-- Frozen Context Notice / Amendments -->
          <div v-if="isFrozen(dec.status)" class="frozen-notice card">
            <p class="text-xs margin-0">
              <strong>Context Frozen:</strong> Decision context was frozen upon transition to <code>{{ dec.status }}</code>.
              Direct payload modifications are disabled; append-only amendments audit trail below.
            </p>
          </div>

          <!-- Amendments Log -->
          <details v-if="dec.amendments?.length" class="amendments-details margin-y">
            <summary>Amendments Audit Trail ({{ dec.amendments.length }})</summary>
            <div class="amendments-list">
              <div v-for="amd in dec.amendments" :key="amd.version" class="amd-item text-xs">
                <span class="badge badge-outline">v{{ amd.version }}</span>
                <strong>{{ amd.author }}:</strong> {{ amd.reason }} ({{ amd.scope }})
                <span class="muted">{{ formatDate(amd.created_at) }}</span>
              </div>
            </div>
          </details>

          <!-- Outcome Record Summary if Evaluated -->
          <div v-if="dec.outcome" class="outcome-box card margin-y">
            <div class="row justify-between">
              <strong>Outcome Review Record</strong>
              <span :class="'badge badge-' + verdictBadge(dec.outcome.review_verdict)">
                {{ dec.outcome.review_verdict }}
              </span>
            </div>
            <p class="text-xs margin-y">{{ dec.outcome.verdict_evidence }}</p>
            <div class="row text-xs muted">
              <span>Window: <strong>{{ dec.outcome.measurement_window }}</strong></span> &middot;
              <span>Data Rev: #{{ dec.outcome.data_revision }}</span>
            </div>
          </div>

          <!-- Lifecycle Action Buttons -->
          <div class="actions margin-top">
            <button v-if="dec.status === 'draft'" class="btn btn-sm" @click="transitionDecision(dec.id, 'proposed')">Propose Decision</button>
            <button v-if="dec.status === 'proposed'" class="btn btn-sm btn-success" @click="transitionDecision(dec.id, 'accepted')">Accept & Freeze</button>
            <button v-if="dec.status === 'proposed'" class="btn btn-sm danger" @click="transitionDecision(dec.id, 'rejected')">Reject</button>
            <button v-if="dec.status === 'accepted'" class="btn btn-sm" @click="transitionDecision(dec.id, 'implementation_pending')">Implementation Pending</button>
            <button v-if="dec.status === 'implementation_pending'" class="btn btn-sm" @click="transitionDecision(dec.id, 'active')">Set Active</button>
            <button v-if="dec.status === 'active'" class="btn btn-sm" @click="transitionDecision(dec.id, 'review_due')">Mark Review Due</button>
            <button v-if="dec.status === 'review_due'" class="btn btn-sm btn-primary" @click="openOutcomeModal(dec.id)">Record Outcome</button>
            <button v-if="dec.status === 'evaluated'" class="btn btn-sm secondary" @click="transitionDecision(dec.id, 'closed')">Close Decision</button>
          </div>
        </div>
      </div>
    </div>

    <!-- Create Decision Modal -->
    <div v-if="showCreateModal" class="modal-backdrop" @click.self="showCreateModal = false">
      <div class="modal card">
        <h2>Create Decision Brief</h2>
        <form @submit.prevent="createDecision">
          <label class="field">
            <span>Decision Title</span>
            <input v-model="createForm.title" required placeholder="e.g. ICU Capacity Expansion Strategy" />
          </label>
          <label class="field">
            <span>Problem Statement</span>
            <textarea v-model="createForm.brief.problem" required rows="2" placeholder="High ICU bed wait times" />
          </label>
          <label class="field">
            <span>Proposed Action</span>
            <textarea v-model="createForm.brief.proposed_action" required rows="2" placeholder="Reallocate 4 step-down beds to ICU" />
          </label>
          <div class="row">
            <label class="field">
              <span>Baseline Option</span>
              <input v-model="createForm.brief.baseline_option" placeholder="Status quo" />
            </label>
            <label class="field">
              <span>Owner</span>
              <input v-model="createForm.brief.owner" required placeholder="Ops Manager" />
            </label>
            <label class="field">
              <span>Expected Effect</span>
              <select v-model="createForm.brief.expected_effect">
                <option value="unknown">unknown</option>
                <option value="deterministic">deterministic</option>
                <option value="estimated">estimated</option>
                <option value="simulated">simulated</option>
              </select>
            </label>
          </div>
          <div class="modal-actions">
            <button type="button" class="btn secondary" @click="showCreateModal = false">{{ t('common.cancel', locale) }}</button>
            <button type="submit" class="btn btn-primary">{{ t('common.create', locale) }}</button>
          </div>
        </form>
      </div>
    </div>

    <!-- Bind Evidence Modal -->
    <div v-if="showBindModal" class="modal-backdrop" @click.self="showBindModal = false">
      <div class="modal card">
        <h2>Bind Evidence Artifact</h2>
        <form @submit.prevent="submitBindEvidence">
          <label class="field">
            <span>Evidence Artifact ID</span>
            <input v-model="bindForm.evidence_id" required placeholder="ev-12345678" />
          </label>
          <label class="field">
            <span>Binding Role</span>
            <select v-model="bindForm.binding_role">
              <option value="primary_support">primary_support</option>
              <option value="contributing">contributing</option>
              <option value="counter_evidence">counter_evidence</option>
            </select>
          </label>
          <div class="modal-actions">
            <button type="button" class="btn secondary" @click="showBindModal = false">{{ t('common.cancel', locale) }}</button>
            <button type="submit" class="btn btn-primary">Bind Artifact</button>
          </div>
        </form>
      </div>
    </div>

    <!-- Record Outcome Review Modal -->
    <div v-if="showOutcomeModal" class="modal-backdrop" @click.self="showOutcomeModal = false">
      <div class="modal card">
        <h2>Record Decision Outcome Review</h2>
        <p class="text-xs muted">Evaluate observed post-implementation metric results against initial expectations.</p>
        <form @submit.prevent="submitRecordOutcome">
          <label class="field">
            <span>Measurement Window</span>
            <input v-model="outcomeForm.measurement_window" required placeholder="e.g. 14d post implementation" />
          </label>
          <label class="field">
            <span>Review Verdict</span>
            <select v-model="outcomeForm.review_verdict">
              <option value="supported_improvement">Supported Improvement (Better than expected)</option>
              <option value="no_clear_change">No Clear Change (Met expectation / Neutral)</option>
              <option value="deterioration">Deterioration (Below expectation)</option>
              <option value="inconclusive">Inconclusive</option>
              <option value="not_evaluable">Not Evaluable</option>
            </select>
          </label>
          <label class="field">
            <span>Verdict Evidence & Findings</span>
            <textarea v-model="outcomeForm.verdict_evidence" required rows="3" placeholder="SLA breaches dropped by 7.3% with no counter-metric deterioration" />
          </label>
          <div class="modal-actions">
            <button type="button" class="btn secondary" @click="showOutcomeModal = false">{{ t('common.cancel', locale) }}</button>
            <button type="submit" class="btn btn-primary">Record Outcome</button>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useLocale, t } from '~/composables/locale'
import type { DecisionRecord, DecisionEvidenceBinding } from '~/shared/types'

const { locale } = useLocale()
const { get, post } = useApi()

const decisions = ref<DecisionRecord[]>([])
const boundEvidence = ref<Record<string, DecisionEvidenceBinding[]>>({})
const loading = ref(true)
const error = ref('')

const showCreateModal = ref(false)
const createForm = ref({
  title: '',
  brief: {
    problem: '',
    relevant_findings: [],
    proposed_action: '',
    baseline_option: 'Status quo',
    scope: 'Global',
    owner: '',
    trade_offs: [],
    assumptions: [],
    evidence_coverage: [],
    validation_plan: 'Review after 30 days',
    counter_metrics: [],
    expected_effect: 'estimated' as const,
  },
})

const showBindModal = ref(false)
const activeBindDecisionId = ref('')
const bindForm = ref({
  evidence_id: '',
  binding_role: 'primary_support' as const,
})

const showOutcomeModal = ref(false)
const activeOutcomeDecisionId = ref('')
const outcomeForm = ref({
  measurement_window: '14d post implementation',
  review_verdict: 'supported_improvement',
  verdict_evidence: '',
})

function isFrozen(status: string): boolean {
  return ['accepted', 'implementation_pending', 'active', 'review_due', 'evaluated', 'closed', 'superseded'].includes(status)
}

function statusBadge(status: string): string {
  return ({
    draft: 'gray', proposed: 'yellow', accepted: 'green',
    implementation_pending: 'blue', active: 'green', review_due: 'orange',
    evaluated: 'purple', closed: 'gray', rejected: 'red',
  } as Record<string, string>)[status] || 'gray'
}

function verdictBadge(verdict: string): string {
  return ({
    supported_improvement: 'green', no_clear_change: 'yellow', deterioration: 'red',
    inconclusive: 'orange', not_evaluable: 'gray'
  } as Record<string, string>)[verdict] || 'purple'
}


function ceBadge(state: string): string {
  return ({ detected: 'red', not_detected: 'green', not_testable: 'yellow', not_run: 'gray' } as Record<string, string>)[state] || 'gray'
}

function formatDate(iso: string): string {
  if (!iso) return '—'
  try { return new Date(iso).toLocaleDateString() } catch { return iso }
}

async function loadDecisions() {
  loading.value = true
  error.value = ''
  try {
    const res = await get<DecisionRecord[]>('/decisions')
    decisions.value = Array.isArray(res) ? res : []
    for (const d of decisions.value) {
      loadDecisionEvidence(d.id)
    }
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : 'Failed to load decisions'
  } finally {
    loading.value = false
  }
}

async function loadDecisionEvidence(decisionId: string) {
  try {
    const evs = await get<DecisionEvidenceBinding[]>(`/decisions/${decisionId}/evidence`)
    boundEvidence.value[decisionId] = Array.isArray(evs) ? evs : []
  } catch {
    boundEvidence.value[decisionId] = []
  }
}

async function createDecision() {
  try {
    await post<DecisionRecord>('/decisions', createForm.value)
    showCreateModal.value = false
    createForm.value = { title: '', brief: { problem: '', relevant_findings: [], proposed_action: '', baseline_option: 'Status quo', scope: 'Global', owner: '', trade_offs: [], assumptions: [], evidence_coverage: [], validation_plan: 'Review after 30 days', counter_metrics: [], expected_effect: 'estimated' } }
    await loadDecisions()
  } catch (e: unknown) {
    alert(e instanceof Error ? e.message : 'Create decision failed')
  }
}

async function transitionDecision(decisionId: string, newStatus: string) {
  try {
    await post(`/decisions/${decisionId}/transition`, { status: newStatus, reason: `Transitioned to ${newStatus}` })
    await loadDecisions()
  } catch (e: unknown) {
    alert(e instanceof Error ? e.message : 'Status transition failed')
  }
}

function openBindModal(decisionId: string) {
  activeBindDecisionId.value = decisionId
  bindForm.value = { evidence_id: '', binding_role: 'primary_support' }
  showBindModal.value = true
}

async function submitBindEvidence() {
  if (!activeBindDecisionId.value) return
  try {
    await post(`/decisions/${activeBindDecisionId.value}/evidence`, bindForm.value)
    showBindModal.value = false
    await loadDecisionEvidence(activeBindDecisionId.value)
  } catch (e: unknown) {
    alert(e instanceof Error ? e.message : 'Bind evidence failed')
  }
}

function openOutcomeModal(decisionId: string) {
  activeOutcomeDecisionId.value = decisionId
  outcomeForm.value = {
    measurement_window: '14d post implementation',
    review_verdict: 'supported_improvement',
    verdict_evidence: 'Observed reduction in SLA breaches with stable counter-metrics.',
  }
  showOutcomeModal.value = true
}

async function submitRecordOutcome() {
  if (!activeOutcomeDecisionId.value) return
  try {
    await post(`/decisions/${activeOutcomeDecisionId.value}/outcome`, outcomeForm.value)
    showOutcomeModal.value = false
    await loadDecisions()
  } catch (e: unknown) {
    alert(e instanceof Error ? e.message : 'Record outcome failed')
  }
}

onMounted(() => {
  loadDecisions()
})
</script>

<style scoped>
.page { max-width: 1100px; margin: 0 auto; padding: 1rem; }
.header-row { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 1rem; }
.dec-card { margin-bottom: 1rem; }
.brief-box { background: #f8fafc; padding: 0.75rem; border-radius: 6px; border: 1px solid #e2e8f0; margin-top: 0.5rem; }
.brief-box p { margin: 0.2rem 0; font-size: 0.9rem; }
.ce-chip { font-size: 0.85rem; display: flex; align-items: center; gap: 0.3rem; }
.evidence-section { border-top: 1px solid #e2e8f0; padding-top: 0.75rem; margin-top: 0.75rem; }
.section-subhead { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem; }
.section-subhead h4 { margin: 0; font-size: 0.95rem; }
.bound-ev-card { background: #f1f5f9; padding: 0.5rem 0.75rem; border-radius: 6px; margin-bottom: 0.4rem; font-size: 0.85rem; }
.hash { font-family: monospace; font-size: 0.8em; word-break: break-all; }
.frozen-notice { background: #fffbeb; border-color: #fde68a; color: #92400e; padding: 0.5rem 0.75rem; margin-top: 0.75rem; }
.badge-frozen { background: #fef3c7; color: #92400e; border: 1px solid #fde68a; margin-left: 0.4rem; }
.amendments-details { margin-top: 0.5rem; font-size: 0.85rem; }
.amd-item { background: #f8fafc; padding: 0.35rem 0.5rem; border-radius: 4px; margin-top: 0.25rem; }
.btn-success { background: #166534; }
.badge-green { background: #dcfce7; color: #166534; }
.badge-yellow { background: #fef9c3; color: #854d0e; }
.badge-blue { background: #dbeafe; color: #1e40af; }
.badge-purple { background: #f3e8ff; color: #6b21a8; }
.badge-red { background: #fee2e2; color: #991b1b; }
.badge-gray { background: #f1f5f9; color: #475569; }
.badge-outline { border: 1px solid #cbd5e1; background: transparent; }
.modal-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; z-index: 100; }
.modal { background: #fff; width: 100%; max-width: 550px; padding: 1.5rem; border-radius: 8px; }
.modal-actions { display: flex; justify-content: flex-end; gap: 0.5rem; margin-top: 1rem; }
</style>
