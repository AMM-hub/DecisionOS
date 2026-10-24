import { ref } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import RiskPage from '~/pages/risk.vue'
import IndexPage from '~/pages/index.vue'

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

beforeEach(() => {
  vi.stubGlobal('computed', (fn: () => unknown) => ref(fn()))
  vi.stubGlobal('useRuntimeConfig', () => ({ public: { apiBase: 'http://api.test/v1' } }))
  vi.stubGlobal('useState', <T,>(_key: string, init: () => T) => ref(init()))
  vi.stubGlobal('useI18n', () => ({ t: (key: string) => key, locale: ref('en') }))
  vi.stubGlobal('$fetch', vi.fn(async () => []))
})

describe('overview page', () => {
  it('renders the empty state and no raw i18n keys', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      const body = String(url).includes('/monitoring/episodes') ? { episodes: [] } : []
      return { ok: true, text: async () => JSON.stringify(body) }
    }))

    const wrapper = mount(IndexPage, {
      global: {
        stubs: {
          NuxtLink: { template: '<a><slot /></a>' },
        },
      },
    })

    await flushPromises()

    expect(wrapper.text()).toContain('No data yet')
    const html = wrapper.html()
    expect(html).not.toMatch(/common\.[a-zA-Z]/)
    expect(html).not.toMatch(/nav\.[a-zA-Z]/)
    expect(html).not.toMatch(/NAV\.[A-Z]/)
  })
})

describe('risk page', () => {
  it('renders the empty state when the queue has no cases', async () => {
    const wrapper = mount(RiskPage, {
      global: {
        stubs: {
          NuxtLink: { template: '<a><slot /></a>' },
        },
      },
    })

    await flushPromises()

    expect(wrapper.text()).toContain('No cases scored yet')
    expect(wrapper.text()).not.toMatch(/CASE-80\d\d/)
  })
})
