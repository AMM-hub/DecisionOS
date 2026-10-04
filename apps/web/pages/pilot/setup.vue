<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useApi } from '~/composables/api'
import { useLocale, t } from '~/composables/locale'

const { get, post } = useApi()
const { locale } = useLocale()

interface SemanticMetric {
  id: string
  name: string
  kind: string
  unit: string
  description: string
  version: number
}

const loading = ref(true)
const bootstrapping = ref(false)
const bootstrapDone = ref(false)
const semanticPack = ref<SemanticMetric[]>([])
const activeStep = ref(1)

const pilotName = ref('Support SLA Pilot (Tier-2 Queue)')
const pilotDomain = ref('support_ticket_operations')
const pilotOwner = ref('ops.manager')
const datasetId = ref('ds-support-ops')

const resultPilot = ref<any>(null)
const validationRes = ref<any>(null)

async function loadSemanticPack() {
  loading.value = true
  try {
    const res = await get<{ semantic_pack: SemanticMetric[] }>('/v1/pilots/semantic-pack').catch(() => ({ semantic_pack: [] }))
    semanticPack.value = res.semantic_pack || []
  } finally {
    loading.value = false
  }
}

async function runBootstrap() {
  bootstrapping.value = true
  try {
    const res = await post<any>('/v1/pilots/bootstrap', {
      name: pilotName.value,
      domain: pilotDomain.value,
      owner: pilotOwner.value,
      dataset_id: datasetId.value,
      dataset_revision: 1
    })
    resultPilot.value = res
    bootstrapDone.value = true
    activeStep.value = 5

    // Run data validation
    if (res.pilot?.id) {
      validationRes.value = await post<any>(`/v1/pilots/${res.pilot.id}/validate-data`, {
        dataset_id: datasetId.value,
        dataset_revision: 1
      }).catch(() => ({ status: 'BLOCKED', reasons: ['Validation request failed'] }))
    }
  } catch (e: any) {
    alert(`Bootstrap failed: ${e.message || e}`)
  } finally {
    bootstrapping.value = false
  }
}

onMounted(() => {
  loadSemanticPack()
})
</script>

<template>
  <div class="pilot-setup-page">
    <h2>{{ t('pilotSetup.title', locale) }}</h2>
    <p class="muted">{{ t('pilotSetup.description', locale) }}</p>

    <!-- Step Progress Indicator -->
    <div class="card steps-bar margin-v">
      <div class="step" :class="{ active: activeStep === 1, done: activeStep > 1 }">
        {{ t('pilotSetup.contractStep', locale) }}
      </div>
      <div class="step" :class="{ active: activeStep === 2, done: activeStep > 2 }">
        {{ t('pilotSetup.dataStep', locale) }}
      </div>
      <div class="step" :class="{ active: activeStep === 3, done: activeStep > 3 }">
        {{ t('pilotSetup.semanticStep', locale) }}
      </div>
      <div class="step" :class="{ active: activeStep === 4, done: activeStep > 4 }">
        {{ t('pilotSetup.monitoringStep', locale) }}
      </div>
      <div class="step" :class="{ active: activeStep === 5, done: bootstrapDone }">
        {{ t('pilotSetup.summaryStep', locale) }}
      </div>
    </div>

    <!-- Main Wizard Card -->
    <div v-if="loading" class="card muted">
      {{ t('common.loading', locale) }}
    </div>

    <div v-else class="card">
      <div v-if="!bootstrapDone" class="setup-form">
        <h3>Step {{ activeStep }}: Pilot Configuration</h3>

        <div class="form-group margin-v">
          <label><strong>Pilot Name:</strong></label>
          <input v-model="pilotName" type="text" class="input" placeholder="e.g. Support SLA Pilot" />
        </div>

        <div class="form-group margin-v">
          <label><strong>Pilot Domain:</strong></label>
          <select v-model="pilotDomain" class="input">
            <option value="support_ticket_operations">Support Ticket SLA & Queue Operations</option>
            <option value="fintech_kyc_operations">KYC & Application Queue Operations</option>
            <option value="healthcare_discharge_operations">Hospital Bed Allocation Operations</option>
          </select>
        </div>

        <div class="form-group margin-v">
          <label><strong>Owner:</strong></label>
          <input v-model="pilotOwner" type="text" class="input" />
        </div>

        <div class="form-group margin-v">
          <label><strong>Target Dataset ID:</strong></label>
          <input v-model="datasetId" type="text" class="input" />
        </div>

        <!-- Semantic Pack Preview -->
        <div class="margin-v">
          <h4>Standard Support Operations Semantic Pack (Included)</h4>
          <ul class="semantic-list">
            <li v-for="m in semanticPack" :key="m.id">
              <strong>{{ m.name }}</strong> ({{ m.kind }}) — <span class="muted">{{ m.description }}</span>
            </li>
          </ul>
        </div>

        <div class="margin-v">
          <button class="primary" :disabled="bootstrapping" @click="runBootstrap">
            {{ bootstrapping ? t('common.loading', locale) : t('pilotSetup.bootstrapButton', locale) }}
          </button>
        </div>
      </div>

      <!-- Bootstrap Complete View -->
      <div v-else class="bootstrap-complete">
        <div class="badge ok margin-v">
          ✓ {{ t('pilotSetup.bootstrappedSuccess', locale) }}
        </div>

        <h3>Pilot Contract: {{ resultPilot?.pilot?.id }}</h3>
        <p><strong>Status:</strong> <span class="badge ok">{{ resultPilot?.pilot?.status }}</span></p>
        <p><strong>Security Gate:</strong> <span class="badge warn">INTERNAL EVALUATION ONLY</span></p>

        <!-- Data Validation Result -->
        <div v-if="validationRes" class="margin-v card" :class="validationRes.status === 'PASS' ? 'ok-border' : 'warn-border'">
          <h4>Data Readiness Quality Gate</h4>
          <p><strong>Status:</strong> <span class="badge" :class="validationRes.status === 'PASS' ? 'ok' : 'warn'">{{ validationRes.status }}</span></p>

          <div v-if="validationRes.warnings && validationRes.warnings.length > 0">
            <strong>Warnings / Caveats:</strong>
            <ul>
              <li v-for="(w, idx) in validationRes.warnings" :key="idx">{{ w }}</li>
            </ul>
          </div>
        </div>

        <div class="row margin-v">
          <NuxtLink to="/pilot" class="button primary">
            Go to Executive Pilot Center →
          </NuxtLink>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.pilot-setup-page { display: flex; flex-direction: column; gap: 1rem; }
.steps-bar { display: flex; justify-content: space-between; gap: 0.5rem; }
.step { flex: 1; padding: 0.6rem; text-align: center; border-radius: 4px; background: #f1f5f9; font-size: 0.85rem; font-weight: 500; color: #64748b; }
.step.active { background: #0f766e; color: #ffffff; }
.step.done { background: #e0f2fe; color: #0369a1; }
.margin-v { margin: 1rem 0; }
.input { width: 100%; max-width: 400px; padding: 0.4rem; font-size: 0.9rem; border: 1px solid #cbd5e1; border-radius: 4px; }
.semantic-list { list-style: none; padding: 0; margin: 0.5rem 0; }
.semantic-list li { padding: 0.4rem 0; border-bottom: 1px solid #e2e8f0; font-size: 0.9rem; }
.ok-border { border-left: 4px solid #16a34a; }
.warn-border { border-left: 4px solid #d97706; }
</style>
