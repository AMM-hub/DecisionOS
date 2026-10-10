<template>
  <div class="decisions-page">
    <!-- Page Header -->
    <div class="page-head">
      <div class="titles">
        <div class="eyebrow">{{ t('decisions.title', locale) }}</div>
        <h1>{{ t('decisions.title', locale) }}</h1>
        <p class="desc">{{ t('decisions.description', locale) }}</p>
      </div>
      <div class="actions">
        <button class="btn btn-secondary btn-sm" @click="loadDecisions">
          <svg><use href="#i-pulse"/></svg>
          <span>Refresh</span>
        </button>
        <button class="btn btn-primary btn-sm" @click="showCreateModal = true">
          <svg><use href="#i-plus"/></svg>
          <span>{{ t('decisions.newDecision', locale) }}</span>
        </button>
      </div>
    </div>

    <!-- Loading State -->
    <div v-if="loading" class="loading">{{ t('common.loading', locale) }}</div>
    <div v-else-if="error" class="error-banner">{{ error }}</div>

    <!-- Enterprise Dense Table Panel -->
    <div v-else class="panel">
      <!-- Toolbar & Filters -->
      <div class="toolbar">
        <div class="search-inline">
          <svg><use href="#i-search"/></svg>
          <input
            v-model="searchQuery"
            type="search"
            placeholder="Search decisions…"
            aria-label="Search decisions"
          />
        </div>

        <select v-model="statusFilter" class="fld" aria-label="Filter by status">
          <option value="">All statuses</option>
          <option value="draft">Draft</option>
          <option value="proposed">Proposed</option>
          <option value="accepted">Accepted</option>
          <option value="implementation_pending">Implementation Pending</option>
          <option value="active">Active</option>
          <option value="review_due">Review Due</option>
          <option value="evaluated">Evaluated</option>
          <option value="closed">Closed</option>
          <option value="rejected">Rejected</option>
        </select>

        <span class="grow"></span>

        <div class="segmented" role="group" aria-label="Scope filter">
          <button
            type="button"
            :aria-pressed="scopeFilter === 'all'"
            @click="scopeFilter = 'all'"
          >
            All
          </button>
          <button
            type="button"
            :aria-pressed="scopeFilter === 'mine'"
            @click="scopeFilter = 'mine'"
          >
            Mine
          </button>
        </div>
      </div>

      <!-- Empty State inside Panel -->
      <div v-if="filteredDecisions.length === 0" class="empty" style="padding: 50px 20px;">
        <div class="e-ico">
          <svg><use href="#i-check-square"/></svg>
        </div>
        <h3>{{ locale === 'ar' ? 'لا توجد قرارات مطابقة' : 'No Operational Decisions Found' }}</h3>
        <p class="muted">
          {{ locale === 'ar' ? 'ابدأ بتسجيل أول قرار تشغيلي لربط الأدلة وتتبع النتائج والامتثال للحوكمة.' : 'Record your first operational decision to bind evidence artifacts, track outcomes, and enforce governance freeze.' }}
        </p>
        <button class="btn btn-primary btn-sm" style="margin-top: 10px;" @click="showCreateModal = true">
          {{ t('decisions.newDecision', locale) }}
        </button>
      </div>

      <!-- Table Scroll Container -->
      <div v-else class="table-scroll">
        <table class="dt">
          <thead>
            <tr>
              <th class="sortable" @click="toggleSort('id')">
                ID <span class="arrow">{{ sortKey === 'id' ? (sortDir === 1 ? '↑' : '↓') : '↕' }}</span>
              </th>
              <th class="sortable" @click="toggleSort('title')">
                Decision <span class="arrow">{{ sortKey === 'title' ? (sortDir === 1 ? '↑' : '↓') : '↕' }}</span>
              </th>
              <th>Owner</th>
              <th>Expected Effect</th>
              <th class="num">Evidence</th>
              <th>Status</th>
              <th class="sortable num" @click="toggleSort('created_at')">
                Created <span class="arrow">{{ sortKey === 'created_at' ? (sortDir === 1 ? '↑' : '↓') : '↕' }}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="dec in filteredDecisions"
              :key="dec.id"
              :class="{ selected: selectedDecision?.id === dec.id }"
              @click="openDecisionDrawer(dec)"
            >
              <td>
                <span class="id isolate">{{ dec.id }}</span>
              </td>
              <td>
                <div class="cell-stack">
                  <span class="cell-strong">{{ dec.title }}</span>
                  <span class="muted" style="font-size: 11px; max-width: 320px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                    {{ dec.brief?.problem }}
                  </span>
                </div>
              </td>
              <td>
                <span>{{ dec.brief?.owner || dec.created_by }}</span>
              </td>
              <td>
                <span class="chip plain">{{ dec.brief?.expected_effect || 'estimated' }}</span>
              </td>
              <td class="num">
                <span class="isolate mono font-weight-600">{{ boundEvidence[dec.id]?.length ?? (dec.evidence_bindings?.length ?? 0) }}</span>
              </td>
              <td>
                <span class="status-cell" :data-tone="statusTone(dec.status)">
                  <span class="status-dot"></span>
                  <span>{{ dec.status }}</span>
                  <span v-if="isFrozen(dec.status)" class="chip plain" style="font-size: 9.5px; padding: 1px 5px; margin-inline-start: 4px;">
                    frozen
                  </span>
                </span>
              </td>
              <td class="num faint">
                <span class="isolate">{{ formatDate(dec.created_at) }}</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Table Foot -->
      <div v-if="filteredDecisions.length > 0" class="table-foot">
        <span>Showing <strong class="isolate mono">{{ filteredDecisions.length }}</strong> of <strong class="isolate mono">{{ decisions.length }}</strong> decisions</span>
      </div>
    </div>

    <!-- ================= SLIDE-OUT DECISION DETAIL DRAWER ================= -->
    <div v-if="selectedDecision">
      <div class="scrim" @click="selectedDecision = null"></div>
      <aside class="drawer" role="dialog" aria-modal="true" :aria-label="selectedDecision.title">
        <div class="drawer-head">
          <div class="dh-top">
            <h2>{{ selectedDecision.title }}</h2>
            <button class="icon-btn" aria-label="Close" @click="selectedDecision = null">
              <svg><use href="#i-x"/></svg>
            </button>
          </div>
          <div class="row" style="margin-top: 8px; gap: 8px;">
            <span class="id isolate">{{ selectedDecision.id }}</span>
            <span class="chip" :data-tone="statusTone(selectedDecision.status)">
              <span class="d"></span>
              {{ selectedDecision.status }}
            </span>
            <span v-if="isFrozen(selectedDecision.status)" class="chip" data-tone="warn">
              <span class="d"></span>
              CONTEXT FROZEN
            </span>
            <span class="muted" style="font-size: 11.5px;">
              Owner: <strong>{{ selectedDecision.brief?.owner || selectedDecision.created_by }}</strong>
            </span>
          </div>
        </div>

        <div class="drawer-body">
          <!-- Problem Brief -->
          <div>
            <div class="faint" style="font-family: var(--font-mono); font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 6px;">
              Decision Brief
            </div>
            <div style="background: var(--surface-2); padding: 12px 14px; border-radius: var(--r); border: 1px solid var(--border); display: flex; flex-direction: column; gap: 8px; font-size: 12.5px;">
              <div><strong class="muted">Problem:</strong> <div>{{ selectedDecision.brief?.problem }}</div></div>
              <div><strong class="muted">Proposed Action:</strong> <div>{{ selectedDecision.brief?.proposed_action }}</div></div>
              <div class="row" style="gap: 16px; margin-top: 4px;">
                <div><span class="muted">Expected Effect:</span> <code class="isolate">{{ selectedDecision.brief?.expected_effect }}</code></div>
                <div><span class="muted">Scope:</span> <strong class="mono">{{ selectedDecision.brief?.scope || 'Global' }}</strong></div>
                <div><span class="muted">Baseline:</span> <span>{{ selectedDecision.brief?.baseline_option || 'Status quo' }}</span></div>
              </div>
            </div>
          </div>

          <!-- Counterevidence Checks -->
          <div v-if="selectedDecision.counterevidence?.length">
            <div class="faint" style="font-family: var(--font-mono); font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 6px;">
              Counterevidence Checks
            </div>
            <div style="display: flex; flex-direction: column; gap: 6px;">
              <div
                v-for="(ce, idx) in selectedDecision.counterevidence"
                :key="idx"
                style="display: flex; justify-content: space-between; align-items: center; padding: 7px 10px; background: var(--surface-2); border-radius: var(--r); font-size: 12px;"
              >
                <span>{{ ce.hypothesis }}</span>
                <span class="chip" :data-tone="ceTone(ce.state)">{{ ce.state }}</span>
              </div>
            </div>
          </div>

          <!-- Bound Evidence Chain -->
          <div>
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
              <div class="faint" style="font-family: var(--font-mono); font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.1em;">
                Evidence Chain ({{ boundEvidence[selectedDecision.id]?.length ?? 0 }})
              </div>
              <button
                v-if="!isFrozen(selectedDecision.status)"
                class="btn btn-secondary btn-xs"
                @click="openBindModal(selectedDecision.id)"
              >
                + Bind Artifact
              </button>
            </div>

            <div v-if="boundEvidence[selectedDecision.id]?.length" style="display: flex; flex-direction: column; gap: 8px;">
              <div
                v-for="b in boundEvidence[selectedDecision.id]"
                :key="b.id"
                style="padding: 10px 12px; background: var(--surface-2); border-radius: var(--r); border: 1px solid var(--border); font-size: 12px;"
              >
                <div style="display: flex; justify-content: space-between; align-items: center;">
                  <strong class="mono isolate">{{ b.evidence_id }}</strong>
                  <span class="chip" data-tone="accent">{{ b.binding_role }}</span>
                </div>
                <div v-if="b.evidence" class="row" style="margin-top: 6px; font-size: 11px; gap: 10px;">
                  <span class="hash isolate">{{ b.evidence.canonical_digest }}</span>
                  <span class="chip" data-tone="ok" style="font-size: 9.5px;">verified</span>
                  <span class="muted">Exactness: {{ b.evidence.exactness_class }}</span>
                </div>
              </div>
            </div>
            <p v-else class="muted" style="font-size: 12px;">No evidence artifacts bound to this decision.</p>
          </div>

          <!-- Amendments Audit Trail -->
          <div v-if="selectedDecision.amendments?.length">
            <div class="faint" style="font-family: var(--font-mono); font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 6px;">
              Amendments Log ({{ selectedDecision.amendments.length }})
            </div>
            <div style="display: flex; flex-direction: column; gap: 6px;">
              <div
                v-for="amd in selectedDecision.amendments"
                :key="amd.version"
                style="padding: 8px 10px; background: var(--surface-2); border-radius: var(--r); font-size: 11.5px;"
              >
                <span class="chip plain" style="font-size: 9.5px; margin-inline-end: 6px;">v{{ amd.version }}</span>
                <strong>{{ amd.author }}:</strong> {{ amd.reason }} ({{ amd.scope }})
                <span class="muted" style="float: right;">{{ formatDate(amd.created_at) }}</span>
              </div>
            </div>
          </div>

          <!-- Outcome Review Record (if evaluated) -->
          <div v-if="selectedDecision.outcome">
            <div class="faint" style="font-family: var(--font-mono); font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 6px;">
              Outcome Review Record
            </div>
            <div style="padding: 10px 12px; background: var(--surface-2); border-radius: var(--r); border: 1px solid var(--border); font-size: 12px;">
              <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                <strong>Verdict:</strong>
                <span class="chip" :data-tone="verdictTone(selectedDecision.outcome.review_verdict)">
                  {{ selectedDecision.outcome.review_verdict }}
                </span>
              </div>
              <p style="margin: 4px 0;">{{ selectedDecision.outcome.verdict_evidence }}</p>
              <div class="row muted" style="font-size: 11px; margin-top: 6px;">
                <span>Window: <strong>{{ selectedDecision.outcome.measurement_window }}</strong></span>
                <span>Data Rev: #{{ selectedDecision.outcome.data_revision }}</span>
              </div>
            </div>
          </div>

          <!-- Lifecycle Transitions -->
          <div>
            <div class="faint" style="font-family: var(--font-mono); font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 8px;">
              Lifecycle Actions
            </div>
            <div class="row" style="gap: 8px; flex-wrap: wrap;">
              <button
                v-if="selectedDecision.status === 'draft'"
                class="btn btn-sm btn-primary"
                :disabled="pendingTransitions[selectedDecision.id]"
                @click="transitionDecision(selectedDecision.id, 'proposed')"
              >
                Propose Decision
              </button>
              <button
                v-if="selectedDecision.status === 'proposed'"
                class="btn btn-sm btn-primary"
                :disabled="pendingTransitions[selectedDecision.id]"
                @click="transitionDecision(selectedDecision.id, 'accepted')"
              >
                Accept &amp; Freeze
              </button>
              <button
                v-if="selectedDecision.status === 'proposed'"
                class="btn btn-sm btn-danger"
                :disabled="pendingTransitions[selectedDecision.id]"
                @click="transitionDecision(selectedDecision.id, 'rejected')"
              >
                Reject
              </button>
              <button
                v-if="selectedDecision.status === 'accepted'"
                class="btn btn-sm btn-secondary"
                :disabled="pendingTransitions[selectedDecision.id]"
                @click="transitionDecision(selectedDecision.id, 'implementation_pending')"
              >
                Implementation Pending
              </button>
              <button
                v-if="selectedDecision.status === 'implementation_pending'"
                class="btn btn-sm btn-primary"
                :disabled="pendingTransitions[selectedDecision.id]"
                @click="transitionDecision(selectedDecision.id, 'active')"
              >
                Set Active
              </button>
              <button
                v-if="selectedDecision.status === 'active'"
                class="btn btn-sm btn-secondary"
                :disabled="pendingTransitions[selectedDecision.id]"
                @click="transitionDecision(selectedDecision.id, 'review_due')"
              >
                Mark Review Due
              </button>
              <button
                v-if="selectedDecision.status === 'review_due'"
                class="btn btn-sm btn-primary"
                :disabled="pendingTransitions[selectedDecision.id]"
                @click="openOutcomeModal(selectedDecision.id)"
              >
                Record Outcome
              </button>
              <button
                v-if="selectedDecision.status === 'evaluated'"
                class="btn btn-sm btn-secondary"
                :disabled="pendingTransitions[selectedDecision.id]"
                @click="transitionDecision(selectedDecision.id, 'closed')"
              >
                Close Decision
              </button>
            </div>
          </div>
        </div>

        <div class="drawer-foot">
          <button class="btn btn-secondary btn-sm" @click="selectedDecision = null">Close</button>
        </div>
      </aside>
    </div>

    <!-- Create Decision Modal -->
    <div v-if="showCreateModal" class="modal-wrap" @click.self="showCreateModal = false">
      <div class="modal">
        <div class="panel-head" style="border: 0; padding: 0 0 12px 0;">
          <h2>Create Decision Brief</h2>
          <button class="icon-btn" @click="showCreateModal = false"><svg><use href="#i-x"/></svg></button>
        </div>
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
          <div class="grid grid-2">
            <label class="field">
              <span>Baseline Option</span>
              <input v-model="createForm.brief.baseline_option" placeholder="Status quo" />
            </label>
            <label class="field">
              <span>Owner</span>
              <input v-model="createForm.brief.owner" required placeholder="Ops Manager" />
            </label>
          </div>
          <label class="field">
            <span>Expected Effect</span>
            <select v-model="createForm.brief.expected_effect">
              <option value="estimated">estimated</option>
              <option value="deterministic">deterministic</option>
              <option value="simulated">simulated</option>
              <option value="unknown">unknown</option>
            </select>
          </label>
          <div style="display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px;">
            <button type="button" class="btn btn-secondary btn-sm" @click="showCreateModal = false">
              {{ t('common.cancel', locale) }}
            </button>
            <button type="submit" class="btn btn-primary btn-sm">
              {{ t('common.create', locale) }}
            </button>
          </div>
        </form>
      </div>
    </div>

    <!-- Bind Evidence Modal -->
    <div v-if="showBindModal" class="modal-wrap" @click.self="showBindModal = false">
      <div class="modal">
        <div class="panel-head" style="border: 0; padding: 0 0 12px 0;">
          <h2>Bind Evidence Artifact</h2>
          <button class="icon-btn" @click="showBindModal = false"><svg><use href="#i-x"/></svg></button>
        </div>
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
          <div style="display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px;">
            <button type="button" class="btn btn-secondary btn-sm" @click="showBindModal = false">
              {{ t('common.cancel', locale) }}
            </button>
            <button type="submit" class="btn btn-primary btn-sm">Bind Artifact</button>
          </div>
        </form>
      </div>
    </div>

    <!-- Record Outcome Modal -->
    <div v-if="showOutcomeModal" class="modal-wrap" @click.self="showOutcomeModal = false">
      <div class="modal">
        <div class="panel-head" style="border: 0; padding: 0 0 12px 0;">
          <h2>Record Decision Outcome Review</h2>
          <button class="icon-btn" @click="showOutcomeModal = false"><svg><use href="#i-x"/></svg></button>
        </div>
        <form @submit.prevent="submitRecordOutcome">
          <label class="field">
            <span>Measurement Window</span>
            <input v-model="outcomeForm.measurement_window" required placeholder="e.g. 14d post implementation" />
          </label>
          <label class="field">
            <span>Review Verdict</span>
            <select v-model="outcomeForm.review_verdict">
              <option value="supported_improvement">Supported Improvement (Better than expected)</option>
              <option value="no_clear_change">No Clear Change (Neutral)</option>
              <option value="deterioration">Deterioration (Below expectation)</option>
              <option value="inconclusive">Inconclusive</option>
              <option value="not_evaluable">Not Evaluable</option>
            </select>
          </label>
          <label class="field">
            <span>Verdict Evidence &amp; Findings</span>
            <textarea v-model="outcomeForm.verdict_evidence" required rows="3" placeholder="SLA breaches dropped by 7.3% with no counter-metric deterioration" />
          </label>
          <div style="display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px;">
            <button type="button" class="btn btn-secondary btn-sm" @click="showOutcomeModal = false">
              {{ t('common.cancel', locale) }}
            </button>
            <button type="submit" class="btn btn-primary btn-sm">Record Outcome</button>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useLocale, t } from '~/composables/locale'
import type { DecisionRecord, DecisionEvidenceBinding } from '~/shared/types'

const { locale } = useLocale()
const { get, post } = useApi()

const decisions = ref<DecisionRecord[]>([])
const boundEvidence = ref<Record<string, DecisionEvidenceBinding[]>>({})
const pendingTransitions = ref<Record<string, boolean>>({})
const loading = ref(true)
const error = ref('')

const selectedDecision = ref<DecisionRecord | null>(null)
const searchQuery = ref('')
const statusFilter = ref('')
const scopeFilter = ref<'all' | 'mine'>('all')
const sortKey = ref<'id' | 'title' | 'created_at'>('created_at')
const sortDir = ref<1 | -1>(-1)

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

function statusTone(status: string): string {
  return ({
    draft: '',
    proposed: 'warn',
    accepted: 'ok',
    implementation_pending: 'accent',
    active: 'ok',
    review_due: 'warn',
    evaluated: 'accent',
    closed: '',
    rejected: 'crit',
  } as Record<string, string>)[status] || ''
}

function ceTone(state: string): string {
  return ({ detected: 'crit', not_detected: 'ok', not_testable: 'warn', not_run: '' } as Record<string, string>)[state] || ''
}

function verdictTone(verdict: string): string {
  return ({
    supported_improvement: 'ok',
    no_clear_change: 'warn',
    deterioration: 'crit',
    inconclusive: 'warn',
    not_evaluable: '',
  } as Record<string, string>)[verdict] || ''
}

function formatDate(iso: string): string {
  if (!iso) return '—'
  try { return new Date(iso).toLocaleDateString() } catch { return iso }
}

const filteredDecisions = computed(() => {
  return decisions.value.filter(d => {
    if (searchQuery.value) {
      const q = searchQuery.value.toLowerCase()
      const match = (d.id + ' ' + d.title + ' ' + (d.brief?.owner || '') + ' ' + (d.brief?.problem || '')).toLowerCase()
      if (!match.includes(q)) return false
    }
    if (statusFilter.value && d.status !== statusFilter.value) {
      return false
    }
    if (scopeFilter.value === 'mine') {
      const owner = (d.brief?.owner || d.created_by || '').toLowerCase()
      if (!owner.includes('manager') && !owner.includes('alpha')) return false
    }
    return true
  }).sort((a, b) => {
    const va = a[sortKey.value] || ''
    const vb = b[sortKey.value] || ''
    return String(va).localeCompare(String(vb)) * sortDir.value
  })
})

function toggleSort(key: 'id' | 'title' | 'created_at') {
  if (sortKey.value === key) {
    sortDir.value = (sortDir.value * -1) as 1 | -1
  } else {
    sortKey.value = key
    sortDir.value = 1
  }
}

function openDecisionDrawer(dec: DecisionRecord) {
  selectedDecision.value = dec
  loadDecisionEvidence(dec.id)
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
    createForm.value = {
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
        expected_effect: 'estimated',
      },
    }
    await loadDecisions()
  } catch (e: unknown) {
    alert(e instanceof Error ? e.message : 'Create decision failed')
  }
}

async function transitionDecision(decisionId: string, newStatus: string) {
  if (pendingTransitions.value[decisionId]) return
  pendingTransitions.value[decisionId] = true
  try {
    await post(`/decisions/${decisionId}/transition`, { status: newStatus, reason: `Transitioned to ${newStatus}` })
    await loadDecisions()
    if (selectedDecision.value && selectedDecision.value.id === decisionId) {
      const refreshed = decisions.value.find(d => d.id === decisionId)
      if (refreshed) selectedDecision.value = refreshed
    }
  } catch (e: unknown) {
    alert(e instanceof Error ? e.message : 'Status transition failed')
  } finally {
    pendingTransitions.value[decisionId] = false
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
    if (selectedDecision.value && selectedDecision.value.id === activeBindDecisionId.value) {
      const refreshed = decisions.value.find(d => d.id === activeBindDecisionId.value)
      if (refreshed) selectedDecision.value = refreshed
    }
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
    if (selectedDecision.value && selectedDecision.value.id === activeOutcomeDecisionId.value) {
      const refreshed = decisions.value.find(d => d.id === activeOutcomeDecisionId.value)
      if (refreshed) selectedDecision.value = refreshed
    }
  } catch (e: unknown) {
    alert(e instanceof Error ? e.message : 'Record outcome failed')
  }
}

onMounted(() => {
  loadDecisions()
})
</script>

<style scoped>
.decisions-page { display: flex; flex-direction: column; gap: 0; }
.page-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; margin-bottom: 20px; flex-wrap: wrap; }
.eyebrow { font-family: var(--font-mono); font-size: 10.5px; letter-spacing: 0.14em; text-transform: uppercase; color: var(--faint); margin-bottom: 6px; }
.page-head h1 { font-size: 20px; font-weight: 650; letter-spacing: -0.02em; color: var(--fg-strong); line-height: 1.2; }
.page-head .desc { font-size: 13px; color: var(--muted); margin-top: 4px; max-width: 68ch; }
.page-head .actions { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.hash { font-family: var(--font-mono); font-size: 11px; color: var(--fg); }
</style>
