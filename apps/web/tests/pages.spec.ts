import { ref } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import RiskPage from '~/pages/risk.vue'

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
