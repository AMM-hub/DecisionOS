import { ref } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { AiModelMapping, AiProvider } from '~/shared/types'
import SettingsAiPage from '~/pages/settings/ai.vue'

vi.mock('~/composables/locale', async () => {
  const { ref } = await import('vue')
  return {
    useLocale: () => ({
      locale: ref('en'),
      setLocale: vi.fn(),
      isRTL: ref(false),
    }),
    t: (key: string) => key,
    SUPPORTED_LOCALES: [],
  }
})

interface FetchCall {
  url: string
  init?: RequestInit
}

type Reply = { status?: number; body: unknown }

function installFetch(handler: (url: string, init?: RequestInit) => Reply) {
  const calls: FetchCall[] = []
  vi.stubGlobal('fetch', vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const url = String(input)
    calls.push({ url, init })
    const reply = handler(url, init)
    const status = reply.status ?? 200
    return {
      ok: status >= 200 && status < 300,
      status,
      text: async () => JSON.stringify(reply.body),
    }
  }))
  return calls
}

const provider: AiProvider = {
  id: 'p1',
  name: 'DeepSeek',
  kind: 'openai_compatible',
  base_url: 'https://api.deepseek.com/v1',
  models: ['deepseek-chat', 'deepseek-reasoner'],
  status: 'active',
  last_tested_at: '2026-10-20T10:00:00Z',
  last_error: null,
  key_suffix: '…02c5',
  key_fingerprint: 'abcdef',
  created_by: 'alpha.manager',
  created_at: '2026-10-20T09:00:00Z',
  updated_at: '2026-10-20T10:00:00Z',
}

const emptyRoles = {
  primary: null,
  fast: null,
  reasoning: null,
  coding: null,
  embedding: null,
  fallback: null,
}

function emptyMapping(): AiModelMapping {
  return { ...emptyRoles, roles: { ...emptyRoles } }
}

function mappingWithPrimary(): AiModelMapping {
  const primary = {
    provider_id: 'p1',
    provider_name: 'DeepSeek',
    provider_status: 'active',
    model_id: 'deepseek-chat',
  }
  return { ...emptyRoles, primary, roles: { ...emptyRoles, primary } }
}

function usageReport() {
  return {
    totals: {
      calls: 2,
      prompt_tokens: 100,
      completion_tokens: 40,
      cost_usd: null,
      latency_ms: 900,
    },
    by_provider: [],
    by_model: [
      {
        provider_id: 'p1',
        model_id: 'deepseek-chat',
        calls: 2,
        prompt_tokens: 100,
        completion_tokens: 40,
        cost_usd: null,
      },
    ],
    by_day: [
      { day: '2026-10-20', calls: 2, prompt_tokens: 100, completion_tokens: 40, cost_usd: null },
    ],
    by_provider_model_day: [],
  }
}

function zeroUsage() {
  return {
    totals: {
      calls: 0,
      prompt_tokens: 0,
      completion_tokens: 0,
      cost_usd: null,
      latency_ms: 0,
    },
    by_provider: [],
    by_model: [],
    by_day: [],
    by_provider_model_day: [],
  }
}

function mountPage() {
  return mount(SettingsAiPage, {
    global: {
      stubs: {
        NuxtLink: { props: ['to'], template: '<a :href="to"><slot /></a>' },
      },
    },
  })
}

beforeEach(() => {
  vi.stubGlobal('computed', (fn: () => unknown) => ref(fn()))
  vi.stubGlobal('useRuntimeConfig', () => ({ public: { apiBase: 'http://api.test/v1' } }))
  vi.stubGlobal('useState', <T,>(_key: string, init: () => T) => ref(init()))
  vi.stubGlobal('confirm', vi.fn(() => true))
})

describe('AI settings page', () => {
  it('renders the masked key suffix and never the raw key', async () => {
    installFetch((url) => {
      if (url.endsWith('/ai/providers')) return { body: [provider] }
      if (url.endsWith('/ai/models')) return { body: mappingWithPrimary() }
      if (url.endsWith('/ai/usage')) return { body: usageReport() }
      return { body: [] }
    })

    const wrapper = mountPage()
    await flushPromises()

    expect(wrapper.text()).toContain('…………02c5')
    expect(wrapper.text()).not.toContain('sk-raw-secret')
  })

  it('posts the add-provider payload with models as an array', async () => {
    const calls = installFetch((url, init) => {
      if (url.endsWith('/ai/providers') && init?.method === 'POST') {
        return { status: 201, body: provider }
      }
      if (url.endsWith('/ai/providers')) return { body: [provider] }
      if (url.endsWith('/ai/models')) return { body: emptyMapping() }
      if (url.endsWith('/ai/usage')) return { body: zeroUsage() }
      return { body: [] }
    })

    const wrapper = mountPage()
    await flushPromises()

    await wrapper.find('input[placeholder="aiSettings.namePlaceholder"]').setValue('DeepSeek')
    await wrapper.find('input[placeholder="aiSettings.baseUrlPlaceholder"]').setValue('https://api.deepseek.com/v1')
    await wrapper.find('input[type="password"]').setValue('sk-raw-secret')
    await wrapper.find('input[placeholder="aiSettings.modelsPlaceholder"]').setValue('deepseek-chat, deepseek-reasoner')
    await wrapper.find('form.provider-form').trigger('submit')
    await flushPromises()

    const postCall = calls.find(call => call.url.endsWith('/ai/providers') && call.init?.method === 'POST')
    expect(postCall).toBeTruthy()
    expect(JSON.parse(String(postCall?.init?.body))).toEqual({
      name: 'DeepSeek',
      base_url: 'https://api.deepseek.com/v1',
      api_key: 'sk-raw-secret',
      models: ['deepseek-chat', 'deepseek-reasoner'],
    })
  })

  it('shows the real provider test latency', async () => {
    installFetch((url, init) => {
      if (url.endsWith('/ai/providers/p1/test') && init?.method === 'POST') {
        return {
          body: { ok: true, latency_ms: 42, models_seen: ['deepseek-chat'], error: null },
        }
      }
      if (url.endsWith('/ai/providers')) return { body: [provider] }
      if (url.endsWith('/ai/models')) return { body: mappingWithPrimary() }
      if (url.endsWith('/ai/usage')) return { body: usageReport() }
      return { body: [] }
    })

    const wrapper = mountPage()
    await flushPromises()

    const testButton = wrapper.findAll('button').find(button => button.text() === 'aiSettings.test')
    expect(testButton).toBeTruthy()
    await testButton?.trigger('click')
    await flushPromises()

    const result = wrapper.find('.test-result')
    expect(result.text()).toContain('aiSettings.testOk')
    expect(result.text()).toContain('42')
  })

  it('saves a role with the documented PUT body', async () => {
    const calls = installFetch((url, init) => {
      if (url.endsWith('/ai/models') && init?.method === 'PUT') {
        return { body: mappingWithPrimary() }
      }
      if (url.endsWith('/ai/providers')) return { body: [provider] }
      if (url.endsWith('/ai/models')) return { body: emptyMapping() }
      if (url.endsWith('/ai/usage')) return { body: usageReport() }
      return { body: [] }
    })

    const wrapper = mountPage()
    await flushPromises()

    await wrapper.find('select').setValue('p1')
    await wrapper.find('input[placeholder="aiSettings.modelIdPlaceholder"]').setValue('deepseek-chat')
    const saveButton = wrapper.findAll('button').filter(button => button.text() === 'common.save')[0]
    expect(saveButton).toBeTruthy()
    await saveButton?.trigger('click')
    await flushPromises()

    const putCall = calls.find(call => call.url.endsWith('/ai/models') && call.init?.method === 'PUT')
    expect(putCall).toBeTruthy()
    expect(JSON.parse(String(putCall?.init?.body))).toEqual({
      roles: { primary: { provider_id: 'p1', model_id: 'deepseek-chat' } },
    })
  })

  it('shows the zero-calls usage state instead of empty tables', async () => {
    installFetch((url) => {
      if (url.endsWith('/ai/providers')) return { body: [] }
      if (url.endsWith('/ai/models')) return { body: emptyMapping() }
      if (url.endsWith('/ai/usage')) return { body: zeroUsage() }
      return { body: [] }
    })

    const wrapper = mountPage()
    await flushPromises()

    expect(wrapper.text()).toContain('aiSettings.noUsage')
    expect(wrapper.text()).not.toContain('aiSettings.byModel')
  })
})
