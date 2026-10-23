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

      <div v-if="riskQueue.length === 0" class="empty" style="padding: 50px 20px;">
        <div class="e-ico">
          <svg><use href="#i-pulse"/></svg>
        </div>
        <h3>No cases scored yet</h3>
        <p class="muted">Run a predictive score against a target to populate the operational risk queue.</p>
        <NuxtLink to="/forecasts" class="btn btn-primary btn-sm" style="margin-top: 10px;">Go to Forecasts</NuxtLink>
      </div>

      <div v-else ref="tableScroll" class="table-scroll" :class="{ 'is-scrollable': isScrollable }">
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
              <td class="faint mono" style="font-size: 11.5px;"><span class="isolate">{{ formatDateTime(item.deadline, locale) }}</span></td>
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
import { ref, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useApi } from '~/composables/api'
import { useLocale, t } from '~/composables/locale'
import { formatDateTime } from '~/composables/format'

const { post } = useApi()
const { locale } = useLocale()

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
const riskQueue = ref<CaseRiskItem[]>([])
const selectedItem = ref<CaseRiskItem | null>(null)
const launchingInv = ref(false)
const invResult = ref<{ id: string } | null>(null)
const tableScroll = ref<HTMLElement | null>(null)
const isScrollable = ref(false)

async function loadRiskQueue() {
  loading.value = true
  try {
    riskQueue.value = []
  } finally {
    loading.value = false
  }
}

function updateScrollable() {
  const el = tableScroll.value
  if (!el) return
  isScrollable.value = el.scrollWidth > el.clientWidth
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

watch(riskQueue, async () => {
  await nextTick()
  updateScrollable()
})

onMounted(() => {
  loadRiskQueue()
  window.addEventListener('resize', updateScrollable)
})

onUnmounted(() => {
  window.removeEventListener('resize', updateScrollable)
})
</script>

<style scoped>
.risk-page { display: flex; flex-direction: column; gap: 0; }
.page-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; margin-bottom: 20px; flex-wrap: wrap; }
.eyebrow { font-family: var(--font-mono); font-size: 10.5px; letter-spacing: 0.14em; text-transform: uppercase; color: var(--faint); margin-bottom: 6px; }
.page-head h1 { font-size: 20px; font-weight: 650; letter-spacing: -0.02em; color: var(--fg-strong); line-height: 1.2; }
.page-head .desc { font-size: 13px; color: var(--muted); margin-top: 4px; max-width: 68ch; }
.page-head .actions { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }

.table-scroll { position: relative; }
.table-scroll.is-scrollable { box-shadow: inset -14px 0 14px -14px rgba(0, 0, 0, 0.3); }
:global(.rtl) .table-scroll.is-scrollable { box-shadow: inset 14px 0 14px -14px rgba(0, 0, 0, 0.3); }
.table-scroll thead th:first-child,
.table-scroll tbody td:first-child {
  position: sticky;
  inset-inline-start: 0;
  background: var(--surface);
  z-index: 3;
}
.table-scroll thead th:first-child { z-index: 4; }
</style>
