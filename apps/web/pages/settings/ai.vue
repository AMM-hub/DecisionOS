<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import type {
  AiModelMapping,
  AiModelRole,
  AiProvider,
  AiUsageReport,
} from '~/shared/types'
import { ApiError, useApi } from '~/composables/api'
import { t, useLocale } from '~/composables/locale'
import { formatDateTime, num } from '~/composables/format'
import PageHeader from '~/components/PageHeader.vue'
import DcCard from '~/components/DcCard.vue'

interface ProviderTestResult {
  ok: boolean
  latency_ms: number
  models_seen: string[]
  error: string | null
}

interface RoleDraft {
  provider_id: string
  model_id: string
}

const MODEL_ROLES: AiModelRole[] = [
  'primary', 'fast', 'reasoning', 'coding', 'embedding', 'fallback',
]

const { get, post, call } = useApi()
const { locale } = useLocale()

const providers = ref<AiProvider[]>([])
const models = ref<AiModelMapping | null>(null)
const usage = ref<AiUsageReport | null>(null)

const loadingProviders = ref(false)
const loadingModels = ref(false)
const loadingUsage = ref(false)

const error = ref<{ code?: string; detail: string } | null>(null)
const notice = ref<string | null>(null)

const form = reactive({ name: '', base_url: '', api_key: '', models: '' })
const fieldErrors = reactive<Record<string, string>>({
  name: '',
  base_url: '',
  api_key: '',
  models: '',
})
const savingProvider = ref(false)

const testResults = ref<Record<string, ProviderTestResult>>({})
const testingId = ref<string | null>(null)

const rotatingId = ref<string | null>(null)
const rotateKey = ref('')
const rotateSaving = ref(false)

const roleDraft = reactive<Record<AiModelRole, RoleDraft>>({
  primary: { provider_id: '', model_id: '' },
  fast: { provider_id: '', model_id: '' },
  reasoning: { provider_id: '', model_id: '' },
  coding: { provider_id: '', model_id: '' },
  embedding: { provider_id: '', model_id: '' },
  fallback: { provider_id: '', model_id: '' },
})
const roleSaving = ref<AiModelRole | null>(null)

const emptyUsage = (): AiUsageReport => ({
  totals: { calls: 0, prompt_tokens: 0, completion_tokens: 0, cost_usd: null, latency_ms: 0 },
  by_provider: [],
  by_model: [],
  by_day: [],
  by_provider_model_day: [],
})
const usageData = computed(() => usage.value ?? emptyUsage())
const hasUsage = computed(() => (usage.value?.totals.calls ?? 0) > 0)
const setRolesCount = computed(() => MODEL_ROLES.filter(role => roleIsSet(role)).length)

function setError(e: unknown) {
  if (e instanceof ApiError) {
    const detail = typeof e.detail === 'string' ? e.detail : e.message
    error.value = { code: e.code, detail }
  } else if (e instanceof Error) {
    error.value = { detail: e.message }
  } else {
    error.value = { detail: String(e) }
  }
}

function maskedKey(suffix: string): string {
  const tail = (suffix ?? '').replace(/^…+/, '').replace(/^\.+/, '')
  return `…………${tail}`
}

function money(value: number | null | undefined): string {
  return value == null ? '—' : num(value, 4)
}

function roleMapping(role: AiModelRole) {
  if (!models.value) return null
  return models.value.roles?.[role] ?? models.value[role] ?? null
}

function roleIsSet(role: AiModelRole): boolean {
  return roleMapping(role) !== null
}

function statusLabel(provider: AiProvider): string {
  return provider.status === 'active'
    ? t('aiSettings.statusActive', locale.value)
    : t('aiSettings.statusError', locale.value)
}

async function loadProviders() {
  loadingProviders.value = true
  try {
    providers.value = await get<AiProvider[]>('/ai/providers')
  } catch (e) {
    setError(e)
  } finally {
    loadingProviders.value = false
  }
}

async function loadModels() {
  loadingModels.value = true
  try {
    const mapping = await get<AiModelMapping>('/ai/models')
    models.value = mapping
    for (const role of MODEL_ROLES) {
      const current = mapping.roles?.[role] ?? mapping[role] ?? null
      roleDraft[role].provider_id = current?.provider_id ?? ''
      roleDraft[role].model_id = current?.model_id ?? ''
    }
  } catch (e) {
    setError(e)
  } finally {
    loadingModels.value = false
  }
}

async function loadUsage() {
  loadingUsage.value = true
  try {
    usage.value = await get<AiUsageReport>('/ai/usage')
  } catch (e) {
    setError(e)
  } finally {
    loadingUsage.value = false
  }
}

onMounted(() => {
  void Promise.all([loadProviders(), loadModels(), loadUsage()])
})

function clearFieldErrors() {
  fieldErrors.name = ''
  fieldErrors.base_url = ''
  fieldErrors.api_key = ''
  fieldErrors.models = ''
}

function applyFieldError(detail: unknown) {
  const text = typeof detail === 'string' ? detail : JSON.stringify(detail)
  const lower = text.toLowerCase()
  if (lower.includes("'name'")) fieldErrors.name = text
  else if (lower.includes("'base_url'")) fieldErrors.base_url = text
  else if (lower.includes("'api_key'")) fieldErrors.api_key = text
  else if (lower.includes("'models'")) fieldErrors.models = text
}

function resetForm() {
  form.name = ''
  form.base_url = ''
  form.api_key = ''
  form.models = ''
}

async function submitProvider() {
  if (savingProvider.value) return
  clearFieldErrors()
  error.value = null
  notice.value = null
  savingProvider.value = true
  try {
    await post<AiProvider>('/ai/providers', {
      name: form.name.trim(),
      base_url: form.base_url.trim(),
      api_key: form.api_key,
      models: form.models.split(',').map(item => item.trim()).filter(Boolean),
    })
    resetForm()
    notice.value = t('aiSettings.providerCreated', locale.value)
    await Promise.all([loadProviders(), loadModels()])
  } catch (e) {
    setError(e)
    if (e instanceof ApiError && e.status === 422) applyFieldError(e.detail)
  } finally {
    savingProvider.value = false
  }
}

async function testProvider(provider: AiProvider) {
  if (testingId.value) return
  testingId.value = provider.id
  error.value = null
  notice.value = null
  try {
    const result = await post<ProviderTestResult>(`/ai/providers/${provider.id}/test`)
    testResults.value = { ...testResults.value, [provider.id]: result }
    await loadProviders()
  } catch (e) {
    setError(e)
  } finally {
    testingId.value = null
  }
}

function startRotate(provider: AiProvider) {
  rotatingId.value = provider.id
  rotateKey.value = ''
  error.value = null
  notice.value = null
}

function cancelRotate() {
  rotatingId.value = null
  rotateKey.value = ''
}

async function saveRotate(provider: AiProvider) {
  const apiKey = rotateKey.value.trim()
  if (!apiKey || rotateSaving.value) return
  rotateSaving.value = true
  error.value = null
  notice.value = null
  try {
    await call<AiProvider>(`/ai/providers/${provider.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ api_key: apiKey }),
    })
    rotatingId.value = null
    rotateKey.value = ''
    notice.value = t('aiSettings.keyRotated', locale.value)
    await loadProviders()
  } catch (e) {
    setError(e)
  } finally {
    rotateSaving.value = false
  }
}

async function deleteProvider(provider: AiProvider) {
  if (!window.confirm(t('aiSettings.deleteConfirm', locale.value))) return
  error.value = null
  notice.value = null
  try {
    await call<{ deleted: boolean; id: string }>(`/ai/providers/${provider.id}`, {
      method: 'DELETE',
    })
    if (rotatingId.value === provider.id) cancelRotate()
    notice.value = t('aiSettings.providerDeleted', locale.value)
    await Promise.all([loadProviders(), loadModels()])
  } catch (e) {
    setError(e)
  }
}

async function saveRole(role: AiModelRole) {
  const draft = roleDraft[role]
  if (!draft.provider_id || !draft.model_id.trim()) {
    if (role === 'primary') {
      error.value = {
        code: 'missing_field',
        detail: t('aiSettings.primaryRequiredError', locale.value),
      }
    }
    return
  }
  if (roleSaving.value) return
  roleSaving.value = role
  error.value = null
  notice.value = null
  try {
    const mapping = await call<AiModelMapping>('/ai/models', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        roles: {
          [role]: {
            provider_id: draft.provider_id,
            model_id: draft.model_id.trim(),
          },
        },
      }),
    })
    models.value = mapping
    const saved = mapping.roles?.[role] ?? mapping[role] ?? null
    if (saved) {
      roleDraft[role].provider_id = saved.provider_id
      roleDraft[role].model_id = saved.model_id
    }
    notice.value = t('aiSettings.roleSaved', locale.value)
  } catch (e) {
    setError(e)
  } finally {
    roleSaving.value = null
  }
}
</script>

<template>
  <section>
    <PageHeader
      :title="t('aiSettings.title', locale)"
      :subtitle="t('aiSettings.subtitle', locale)"
    />

    <div v-if="error" class="banner error-banner-row" data-tone="warn" role="alert">
      <span class="badge err">{{ error.code ?? t('common.error', locale) }}</span>
      <span>{{ error.detail }}</span>
      <button class="btn-ghost btn-xs" type="button" @click="error = null">
        {{ t('common.close', locale) }}
      </button>
    </div>

    <div v-if="notice" class="banner notice-row" role="status">
      <span class="badge ok">{{ t('aiSettings.ok', locale) }}</span>
      <span>{{ notice }}</span>
    </div>

    <DcCard :title="t('aiSettings.providers', locale)">
      <template #actions>
        <span class="badge plain">{{ providers.length }}</span>
      </template>

      <p class="muted panel-note">{{ t('aiSettings.providersHelp', locale) }}</p>

      <div v-if="loadingProviders" class="skeleton-stack" aria-hidden="true">
        <span></span><span></span><span></span>
      </div>

      <div v-else-if="!providers.length" class="empty providers-empty">
        <h3>{{ t('aiSettings.noProviders', locale) }}</h3>
        <p class="muted">{{ t('aiSettings.noProvidersHelp', locale) }}</p>
      </div>

      <div v-else class="table-scroll">
        <table class="dt providers-table">
          <thead>
            <tr>
              <th>{{ t('aiSettings.name', locale) }}</th>
              <th>{{ t('aiSettings.baseUrl', locale) }}</th>
              <th>{{ t('aiSettings.models', locale) }}</th>
              <th>{{ t('common.status', locale) }}</th>
              <th>{{ t('aiSettings.key', locale) }}</th>
              <th>{{ t('common.actions', locale) }}</th>
            </tr>
          </thead>
          <tbody>
            <template v-for="provider in providers" :key="provider.id">
              <tr>
                <td>
                  <div class="cell-stack">
                    <span class="cell-strong">{{ provider.name }}</span>
                    <span class="muted mono provider-sub">
                      {{ provider.kind }} · {{ provider.id }}
                    </span>
                  </div>
                </td>
                <td><code class="base-url" :title="provider.base_url">{{ provider.base_url }}</code></td>
                <td>
                  <div class="row model-chips">
                    <span v-for="model in provider.models" :key="model" class="chip plain">{{ model }}</span>
                    <span v-if="!provider.models.length" class="muted">—</span>
                  </div>
                </td>
                <td>
                  <div class="cell-stack">
                    <span class="badge" :class="provider.status === 'active' ? 'ok' : 'err'">
                      {{ statusLabel(provider) }}
                    </span>
                    <span class="muted tested-at">
                      {{ formatDateTime(provider.last_tested_at, locale) }}
                    </span>
                  </div>
                </td>
                <td><code class="mono key-suffix" :title="provider.key_suffix">{{ maskedKey(provider.key_suffix) }}</code></td>
                <td>
                  <div class="row provider-actions">
                    <button
                      class="btn-secondary btn-xs"
                      type="button"
                      :disabled="testingId === provider.id"
                      @click="testProvider(provider)"
                    >
                      {{ testingId === provider.id ? t('aiSettings.testing', locale) : t('aiSettings.test', locale) }}
                    </button>
                    <button class="btn-secondary btn-xs" type="button" @click="startRotate(provider)">
                      {{ t('aiSettings.rotateKey', locale) }}
                    </button>
                    <button class="btn-danger btn-xs" type="button" @click="deleteProvider(provider)">
                      {{ t('common.delete', locale) }}
                    </button>
                  </div>
                </td>
              </tr>
              <tr v-if="provider.last_error || testResults[provider.id]" class="detail-row">
                <td colspan="6">
                  <div v-if="testResults[provider.id]" class="test-result">
                    <span class="badge" :class="testResults[provider.id]?.ok ? 'ok' : 'err'">
                      {{ testResults[provider.id]?.ok ? t('aiSettings.testOk', locale) : t('aiSettings.testFailed', locale) }}
                    </span>
                    <span v-if="testResults[provider.id]?.ok" class="mono">
                      {{ num(testResults[provider.id]?.latency_ms) }} {{ t('aiSettings.milliseconds', locale) }}
                    </span>
                    <span v-else-if="testResults[provider.id]?.error" class="muted">
                      {{ testResults[provider.id]?.error }}
                    </span>
                  </div>
                  <div v-if="provider.last_error" class="last-error">
                    <span class="trace-k">{{ t('aiSettings.lastError', locale) }}</span>
                    <span class="mono">{{ provider.last_error }}</span>
                  </div>
                </td>
              </tr>
              <tr v-if="rotatingId === provider.id" class="detail-row">
                <td colspan="6">
                  <form class="rotate-form" @submit.prevent="saveRotate(provider)">
                    <p class="rotate-warn">{{ t('aiSettings.rotateWarning', locale) }}</p>
                    <label class="field rotate-field">
                      <span>{{ t('aiSettings.newApiKey', locale) }}</span>
                      <input v-model="rotateKey" type="password" autocomplete="new-password" />
                    </label>
                    <button
                      class="btn-primary btn-sm"
                      type="submit"
                      :disabled="rotateSaving || !rotateKey.trim()"
                    >
                      {{ rotateSaving ? t('aiSettings.rotating', locale) : t('aiSettings.rotate', locale) }}
                    </button>
                    <button class="btn-ghost btn-sm" type="button" @click="cancelRotate">
                      {{ t('common.cancel', locale) }}
                    </button>
                  </form>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>

      <form class="provider-form" @submit.prevent="submitProvider">
        <h3 class="form-title">{{ t('aiSettings.addProviderTitle', locale) }}</h3>
        <div class="form-grid">
          <label class="field">
            <span>{{ t('aiSettings.name', locale) }}</span>
            <input v-model="form.name" type="text" :placeholder="t('aiSettings.namePlaceholder', locale)" />
            <span v-if="fieldErrors.name" class="field-error" role="alert">{{ fieldErrors.name }}</span>
          </label>
          <label class="field">
            <span>{{ t('aiSettings.baseUrl', locale) }}</span>
            <input
              v-model="form.base_url"
              type="url"
              :placeholder="t('aiSettings.baseUrlPlaceholder', locale)"
              autocomplete="url"
            />
            <span class="field-help">{{ t('aiSettings.baseUrlHelp', locale) }}</span>
            <span v-if="fieldErrors.base_url" class="field-error" role="alert">{{ fieldErrors.base_url }}</span>
          </label>
          <label class="field">
            <span>{{ t('aiSettings.apiKey', locale) }}</span>
            <input
              v-model="form.api_key"
              type="password"
              :placeholder="t('aiSettings.apiKeyPlaceholder', locale)"
              autocomplete="new-password"
            />
            <span class="field-help">{{ t('aiSettings.apiKeyHelp', locale) }}</span>
            <span v-if="fieldErrors.api_key" class="field-error" role="alert">{{ fieldErrors.api_key }}</span>
          </label>
          <label class="field">
            <span>{{ t('aiSettings.models', locale) }}</span>
            <input v-model="form.models" type="text" :placeholder="t('aiSettings.modelsPlaceholder', locale)" />
            <span class="field-help">{{ t('aiSettings.modelsHelp', locale) }}</span>
            <span v-if="fieldErrors.models" class="field-error" role="alert">{{ fieldErrors.models }}</span>
          </label>
        </div>
        <div class="row">
          <button class="btn-primary" type="submit" :disabled="savingProvider">
            {{ savingProvider ? t('aiSettings.creating', locale) : t('aiSettings.addProvider', locale) }}
          </button>
        </div>
      </form>
    </DcCard>

    <DcCard :title="t('aiSettings.rolesTitle', locale)">
      <template #actions>
        <span class="badge plain">{{ setRolesCount }} / {{ MODEL_ROLES.length }}</span>
      </template>

      <p class="muted panel-note">{{ t('aiSettings.rolesHelp', locale) }}</p>

      <div v-if="loadingModels" class="skeleton-stack" aria-hidden="true">
        <span></span><span></span><span></span>
      </div>

      <template v-else>
        <div v-if="!providers.length" class="banner role-banner" data-tone="warn">
          <svg aria-hidden="true"><use href="#i-alert" /></svg>
          <span>{{ t('aiSettings.noProvidersForRole', locale) }}</span>
        </div>

        <div class="role-list">
          <div v-for="role in MODEL_ROLES" :key="role" class="role-row">
            <div class="role-name">
              <div class="row">
                <span class="role-title">{{ t(`aiSettings.roles.${role}`, locale) }}</span>
                <span v-if="role === 'primary'" class="badge accent">
                  {{ t('aiSettings.primaryRequired', locale) }}
                </span>
                <span class="badge plain">
                  {{ roleIsSet(role) ? t('aiSettings.set', locale) : t('aiSettings.unset', locale) }}
                </span>
              </div>
              <span class="muted role-note">
                {{ role === 'primary' ? t('aiSettings.primaryUsedBy', locale) : '' }}
              </span>
            </div>
            <label class="field">
              <span>{{ t('aiSettings.provider', locale) }}</span>
              <select v-model="roleDraft[role].provider_id">
                <option value="">{{ t('aiSettings.providerPlaceholder', locale) }}</option>
                <option v-for="provider in providers" :key="provider.id" :value="provider.id">
                  {{ provider.name }}
                </option>
              </select>
            </label>
            <label class="field">
              <span>{{ t('aiSettings.modelId', locale) }}</span>
              <input
                v-model="roleDraft[role].model_id"
                type="text"
                :placeholder="t('aiSettings.modelIdPlaceholder', locale)"
              />
            </label>
            <button
              class="btn-secondary btn-sm role-save"
              type="button"
              :disabled="!roleDraft[role].provider_id || !roleDraft[role].model_id.trim() || roleSaving !== null"
              @click="saveRole(role)"
            >
              {{ roleSaving === role ? t('aiSettings.savingRole', locale) : t('common.save', locale) }}
            </button>
          </div>
        </div>
      </template>
    </DcCard>

    <DcCard :title="t('aiSettings.usage', locale)">
      <template #actions>
        <span class="badge plain">{{ t('aiSettings.usageHelp', locale) }}</span>
      </template>

      <div v-if="loadingUsage" class="skeleton-stack" aria-hidden="true">
        <span></span><span></span>
      </div>

      <div v-else-if="!hasUsage" class="empty usage-empty">
        <div class="e-ico">
          <svg aria-hidden="true"><use href="#i-pulse" /></svg>
        </div>
        <h3>{{ t('aiSettings.noUsage', locale) }}</h3>
        <p class="muted">{{ t('aiSettings.noUsageHelp', locale) }}</p>
      </div>

      <template v-else>
        <div class="kpi-band usage-kpis">
          <div class="kpi" data-tone="accent">
            <span class="k-label"><span class="mark" />{{ t('aiSettings.calls', locale) }}</span>
            <span class="k-val mono">{{ num(usageData.totals.calls) }}</span>
          </div>
          <div class="kpi">
            <span class="k-label"><span class="mark" />{{ t('aiSettings.promptTokens', locale) }}</span>
            <span class="k-val mono">{{ num(usageData.totals.prompt_tokens) }}</span>
          </div>
          <div class="kpi">
            <span class="k-label"><span class="mark" />{{ t('aiSettings.completionTokens', locale) }}</span>
            <span class="k-val mono">{{ num(usageData.totals.completion_tokens) }}</span>
          </div>
          <div class="kpi">
            <span class="k-label"><span class="mark" />{{ t('aiSettings.latencySum', locale) }}</span>
            <span class="k-val mono">
              {{ num(usageData.totals.latency_ms) }}
              <span class="unit">{{ t('aiSettings.milliseconds', locale) }}</span>
            </span>
          </div>
        </div>

        <h3 class="table-title">{{ t('aiSettings.byModel', locale) }}</h3>
        <div class="table-scroll">
          <table class="dt">
            <thead>
              <tr>
                <th>{{ t('aiSettings.model', locale) }}</th>
                <th>{{ t('aiSettings.calls', locale) }}</th>
                <th>{{ t('aiSettings.promptShort', locale) }}</th>
                <th>{{ t('aiSettings.completionShort', locale) }}</th>
                <th>{{ t('aiSettings.cost', locale) }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in usageData.by_model" :key="`${row.provider_id}-${row.model_id}`">
                <td>
                  <div class="cell-stack">
                    <span class="mono">{{ row.model_id }}</span>
                    <span class="muted mono">{{ row.provider_id }}</span>
                  </div>
                </td>
                <td class="num">{{ num(row.calls) }}</td>
                <td class="num">{{ num(row.prompt_tokens) }}</td>
                <td class="num">{{ num(row.completion_tokens) }}</td>
                <td class="num">{{ money(row.cost_usd) }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <h3 class="table-title">{{ t('aiSettings.byDay', locale) }}</h3>
        <div class="table-scroll">
          <table class="dt">
            <thead>
              <tr>
                <th>{{ t('aiSettings.day', locale) }}</th>
                <th>{{ t('aiSettings.calls', locale) }}</th>
                <th>{{ t('aiSettings.promptShort', locale) }}</th>
                <th>{{ t('aiSettings.completionShort', locale) }}</th>
                <th>{{ t('aiSettings.cost', locale) }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in usageData.by_day" :key="row.day">
                <td class="mono">{{ row.day }}</td>
                <td class="num">{{ num(row.calls) }}</td>
                <td class="num">{{ num(row.prompt_tokens) }}</td>
                <td class="num">{{ num(row.completion_tokens) }}</td>
                <td class="num">{{ money(row.cost_usd) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
    </DcCard>
  </section>
</template>

<style scoped>
.error-banner-row,
.notice-row {
  margin-bottom: 14px;
}
.error-banner-row > span:nth-child(2),
.notice-row > span:nth-child(2) {
  flex: 1;
  min-width: 0;
}
.panel-note {
  font-size: 11.5px;
  margin-bottom: 10px;
}
.providers-empty {
  padding: 20px 12px;
}
.base-url {
  font-size: 11.5px;
  display: inline-block;
  max-width: 190px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  vertical-align: bottom;
}
.provider-sub {
  display: block;
  font-size: 10.5px;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.providers-table {
  table-layout: fixed;
  width: 100%;
}
.providers-table th,
.providers-table td {
  overflow: hidden;
  text-overflow: ellipsis;
  vertical-align: top;
}
.providers-table th:nth-child(1) { width: 21%; }
.providers-table th:nth-child(2) { width: 22%; }
.providers-table th:nth-child(3) { width: 14%; }
.providers-table th:nth-child(4) { width: 14%; }
.providers-table th:nth-child(5) { width: 10%; }
.providers-table th:nth-child(6) { width: 19%; }
.tested-at {
  font-size: 10.5px;
  white-space: nowrap;
}
.provider-actions {
  flex-wrap: nowrap;
  gap: 4px;
}
.provider-actions .btn {
  flex: 0 0 auto;
}
.model-chips {
  gap: 4px;
  flex-wrap: nowrap;
}
.key-suffix {
  font-size: 11.5px;
  white-space: nowrap;
}
.detail-row td {
  background: var(--surface-2);
  padding-top: 7px;
  padding-bottom: 7px;
}
.test-result {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 11.5px;
}
.last-error {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 7px;
  font-size: 11.5px;
  color: var(--crit-ink);
  margin-top: 4px;
}
.trace-k {
  font-family: var(--font-mono);
  font-size: 9.5px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--faint);
}
.rotate-form {
  display: flex;
  align-items: flex-end;
  flex-wrap: wrap;
  gap: 9px;
}
.rotate-warn {
  flex: 1 1 100%;
  font-size: 11.5px;
  color: var(--warn-ink);
}
.rotate-field {
  margin-bottom: 0;
  flex: 1 1 240px;
}
.provider-form {
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px solid var(--border);
}
.form-title,
.table-title {
  font-size: 12px;
  font-weight: 650;
  letter-spacing: 0.03em;
  text-transform: uppercase;
  color: var(--muted);
  margin-bottom: 9px;
}
.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 14px;
}
.field-help {
  font-size: 10.5px;
  font-weight: 400;
  color: var(--faint);
  line-height: 1.4;
}
.field-error {
  font-size: 10.5px;
  font-weight: 500;
  color: var(--crit-ink);
}
.role-banner {
  margin-bottom: 12px;
}
.role-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.role-row {
  display: grid;
  grid-template-columns: minmax(150px, 0.9fr) minmax(140px, 0.8fr) minmax(160px, 1fr) auto;
  gap: 10px;
  align-items: end;
  padding: 9px 0;
  border-bottom: 1px solid var(--border);
}
.role-row:last-child {
  border-bottom: 0;
}
.role-name {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding-bottom: 6px;
  min-width: 0;
}
.role-title {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--fg-strong);
}
.role-note {
  font-size: 10.5px;
  min-height: 14px;
}
.role-row .field {
  margin-bottom: 0;
}
.role-save {
  margin-bottom: 1px;
}
.skeleton-stack {
  display: flex;
  flex-direction: column;
  gap: 9px;
  padding: 4px 0;
}
.skeleton-stack span {
  display: block;
  height: 13px;
  border-radius: var(--r-sm);
  background: linear-gradient(90deg, var(--surface-2), var(--surface-3), var(--surface-2));
  background-size: 200% 100%;
  animation: settings-shimmer 1.2s ease-in-out infinite;
}
.skeleton-stack span:nth-child(2n) {
  width: 72%;
}
.skeleton-stack span:nth-child(3n) {
  width: 84%;
}
@keyframes settings-shimmer {
  from { background-position: 200% 0; }
  to { background-position: -200% 0; }
}
.usage-empty {
  padding: 20px 12px;
}
.usage-kpis {
  margin-bottom: 16px;
}
.table-title {
  margin-top: 14px;
}
.table-title:first-of-type {
  margin-top: 0;
}
@media (max-width: 980px) {
  .role-row {
    grid-template-columns: 1fr 1fr;
  }
  .role-name {
    grid-column: 1 / -1;
    padding-bottom: 0;
  }
  .role-save {
    justify-self: start;
  }
}
@media (max-width: 820px) {
  .form-grid {
    grid-template-columns: 1fr;
  }
}
@media (max-width: 620px) {
  .role-row {
    grid-template-columns: 1fr;
  }
}
</style>
