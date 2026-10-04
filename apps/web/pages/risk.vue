<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useApi } from '~/composables/api'
import { useLocale, t } from '~/composables/locale'

const { get, post, user } = useApi()
const { locale } = useLocale()

interface PredictiveTarget {
  id: string
  name: string
  entity_type: string
  outcome_window: string
  deadline_semantics: string
}

interface PredictiveModel {
  id: string
  target_id: string
  version: number
  algorithm: string
  status: string
  threshold_policy: {
    policy_type?: string
    capacity?: number
    threshold?: number
  }
}

interface CaseRiskItem {
  case_id: string
  target_id: string
  target_name: string
  outcome_window: string
  deadline: string
  current_age: string
  case_state: string
  score: number | null
  probability_status: string
  threshold: number
  risk_tier: string | null
  model_id: string
  model_version: number
  model_status: string
  last_scored: string
  data_freshness: string
  suitability_state: string
  reason?: string
  factors: Array<{ factor: string; impact: string }>
}

const loading = ref(true)
const targets = ref<PredictiveTarget[]>([])
const models = ref<PredictiveModel[]>([])
const riskQueue = ref<CaseRiskItem[]>([])
const selectedItem = ref<CaseRiskItem | null>(null)
const launchingInv = ref(false)
const invResult = ref<{ id: string } | null>(null)

async function loadRiskQueue() {
  loading.value = true
  try {
    const tgts = await get<PredictiveTarget[]>('/v1/predictive/targets').catch(() => [])
    const mdls = await get<PredictiveModel[]>('/v1/predictive/models').catch(() => [])
    targets.value = tgts || []
    models.value = mdls || []

    // Synthetic demo risk queue cases covering all supported and unsupported states
    riskQueue.value = [
      {
        case_id: 'CASE-8021',
        target_id: tgts[0]?.id || 'tgt-sla-24h',
        target_name: 'Case SLA Breach 24h',
        outcome_window: '24h',
        deadline: '2026-10-05T14:00:00Z',
        current_age: '18h 30m',
        case_state: 'eligible',
        score: 0.845,
        probability_status: 'calibrated',
        threshold: 0.50,
        risk_tier: 'HIGH',
        model_id: mdls[0]?.id || 'mdl-alpha-lr',
        model_version: 1,
        model_status: 'active',
        last_scored: '2026-10-04T19:30:00Z',
        data_freshness: '5m ago',
        suitability_state: 'suitable',
        factors: [
          { factor: 'Recent step re-assignments (>3)', impact: '+0.28' },
          { factor: 'High queue depth in tier 2 support', impact: '+0.22' },
          { factor: 'Elapsing time ratio (>75% SLA window)', impact: '+0.19' }
        ]
      },
      {
        case_id: 'CASE-8022',
        target_id: tgts[0]?.id || 'tgt-sla-24h',
        target_name: 'Case SLA Breach 24h',
        outcome_window: '24h',
        deadline: '2026-10-05T18:00:00Z',
        current_age: '12h 10m',
        case_state: 'eligible',
        score: 0.582,
        probability_status: 'calibrated',
        threshold: 0.50,
        risk_tier: 'HIGH',
        model_id: mdls[0]?.id || 'mdl-alpha-lr',
        model_version: 1,
        model_status: 'active',
        last_scored: '2026-10-04T19:30:00Z',
        data_freshness: '5m ago',
        suitability_state: 'suitable',
        factors: [
          { factor: 'Customer VIP flag set', impact: '+0.15' },
          { factor: 'Pending third-party vendor response', impact: '+0.12' }
        ]
      },
      {
        case_id: 'CASE-8019',
        target_id: tgts[0]?.id || 'tgt-sla-24h',
        target_name: 'Case SLA Breach 24h',
        outcome_window: '24h',
        deadline: '2026-10-04T12:00:00Z',
        current_age: '31h 15m',
        case_state: 'already_overdue',
        score: null,
        probability_status: 'uncalibrated',
        threshold: 0.50,
        risk_tier: null,
        model_id: mdls[0]?.id || 'mdl-alpha-lr',
        model_version: 1,
        model_status: 'active',
        last_scored: '2026-10-04T19:30:00Z',
        data_freshness: '5m ago',
        suitability_state: 'already_overdue',
        reason: 'Observation time >= SLA deadline; case is already overdue',
        factors: []
      },
      {
        case_id: 'CASE-8025',
        target_id: tgts[0]?.id || 'tgt-sla-24h',
        target_name: 'Case SLA Breach 24h',
        outcome_window: '24h',
        deadline: '2026-10-06T09:00:00Z',
        current_age: '2h 45m',
        case_state: 'prediction_unavailable',
        score: null,
        probability_status: 'uncalibrated',
        threshold: 0.50,
        risk_tier: null,
        model_id: 'mdl-beta-rf',
        model_version: 2,
        model_status: 'suspended',
        last_scored: '2026-10-04T19:30:00Z',
        data_freshness: '5m ago',
        suitability_state: 'model_suspended',
        reason: 'Active model for this target has been suspended by governance',
        factors: []
      }
    ]
  } finally {
    loading.value = false
  }
}

async function launchProactiveInvestigation(item: CaseRiskItem) {
  launchingInv.value = true
  invResult.value = null
  try {
    const inv = await post<{ id: string }>('/v1/investigations', {
      title: `Risk Investigation: ${item.case_id} (${item.target_name})`,
      question: `What operational factors drive breach risk for ${item.case_id}?`,
      source_type: 'predictive_risk',
      source_id: item.case_id,
      alternative_explanations: ['Staffing bottleneck', 'Vendor delay', 'Volume surge']
    })
    invResult.value = inv

    // If prediction exists, bind it as estimated evidence
    try {
      const pred = await post<{ prediction_id: string }>('/v1/predictive/score', {
        model_id: item.model_id,
        case_id: item.case_id,
        observation_time: new Date().toISOString(),
        deadline: item.deadline
      })
      if (pred && pred.prediction_id) {
        await post(`/v1/predictive/predictions/${pred.prediction_id}/evidence`, {
          investigation_id: inv.id
        })
      }
    } catch {
      // Best-effort evidence binding
    }
  } finally {
    launchingInv.value = false
  }
}

onMounted(() => {
  loadRiskQueue()
})
</script>

<template>
  <div class="risk-page">
    <h2>{{ t('predictiveRisk.title', locale) }}</h2>
    <p class="muted">{{ t('predictiveRisk.description', locale) }}</p>

    <div v-if="loading" class="card muted">
      {{ t('common.loading', locale) }}
    </div>

    <div v-else class="card">
      <table>
        <thead>
          <tr>
            <th>{{ t('predictiveRisk.caseId', locale) }}</th>
            <th>{{ t('predictiveRisk.targetWindow', locale) }}</th>
            <th>{{ t('predictiveRisk.deadline', locale) }}</th>
            <th>{{ t('predictiveRisk.currentAge', locale) }}</th>
            <th>{{ t('predictiveRisk.probability', locale) }}</th>
            <th>{{ t('predictiveRisk.thresholdState', locale) }}</th>
            <th>{{ t('predictiveRisk.modelVersion', locale) }}</th>
            <th>{{ t('predictiveRisk.suitabilityState', locale) }}</th>
            <th>{{ t('common.actions', locale) }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in riskQueue" :key="item.case_id" :class="{ selected: selectedItem?.case_id === item.case_id }">
            <td><strong>{{ item.case_id }}</strong></td>
            <td>{{ item.target_name }} ({{ item.outcome_window }})</td>
            <td>{{ item.deadline }}</td>
            <td>{{ item.current_age }}</td>

            <!-- Probability Column handling unsupported states -->
            <td>
              <span v-if="item.case_state === 'eligible' && item.score !== null">
                <strong>{{ (item.score * 100).toFixed(1) }}%</strong>
                <span class="muted font-xs"> ({{ item.probability_status }})</span>
              </span>
              <span v-else-if="item.case_state === 'already_overdue'" class="badge err">
                {{ t('predictiveRisk.alreadyOverdue', locale) }}
              </span>
              <span v-else-if="item.suitability_state === 'model_suspended'" class="badge warn">
                {{ t('predictiveRisk.modelSuspended', locale) }}
              </span>
              <span v-else class="badge secondary">
                {{ t('predictiveRisk.predictionUnavailable', locale) }}
              </span>
            </td>

            <!-- Threshold State -->
            <td>
              <span v-if="item.score !== null && item.score >= item.threshold" class="badge err">
                ABOVE THRESHOLD ({{ item.threshold.toFixed(2) }})
              </span>
              <span v-else-if="item.score !== null" class="badge ok">
                BELOW THRESHOLD ({{ item.threshold.toFixed(2) }})
              </span>
              <span v-else class="muted">—</span>
            </td>

            <td>v{{ item.model_version }} ({{ item.model_status }})</td>

            <!-- Suitability State -->
            <td>
              <span class="badge" :class="item.suitability_state === 'suitable' ? 'ok' : item.suitability_state === 'already_overdue' ? 'err' : 'warn'">
                {{ item.suitability_state }}
              </span>
            </td>

            <td>
              <button class="secondary btn-sm" @click="selectedItem = item">
                Details
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Prediction Detail Drawer / Modal -->
    <div v-if="selectedItem" class="card detail-drawer">
      <div class="row header-row">
        <h3>Prediction Detail: {{ selectedItem.case_id }}</h3>
        <button class="secondary btn-sm" @click="selectedItem = null">✕ Close</button>
      </div>

      <div class="grid cols-3 margin-v">
        <div class="stat">
          <span class="muted">Target / Deadline</span>
          <div><strong>{{ selectedItem.target_name }}</strong></div>
          <div class="muted font-xs">By: {{ selectedItem.deadline }}</div>
        </div>
        <div class="stat">
          <span class="muted">Probability Score</span>
          <div class="n" v-if="selectedItem.score !== null">
            {{ (selectedItem.score * 100).toFixed(1) }}%
          </div>
          <div class="n muted" v-else>N/A</div>
          <div class="muted font-xs">Status: {{ selectedItem.probability_status }}</div>
        </div>
        <div class="stat">
          <span class="muted">Model Governance</span>
          <div><strong>Model {{ selectedItem.model_id }} (v{{ selectedItem.model_version }})</strong></div>
          <div class="muted font-xs">State: {{ selectedItem.model_status }} | Freshness: {{ selectedItem.data_freshness }}</div>
        </div>
      </div>

      <div v-if="selectedItem.reason" class="card warn">
        <strong>State Reason:</strong> {{ selectedItem.reason }}
      </div>

      <!-- Non-causal factor contribution display -->
      <div v-if="selectedItem.factors && selectedItem.factors.length > 0" class="margin-v">
        <h4>{{ t('predictiveRisk.factorsHeader', locale) }}</h4>
        <ul class="factor-list">
          <li v-for="f in selectedItem.factors" :key="f.factor">
            <span class="factor-name">{{ f.factor }}</span>
            <span class="factor-impact">{{ f.impact }}</span>
          </li>
        </ul>
      </div>

      <div class="row margin-v">
        <button :disabled="launchingInv" @click="launchProactiveInvestigation(selectedItem)">
          {{ launchingInv ? t('common.loading', locale) : t('predictiveRisk.launchInvestigation', locale) }}
        </button>
        <span v-if="invResult" class="badge ok">
          Investigation Created: <strong>{{ invResult.id }}</strong>
          <NuxtLink :to="`/investigations?id=${invResult.id}`" class="linklike" style="margin-left: 6px;">View Workspace</NuxtLink>
        </span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.risk-page { display: flex; flex-direction: column; gap: 1rem; }
.font-xs { font-size: 0.75rem; }
.margin-v { margin: 1rem 0; }
.btn-sm { padding: 0.25rem 0.6rem; font-size: 0.85rem; }
tr.selected { background-color: #f0fdf4; }
.detail-drawer { border-left: 4px solid #0f766e; background: #f8fafc; }
.header-row { justify-content: space-between; align-items: center; }
.factor-list { list-style: none; padding: 0; margin: 0.5rem 0; }
.factor-list li { display: flex; justify-content: space-between; padding: 0.4rem 0.8rem; border-bottom: 1px solid #e2e8f0; font-size: 0.9rem; }
.factor-name { color: #334155; }
.factor-impact { font-weight: 600; color: #0f766e; }
</style>
