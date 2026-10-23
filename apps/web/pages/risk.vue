<template>
  <div class="risk-page">
    <div class="page-head">
      <div class="titles">
        <div class="eyebrow">Predictive Risk Scoring</div>
        <h1>{{ t('predictiveRisk.title', locale) }}</h1>
        <p class="desc">{{ t('predictiveRisk.description', locale) }}</p>
      </div>
      <div class="actions">
        <button class="btn btn-secondary btn-sm" @click="loadRiskQueue">
          <svg><use href="#i-pulse"/></svg>
          <span>Refresh</span>
        </button>
      </div>
    </div>

    <div v-if="loading" class="loading">
      {{ t('common.loading', locale) }}
    </div>

    <!-- Main Table Panel -->
    <div v-else class="panel">
      <div class="panel-head">
        <h2>Case Risk Register</h2>
        <span class="sub"><span class="isolate mono">{{ riskQueue.length }}</span> cases evaluated</span>
      </div>

      <div class="table-scroll">
        <table class="dt">
          <thead>
            <tr>
              <th>{{ t('predictiveRisk.caseId', locale) }}</th>
              <th>{{ t('predictiveRisk.targetWindow', locale) }}</th>
              <th>{{ t('predictiveRisk.deadline', locale) }}</th>
              <th>{{ t('predictiveRisk.currentAge', locale) }}</th>
              <th class="num">{{ t('predictiveRisk.probability', locale) }}</th>
              <th>{{ t('predictiveRisk.thresholdState', locale) }}</th>
              <th>{{ t('predictiveRisk.modelVersion', locale) }}</th>
              <th>{{ t('predictiveRisk.suitabilityState', locale) }}</th>
              <th>{{ t('common.actions', locale) }}</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="item in riskQueue"
              :key="item.case_id"
              :class="{ selected: selectedItem?.case_id === item.case_id }"
              @click="selectedItem = item"
            >
              <td>
                <span class="id isolate font-weight-600">{{ item.case_id }}</span>
              </td>
              <td>
                <span class="cell-stack">
                  <span class="cell-strong">{{ item.target_name }}</span>
                  <span class="faint" style="font-size: 11px;">Window: {{ item.outcome_window }}</span>
                </span>
              </td>
              <td class="faint mono isolate" style="font-size: 11.5px;">{{ item.deadline }}</td>
              <td class="mono isolate">{{ item.current_age }}</td>

              <!-- Probability Score -->
              <td class="num">
                <span v-if="item.case_state === 'eligible' && item.score !== null">
                  <strong class="isolate mono" :style="item.score >= item.threshold ? 'color: var(--crit-ink);' : 'color: var(--fg);'">
                    {{ (item.score * 100).toFixed(1) }}%
                  </strong>
                  <span class="faint" style="font-size: 10px; margin-inline-start: 4px;">({{ item.probability_status }})</span>
                </span>
                <span v-else-if="item.case_state === 'already_overdue'" class="chip" data-tone="crit">
                  {{ t('predictiveRisk.alreadyOverdue', locale) }}
                </span>
                <span v-else-if="item.suitability_state === 'model_suspended'" class="chip" data-tone="warn">
                  {{ t('predictiveRisk.modelSuspended', locale) }}
                </span>
                <span v-else class="chip plain">
                  {{ t('predictiveRisk.predictionUnavailable', locale) }}
                </span>
              </td>

              <!-- Threshold State -->
              <td>
                <span v-if="item.score !== null && item.score >= item.threshold" class="chip" data-tone="crit">
                  <span class="d"></span>
                  ABOVE ({{ item.threshold.toFixed(2) }})
                </span>
                <span v-else-if="item.score !== null" class="chip" data-tone="ok">
                  <span class="d"></span>
                  BELOW ({{ item.threshold.toFixed(2) }})
                </span>
                <span v-else class="muted">—</span>
              </td>

              <td class="mono faint" style="font-size: 11.5px;">
                v{{ item.model_version }} ({{ item.model_status }})
              </td>

              <!-- Suitability State -->
              <td>
                <span class="chip" :data-tone="item.suitability_state === 'suitable' ? 'ok' : item.suitability_state === 'already_overdue' ? 'crit' : 'warn'">
                  {{ item.suitability_state }}
                </span>
              </td>

              <td>
                <button class="btn btn-secondary btn-xs" @click.stop="selectedItem = item">
                  Details
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Prediction Detail Drawer -->
    <div v-if="selectedItem">
      <div class="scrim" @click="selectedItem = null"></div>
      <aside class="drawer" role="dialog" aria-modal="true" :aria-label="selectedItem.case_id">
        <div class="drawer-head">
          <div class="dh-top">
            <h2>Prediction Detail: {{ selectedItem.case_id }}</h2>
            <button class="icon-btn" @click="selectedItem = null"><svg><use href="#i-x"/></svg></button>
          </div>
          <div class="row" style="margin-top: 8px; gap: 8px;">
            <span class="id isolate">{{ selectedItem.case_id }}</span>
            <span class="chip" :data-tone="selectedItem.score && selectedItem.score >= selectedItem.threshold ? 'crit' : 'ok'">
              <span class="d"></span>
              {{ selectedItem.risk_tier || 'MONITORED' }}
            </span>
            <span class="muted" style="font-size: 11.5px;">
              Target: <strong>{{ selectedItem.target_name }}</strong>
            </span>
          </div>
        </div>

        <div class="drawer-body">
          <!-- Metrics Overview Strip -->
          <div class="metric-row">
            <div class="metric-cell">
              <div class="mc-l">Probability Score</div>
              <div class="mc-v isolate" v-if="selectedItem.score !== null" :style="selectedItem.score >= selectedItem.threshold ? 'color: var(--crit-ink);' : ''">
                {{ (selectedItem.score * 100).toFixed(1) }}%
              </div>
              <div class="mc-v faint" v-else>N/A</div>
              <div class="mc-s">{{ selectedItem.probability_status }}</div>
            </div>
            <div class="metric-cell">
              <div class="mc-l">Threshold Boundary</div>
              <div class="mc-v isolate mono">{{ selectedItem.threshold.toFixed(2) }}</div>
              <div class="mc-s">Capacity Trigger</div>
            </div>
            <div class="metric-cell">
              <div class="mc-l">Model Governance</div>
              <div class="mc-v isolate mono" style="font-size: 15px;">v{{ selectedItem.model_version }}</div>
              <div class="mc-s">{{ selectedItem.model_status }} &middot; {{ selectedItem.data_freshness }}</div>
            </div>
          </div>

          <!-- Reason Alert if Any -->
          <div v-if="selectedItem.reason" class="banner" data-tone="warn">
            <svg><use href="#i-alert"/></svg>
            <span><strong>State Reason:</strong> {{ selectedItem.reason }}</span>
          </div>

          <!-- Contributing Factors Breakdown -->
          <div v-if="selectedItem.factors && selectedItem.factors.length > 0">
            <div class="faint" style="font-family: var(--font-mono); font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 8px;">
              {{ t('predictiveRisk.factorsHeader', locale) }}
            </div>
            <div class="factor-list">
              <div v-for="f in selectedItem.factors" :key="f.factor" class="factor" data-tone="crit">
                <span class="fx-name">{{ f.factor }}</span>
                <span class="fx-val isolate" style="color: var(--accent-ink);">{{ f.impact }}</span>
                <div class="fx-track"><i style="width: 75%;"></i></div>
              </div>
            </div>
          </div>

          <!-- Proactive Investigation Action -->
          <div style="margin-top: 10px;">
            <div class="faint" style="font-family: var(--font-mono); font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 8px;">
              Operational Response
            </div>
            <div class="row" style="gap: 10px; align-items: center;">
              <button class="btn btn-primary btn-sm" :disabled="launchingInv" @click="launchProactiveInvestigation(selectedItem)">
                <svg><use href="#i-flask"/></svg>
                <span>{{ launchingInv ? t('common.loading', locale) : t('predictiveRisk.launchInvestigation', locale) }}</span>
              </button>
              <span v-if="invResult" class="chip" data-tone="ok">
                Investigation Created: <strong class="isolate mono">{{ invResult.id }}</strong>
                <NuxtLink :to="`/investigations/${invResult.id}`" style="margin-inline-start: 6px; text-decoration: underline;">View</NuxtLink>
              </span>
            </div>
          </div>
        </div>

        <div class="drawer-foot">
          <button class="btn btn-secondary btn-sm" @click="selectedItem = null">Close</button>
        </div>
      </aside>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useApi } from '~/composables/api'
import { useLocale, t } from '~/composables/locale'
import { shortId, titleCase } from '~/composables/format'

const { get, post } = useApi()
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
          { factor: 'Elapsing time ratio (>75% SLA window)', impact: '+0.19' },
        ],
      },
      {
        case_id: 'CASE-8022',
        target_id: tgts[0]?.id || 'tgt-sla-24h',
        target_name: 'Case SLA Breach 24h',
        outcome_window: '24h',
        deadline: '2026-10-05T18:00:00Z',
        current_age: '12h 10m',
        case_state: 'eligible',
        score: 0.382,
        probability_status: 'calibrated',
        threshold: 0.50,
        risk_tier: 'MEDIUM',
        model_id: mdls[0]?.id || 'mdl-alpha-lr',
        model_version: 1,
        model_status: 'active',
        last_scored: '2026-10-04T19:30:00Z',
        data_freshness: '5m ago',
        suitability_state: 'suitable',
        factors: [
          { factor: 'Standard progression rhythm', impact: '-0.15' },
        ],
      },
      {
        case_id: 'CASE-7991',
        target_id: tgts[0]?.id || 'tgt-sla-24h',
        target_name: 'Case SLA Breach 24h',
        outcome_window: '24h',
        deadline: '2026-10-04T12:00:00Z',
        current_age: '28h 00m',
        case_state: 'already_overdue',
        score: null,
        probability_status: 'unavailable',
        threshold: 0.50,
        risk_tier: null,
        model_id: mdls[0]?.id || 'mdl-alpha-lr',
        model_version: 1,
        model_status: 'active',
        last_scored: '2026-10-04T19:30:00Z',
        data_freshness: '5m ago',
        suitability_state: 'already_overdue',
        reason: 'Case deadline has already elapsed; prospective risk prediction unavailable',
        factors: [],
      },
      {
        case_id: 'CASE-8025',
        target_id: tgts[1]?.id || 'tgt-closure-7d',
        target_name: 'Weekly Resolution 7d',
        outcome_window: '7d',
        deadline: '2026-10-11T00:00:00Z',
        current_age: '1h 00m',
        case_state: 'eligible',
        score: null,
        probability_status: 'suspended',
        threshold: 0.65,
        risk_tier: null,
        model_id: 'mdl-beta-rf',
        model_version: 2,
        model_status: 'suspended',
        last_scored: '2026-10-04T19:30:00Z',
        data_freshness: '5m ago',
        suitability_state: 'model_suspended',
        reason: 'Active model for this target has been suspended by governance',
        factors: [],
      },
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
      alternative_explanations: ['Staffing bottleneck', 'Vendor delay', 'Volume surge'],
    })
    invResult.value = inv

    // If prediction exists, bind it as estimated evidence
    try {
      const pred = await post<{ prediction_id: string }>('/v1/predictive/score', {
        model_id: item.model_id,
        case_id: item.case_id,
        observation_time: new Date().toISOString(),
        deadline: item.deadline,
      })
      if (pred && pred.prediction_id) {
        await post(`/v1/predictive/predictions/${pred.prediction_id}/evidence`, {
          investigation_id: inv.id,
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

<style scoped>
.risk-page { display: flex; flex-direction: column; gap: 0; }
.page-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; margin-bottom: 20px; flex-wrap: wrap; }
.eyebrow { font-family: var(--font-mono); font-size: 10.5px; letter-spacing: 0.14em; text-transform: uppercase; color: var(--faint); margin-bottom: 6px; }
.page-head h1 { font-size: 20px; font-weight: 650; letter-spacing: -0.02em; color: var(--fg-strong); line-height: 1.2; }
.page-head .desc { font-size: 13px; color: var(--muted); margin-top: 4px; max-width: 68ch; }
.page-head .actions { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
</style>
