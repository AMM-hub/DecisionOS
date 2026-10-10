<template>
  <div class="investigation-detail-page">
    <div v-if="loading" class="loading">{{ t('common.loading', locale) }}</div>
    <div v-else-if="error" class="error-banner">{{ error }}</div>
    <div v-else-if="inv" class="inv-workspace">
      <!-- Breadcrumb / Header -->
      <div class="page-head" style="margin-bottom: 16px; display: flex; justify-content: space-between; align-items: flex-start; gap: 14px; flex-wrap: wrap;">
        <div>
          <NuxtLink to="/investigations" class="back-link" style="display: inline-flex; align-items: center; gap: 5px; font-size: 12px; color: var(--accent); margin-bottom: 4px; font-weight: 550;">
            &larr; {{ locale === 'ar' ? 'العودة للتحقيقات' : 'Back to Investigations' }}
          </NuxtLink>
          <div class="eyebrow" style="font-family: var(--font-mono); font-size: 11px; color: var(--faint); text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 2px;">
            Track <span class="isolate">{{ inv.id }}</span>
          </div>
          <h1 style="font-size: 20px; font-weight: 700; color: var(--fg-strong); margin: 0;">{{ inv.title }}</h1>
          <p class="muted" style="font-size: 13px; margin-top: 4px;">
            <strong style="color: var(--fg);">Question:</strong> {{ inv.question }}
          </p>
        </div>
        <div style="display: flex; align-items: center; gap: 10px;">
          <span class="chip" :data-tone="statusBadgeTone(inv.status)">
            <span class="d"></span>
            {{ inv.status }}
          </span>
          <select v-model="selectedStatus" @change="updateStatus" style="font-size: 12px; height: 32px; padding: 2px 8px;">
            <option value="open">open</option>
            <option value="in_progress">in_progress</option>
            <option value="resolved">resolved</option>
            <option value="closed">closed</option>
          </select>
        </div>
      </div>

      <!-- Main Overview KPI Strip -->
      <div class="kpi-band" style="margin-bottom: 16px;">
        <div class="kpi">
          <div class="k-label"><span class="mark"></span> Source Type</div>
          <div class="k-val isolate" style="font-size: 18px;">{{ inv.source_type }}</div>
          <div class="k-foot">Origin classification</div>
        </div>
        <div class="kpi">
          <div class="k-label"><span class="mark"></span> Responsible Owner</div>
          <div class="k-val isolate" style="font-size: 18px;">{{ inv.owner }}</div>
          <div class="k-foot">Operational lead</div>
        </div>
        <div class="kpi">
          <div class="k-label"><span class="mark"></span> Created Date</div>
          <div class="k-val isolate" style="font-size: 18px;">{{ formatDate(inv.created_at) }}</div>
          <div class="k-foot">Audit entry stamp</div>
        </div>
        <div class="kpi" :data-tone="inv.evidence?.length ? 'ok' : 'warn'">
          <div class="k-label"><span class="mark"></span> Evidence Artifacts</div>
          <div class="k-val isolate" style="font-size: 22px;">{{ inv.evidence?.length ?? 0 }}</div>
          <div class="k-foot">{{ inv.claims?.length ?? 0 }} claims formulated</div>
        </div>
      </div>

      <!-- Alternative Explanations -->
      <div v-if="inv.alternative_explanations?.length" class="panel" style="margin-bottom: 16px;">
        <div class="panel-head">
          <h3 style="font-size: 13.5px; margin: 0;">Alternative Explanations Under Investigation</h3>
        </div>
        <div class="panel-body">
          <ul style="margin: 0; padding-inline-start: 18px; font-size: 13px; color: var(--fg);">
            <li v-for="(exp, idx) in inv.alternative_explanations" :key="idx" style="margin-bottom: 4px;">{{ exp }}</li>
          </ul>
        </div>
      </div>

      <!-- Structured Claims Section -->
      <div class="panel" style="margin-bottom: 16px;">
        <div class="panel-head">
          <div style="display: flex; align-items: center; gap: 8px;">
            <h3 style="font-size: 13.5px; margin: 0;">{{ t('investigations.claims', locale) }}</h3>
            <span class="chip">{{ inv.claims?.length ?? 0 }}</span>
          </div>
          <button class="btn btn-secondary btn-sm" @click="showAddClaimModal = true">
            + {{ t('investigations.addClaim', locale) }}
          </button>
        </div>
        <div class="panel-body">
          <div v-if="!inv.claims || inv.claims.length === 0" style="padding: 18px; text-align: center;">
            <p class="muted" style="font-size: 13px;">No structured claims registered for this investigation yet.</p>
          </div>
          <div v-else style="display: flex; flex-direction: column; gap: 10px;">
            <div v-for="claim in inv.claims" :key="claim.id" class="panel" style="margin-bottom: 0; background: var(--surface-2); border-color: var(--border);">
              <div class="panel-head" style="padding: 8px 12px; background: transparent;">
                <div style="font-weight: 600; color: var(--fg-strong); font-size: 13px;">{{ claim.statement }}</div>
                <div style="display: flex; gap: 6px; align-items: center;">
                  <span class="chip">{{ claim.evidence_type }}</span>
                  <span class="chip" :data-tone="supportBadgeTone(claim.support_status)">{{ claim.support_status }}</span>
                </div>
              </div>
              <div class="panel-body" style="padding: 10px 12px;">
                <div v-if="claim.structured_fact" style="background: var(--surface); padding: 6px 10px; border-radius: var(--r-sm); border: 1px solid var(--border); font-size: 12.5px; margin-bottom: 6px;">
                  <span class="muted">Fact Reference:</span>
                  <code class="isolate" style="margin: 0 4px;">{{ claim.structured_fact.metric_id }}</code> =
                  <strong class="isolate num">{{ claim.structured_fact.value }} {{ claim.structured_fact.unit || '' }}</strong>
                </div>
                <div v-if="claim.quality_flags?.length" style="display: flex; gap: 6px; flex-wrap: wrap;">
                  <span v-for="flag in claim.quality_flags" :key="flag" class="chip" data-tone="warn">{{ flag }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Immutable Evidence Artifacts Section -->
      <div class="panel" style="margin-bottom: 16px;">
        <div class="panel-head">
          <div style="display: flex; align-items: center; gap: 8px;">
            <h3 style="font-size: 13.5px; margin: 0;">{{ t('investigations.evidence', locale) }}</h3>
            <span class="chip">{{ inv.evidence?.length ?? 0 }}</span>
          </div>
          <button class="btn btn-secondary btn-sm" @click="showCaptureEvidenceModal = true">
            + {{ t('investigations.captureEvidence', locale) }}
          </button>
        </div>
        <div class="panel-body">
          <div v-if="!inv.evidence || inv.evidence.length === 0" style="padding: 18px; text-align: center;">
            <p class="muted" style="font-size: 13px;">No evidence artifacts captured for this investigation yet.</p>
          </div>
          <div v-else style="display: flex; flex-direction: column; gap: 12px;">
            <div v-for="ev in inv.evidence" :key="ev.artifact_id" class="panel" style="margin-bottom: 0; background: var(--surface-2); border-color: var(--border);">
              <div class="panel-head" style="padding: 10px 14px; background: transparent;">
                <div>
                  <div style="font-weight: 600; color: var(--fg-strong); font-size: 13px;">
                    Artifact <span class="isolate mono">{{ ev.artifact_id }}</span>
                  </div>
                  <div class="muted isolate" style="font-size: 11.5px; margin-top: 2px;">
                    Metric: <code>{{ ev.metric_id }}</code> &middot; Dataset: <code>{{ ev.dataset_id }}</code> r#{{ ev.dataset_revision }}
                  </div>
                </div>
                <div style="display: flex; gap: 6px; align-items: center;">
                  <span class="chip">{{ ev.evidence_type }}</span>
                  <span class="chip" :data-tone="supportBadgeTone(ev.support_status)">{{ ev.support_status }}</span>
                </div>
              </div>

              <div class="panel-body" style="padding: 12px 14px;">
                <div class="grid cols-3" style="font-size: 12px; margin-bottom: 8px;">
                  <div><span class="muted">Exactness:</span> <code class="isolate">{{ ev.exactness_class }}</code></div>
                  <div><span class="muted">Reproducibility:</span> <code class="isolate">{{ ev.reproducibility_status }}</code></div>
                  <div><span class="muted">Row Count:</span> <strong class="isolate num">{{ ev.row_count }}</strong></div>
                </div>

                <!-- Quality Flags -->
                <div v-if="ev.quality_flags?.length" style="display: flex; gap: 6px; align-items: center; margin-bottom: 8px;">
                  <span class="muted" style="font-size: 12px;">Quality Flags:</span>
                  <span v-for="flag in ev.quality_flags" :key="flag" class="chip" data-tone="warn">{{ flag }}</span>
                </div>

                <!-- Expandable Provenance Details -->
                <details style="margin-top: 8px; border-top: 1px dashed var(--border-strong); padding-top: 8px; font-size: 12px;">
                  <summary style="cursor: pointer; color: var(--muted); font-weight: 550;">Provenance &amp; Cryptographic Integrity</summary>
                  <div style="background: var(--surface); padding: 10px; border-radius: var(--r-sm); border: 1px solid var(--border); margin-top: 6px;">
                    <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 6px;">
                      <span class="muted">Canonical Digest:</span>
                      <code class="isolate" style="word-break: break-all; font-size: 11px;">{{ ev.canonical_digest }}</code>
                      <span class="chip" data-tone="ok">Integrity Verified</span>
                    </div>
                    <div class="faint isolate" style="font-size: 11px; margin-bottom: 6px;">
                      Storage: {{ ev.storage_format }} &middot; Created By: {{ ev.created_by }} &middot; Created At: {{ formatDate(ev.created_at) }}
                    </div>
                    <div v-if="ev.payload_json" style="margin-top: 6px;">
                      <span class="muted" style="font-size: 11px;">Stored Payload Snippet:</span>
                      <pre class="isolate" style="font-family: var(--font-mono); font-size: 11px; background: var(--surface-3); color: var(--fg); padding: 8px; border-radius: 4px; overflow-x: auto; margin: 4px 0 0 0;">{{ ev.payload_json }}</pre>
                    </div>
                  </div>
                </details>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Action Footer: Create Decision Brief -->
      <div class="panel" style="background: var(--accent-soft); border-color: var(--accent-line); padding: 16px 20px; display: flex; justify-content: space-between; align-items: center; gap: 16px; flex-wrap: wrap;">
        <div>
          <h3 style="font-size: 14.5px; font-weight: 650; color: var(--fg-strong); margin: 0;">Ready to turn findings into a Decision?</h3>
          <p class="muted" style="font-size: 12.5px; margin-top: 2px;">
            Initialize a formalized Decision Brief with all verified evidence gathered in this investigation.
          </p>
        </div>
        <button class="btn btn-primary btn-sm" @click="createDecisionFromInv">
          <svg><use href="#i-check-square"/></svg>
          <span>{{ t('investigations.convertDecision', locale) }}</span>
        </button>
      </div>

      <!-- Add Claim Modal -->
      <div v-if="showAddClaimModal" class="modal-backdrop" @click.self="showAddClaimModal = false">
        <div class="modal">
          <h2 style="font-size: 16px; font-weight: 650; margin-bottom: 14px; color: var(--fg-strong);">Add Structured Claim</h2>
          <form @submit.prevent="submitClaim">
            <label class="field">
              <span>{{ t('investigations.statement', locale) }}</span>
              <textarea v-model="claimForm.statement" required rows="2" placeholder="e.g. ICU stay duration increased by 2.4 hours" />
            </label>
            <div class="grid cols-2" style="gap: 10px;">
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
            <fieldset style="border: 1px solid var(--border); border-radius: var(--r); padding: 10px 12px; margin: 10px 0;">
              <legend style="font-size: 11.5px; font-weight: 600; color: var(--muted); padding: 0 4px;">Structured Fact (Optional)</legend>
              <div class="grid cols-3" style="gap: 8px;">
                <label class="field" style="margin: 0;">
                  <span>Metric ID</span>
                  <input v-model="claimForm.structured_fact.metric_id" placeholder="m_icu_stay" />
                </label>
                <label class="field" style="margin: 0;">
                  <span>Value</span>
                  <input v-model="claimForm.structured_fact.value" placeholder="2.4" />
                </label>
                <label class="field" style="margin: 0;">
                  <span>Unit</span>
                  <input v-model="claimForm.structured_fact.unit" placeholder="hours" />
                </label>
              </div>
            </fieldset>
            <div style="display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px;">
              <button type="button" class="btn btn-secondary btn-sm" @click="showAddClaimModal = false">{{ t('common.cancel', locale) }}</button>
              <button type="submit" class="btn btn-primary btn-sm">{{ t('common.save', locale) }}</button>
            </div>
          </form>
        </div>
      </div>

      <!-- Capture Evidence Modal -->
      <div v-if="showCaptureEvidenceModal" class="modal-backdrop" @click.self="showCaptureEvidenceModal = false">
        <div class="modal">
          <h2 style="font-size: 16px; font-weight: 650; margin-bottom: 14px; color: var(--fg-strong);">Capture Certified Metric Evidence</h2>
          <form @submit.prevent="submitEvidenceCapture">
            <label class="field">
              <span>Metric ID</span>
              <input v-model="evidenceForm.metric_id" required placeholder="m_occupancy" />
            </label>
            <div class="grid cols-2" style="gap: 10px;">
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
            <div style="display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px;">
              <button type="button" class="btn btn-secondary btn-sm" @click="showCaptureEvidenceModal = false">{{ t('common.cancel', locale) }}</button>
              <button type="submit" class="btn btn-primary btn-sm">Capture Snapshot</button>
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

function statusBadgeTone(status: string): string {
  switch (status) {
    case 'resolved': return 'ok'
    case 'in_progress': return 'accent'
    case 'open': return 'warn'
    default: return 'muted'
  }
}

function supportBadgeTone(status: string): string {
  switch (status) {
    case 'supporting': return 'ok'
    case 'counter': return 'crit'
    case 'unverified': return 'warn'
    default: return 'muted'
  }
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
