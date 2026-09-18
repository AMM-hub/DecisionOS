<script setup lang="ts">
import type { ScenarioTemplate, ScenarioSolveResponse } from '~/shared/types'

const { get, post } = useApi()

const templates = ref<ScenarioTemplate[]>([])
const loading = ref(false)
const busy = ref(false)
const error = ref<string | null>(null)
const result = ref<ScenarioSolveResponse | null>(null)

const activeTemplate = ref('reallocate-capacity')

// JSON editor fields for the solver payload
const jsonInput = ref(`{
  "groups": ["G1", "G2"],
  "queues": ["Q1", "Q2"],
  "periods": [1, 2, 3],
  "segments": [1, 2],
  "eligibility": { "[\"G1\",\"Q1\"]": true, "[\"G2\",\"Q2\"]": true },
  "regular_hours": { "[\"G1\",1]": 160, "[\"G1\",2]": 160, "[\"G1\",3]": 160, "[\"G2\",1]": 160, "[\"G2\",2]": 160, "[\"G2\",3]": 160 },
  "overtime_cap": { "[\"G1\",1]": 40, "[\"G1\",2]": 40, "[\"G1\",3]": 40, "[\"G2\",1]": 40, "[\"G2\",2]": 40, "[\"G2\",3]": 40 },
  "arrivals": { "[\"Q1\",1]": 120, "[\"Q1\",2]": 120, "[\"Q1\",3]": 120, "[\"Q2\",1]": 120, "[\"Q2\",2]": 120, "[\"Q2\",3]": 120 },
  "opening_backlog": { "Q1": 30, "Q2": 20 },
  "backlog_penalty_weight": 1,
  "overtime_penalty_weight": 1,
  "timelimit": 30
}`)

async function loadTemplates() {
  loading.value = true
  try { templates.value = await get<ScenarioTemplate[]>('/scenarios/templates') }
  catch (e) { error.value = e instanceof Error ? e.message : String(e) }
  finally { loading.value = false }
}
onMounted(loadTemplates)

async function solve() {
  busy.value = true; error.value = null; result.value = null
  try {
    const payload = JSON.parse(jsonInput.value)
    payload.template = activeTemplate.value
    result.value = await post<ScenarioSolveResponse>('/scenarios/solve', payload)
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally { busy.value = false }
}

// Quick-fill helper: populate default segment/marginal/cost data
function fillDefaults() {
  try {
    const p = JSON.parse(jsonInput.value)
    const groups: string[] = p.groups ?? ['G1', 'G2']
    const queues: string[] = p.queues ?? ['Q1', 'Q2']
    const periods: number[] = p.periods ?? [1, 2, 3]
    const segments: number[] = p.segments ?? [1, 2]

    p.segment_width = p.segment_width ?? {}
    p.marginal_rate = p.marginal_rate ?? {}
    p.regular_cost = p.regular_cost ?? {}
    p.overtime_cost = p.overtime_cost ?? {}
    p.backlog_penalty = p.backlog_penalty ?? {}

    for (const g of groups) {
      for (const q of queues) {
        for (const t of periods) {
          for (const k of segments) {
            swk = JSON.stringify([g, q, k, t])
            mrk = JSON.stringify([g, q, k, t])
            p.segment_width[swk] = p.segment_width[swk] ?? (k === 1 ? 160 : 40)
            p.marginal_rate[mrk] = p.marginal_rate[mrk] ?? (k === 1 ? 2.0 : 1.5)
          }
        }
        for (const t of periods) {
          p.regular_cost[JSON.stringify([g, t])] = p.regular_cost[JSON.stringify([g, t])] ?? 0
          p.overtime_cost[JSON.stringify([g, t])] = p.overtime_cost[JSON.stringify([g, t])] ?? 30
        }
      }
    }
    for (const q of queues) {
      for (const t of periods) {
        p.backlog_penalty[JSON.stringify([q, t])] = p.backlog_penalty[JSON.stringify([q, t])] ?? 50
      }
    }
    jsonInput.value = JSON.stringify(p, null, 2)
  } catch { /* ignore parse errors during fill */ }
}

function statusBadge(s: string) {
  if (s === 'optimal') return 'ok'
  if (s === 'infeasible') return 'err'
  if (s === 'feasible_time_limited') return 'warn'
  return 'err'
}
</script>

<template>
  <section>
    <div class="row" style="justify-content: space-between">
      <h1>Scenario Studio</h1>
      <button class="secondary" :disabled="loading" @click="loadTemplates">{{ loading ? 'Loading…' : 'Refresh templates' }}</button>
    </div>
    <p class="muted">What-if analysis, optimisation, and sensitivity for capacity decisions (§17). Fill in the allocation inputs and run the solver.</p>

    <div v-if="error" class="card"><span class="badge err">{{ error }}</span></div>

    <!-- Template selector -->
    <div class="card">
      <label class="field">
        Scenario template
        <select v-model="activeTemplate">
          <option v-for="t in templates" :key="t.template_id" :value="t.template_id">
            {{ t.name }}
          </option>
        </select>
      </label>
      <p v-if="templates.find(t => t.template_id === activeTemplate)" class="muted">
        {{ templates.find(t => t.template_id === activeTemplate)?.description }}
      </p>
    </div>

    <!-- JSON editor -->
    <div class="card">
      <div class="row" style="justify-content: space-between">
        <label class="field" style="flex:1">
          Allocation Inputs <span class="muted">(JSON — see §17.3 formulation)</span>
          <textarea v-model="jsonInput" rows="20" style="font-family: monospace; font-size: 0.85rem; width: 100%; box-sizing: border-box" />
        </label>
      </div>
      <div class="row">
        <button class="secondary" @click="fillDefaults">Fill default segment/cost data</button>
        <button :disabled="busy" @click="solve">{{ busy ? 'Solving…' : 'Run solver' }}</button>
      </div>
    </div>

    <!-- Results -->
    <div v-if="result" class="card">
      <h2>Solver Result</h2>
      <div class="grid cols-4">
        <div class="stat">
          <div class="n"><span :class="['badge', statusBadge(result.status)]">{{ result.status }}</span></div>
          <span class="muted">Status</span>
        </div>
        <div class="stat">
          <div class="n">{{ result.objective != null ? result.objective.toFixed(2) : '—' }}</div>
          <span class="muted">Objective</span>
        </div>
        <div class="stat">
          <div class="n">{{ result.runtime.toFixed(3) }}s</div>
          <span class="muted">Runtime</span>
        </div>
        <div class="stat">
          <div class="n">{{ result.variable_count }}</div>
          <span class="muted">Variables</span>
        </div>
      </div>
      <div class="grid cols-3" style="margin-top: 0.5rem">
        <div>
          <span class="muted">Solver:</span> <code>{{ result.solver }} {{ result.solver_version }}</code>
        </div>
        <div v-if="result.bound != null">
          <span class="muted">Bound:</span> <code>{{ result.bound.toFixed(4) }}</code>
        </div>
        <div v-if="result.gap != null">
          <span class="muted">Gap:</span> <code>{{ (result.gap * 100).toFixed(2) }}%</code>
        </div>
      </div>
      <div v-if="result.infeasibility_report" style="margin-top: 0.5rem">
        <h3>Infeasibility Report</h3>
        <pre class="muted" style="white-space: pre-wrap">{{ JSON.stringify(result.infeasibility_report, null, 2) }}</pre>
      </div>
    </div>
  </section>
</template>

<script lang="ts">
// Fill-defaults helper uses a shared scope variable
let swk: string, mrk: string
</script>