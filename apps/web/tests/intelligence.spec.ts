import { ref } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import IntelligencePage from '~/pages/intelligence.vue'

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

const emptyRoles = {
  primary: null,
  fast: null,
  reasoning: null,
  coding: null,
  embedding: null,
  fallback: null,
}

function mappingWithPrimary() {
  const primary = {
    provider_id: 'p1',
    provider_name: 'DeepSeek',
    provider_status: 'active',
    model_id: 'deepseek-chat',
  }
  return {
    ...emptyRoles,
    primary,
    roles: { ...emptyRoles, primary },
  }
}

function mappingWithoutPrimary() {
  return { ...emptyRoles, roles: { ...emptyRoles } }
}

function mountPage() {
  return mount(IntelligencePage, {
    global: {
      stubs: {
        NuxtLink: { props: ['to'], template: '<a :href="to"><slot /></a>' },
      },
    },
  })
}

function sendButton(wrapper: ReturnType<typeof mountPage>) {
  return wrapper.findAll('button').find(button => button.text().includes('intelligence.send'))
}

beforeEach(() => {
  vi.stubGlobal('computed', (fn: () => unknown) => ref(fn()))
  vi.stubGlobal('useRuntimeConfig', () => ({ public: { apiBase: 'http://api.test/v1' } }))
  vi.stubGlobal('useState', <T,>(_key: string, init: () => T) => ref(init()))
  vi.stubGlobal('confirm', vi.fn(() => true))
})

describe('intelligence page', () => {
  it('renders the no-model call to action linking to AI settings', async () => {
    installFetch((url) => {
      if (url.includes('/ai/conversations')) return { body: [] }
      if (url.includes('/ai/models')) return { body: mappingWithoutPrimary() }
      return { body: [] }
    })

    const wrapper = mountPage()
    await flushPromises()

    expect(wrapper.text()).toContain('intelligence.noModel')
    expect(wrapper.find('a[href="/settings/ai"]').exists()).toBe(true)
  })

  it('posts the message and renders the answer, evidence chip and tool trace count', async () => {
    const calls = installFetch((url, init) => {
      if (url.includes('/ai/conversations')) return { body: [] }
      if (url.includes('/ai/models')) return { body: mappingWithPrimary() }
      if (url.endsWith('/ai/chat') && init?.method === 'POST') {
        return {
          body: {
            answer: 'Counts by status:\n\n```\nopen 12\nclosed 4\n```',
            tool_calls: [
              {
                name: 'count_tickets_by_status',
                input: { status: 'open' },
                ok: true,
                evidence_ref: 'ev:tickets:1',
                refused: false,
                code: null,
                error: null,
              },
            ],
            usage: { prompt_tokens: 10, completion_tokens: 6, total_tokens: 16 },
            usage_events: [],
            latency_ms: 42,
            conversation_id: 'c1',
            message_id: 'm2',
            provider_id: 'p1',
            model_id: 'deepseek-chat',
          },
        }
      }
      return { body: [] }
    })

    const wrapper = mountPage()
    await flushPromises()

    await wrapper.find('textarea').setValue('How many tickets are open?')
    await sendButton(wrapper)?.trigger('click')
    await flushPromises()

    const chatCall = calls.find(call => call.url.endsWith('/ai/chat'))
    expect(chatCall).toBeTruthy()
    expect(JSON.parse(String(chatCall?.init?.body))).toEqual({ message: 'How many tickets are open?' })
    expect(wrapper.find('pre.msg-code').text()).toContain('open 12')
    expect(wrapper.text()).toContain('ev:tickets:1')
    expect(wrapper.find('summary').text()).toContain('1 intelligence.toolCallOne · 1 intelligence.evidenceRefOne')
  })

  it('renders the ungrounded-numbers warning banner', async () => {
    installFetch((url, init) => {
      if (url.includes('/ai/conversations')) return { body: [] }
      if (url.includes('/ai/models')) return { body: mappingWithPrimary() }
      if (url.endsWith('/ai/chat') && init?.method === 'POST') {
        return {
          body: {
            answer: 'There are 999 open tickets.',
            tool_calls: [],
            usage: { prompt_tokens: 8, completion_tokens: 4, total_tokens: 12 },
            usage_events: [],
            latency_ms: 20,
            conversation_id: 'c1',
            message_id: 'm2',
            provider_id: 'p1',
            model_id: 'deepseek-chat',
            warning: { ungrounded_numbers: ['999'] },
            ungrounded_numbers: ['999'],
          },
        }
      }
      return { body: [] }
    })

    const wrapper = mountPage()
    await flushPromises()

    await wrapper.find('textarea').setValue('How many tickets are open?')
    await sendButton(wrapper)?.trigger('click')
    await flushPromises()

    const banner = wrapper.find('.banner.ungrounded')
    expect(banner.exists()).toBe(true)
    expect(banner.text()).toContain('intelligence.ungroundedLead')
    expect(banner.text()).toContain('999')
  })

  it('keeps the composer text and shows the error code on a 409', async () => {
    installFetch((url, init) => {
      if (url.includes('/ai/conversations')) return { body: [] }
      if (url.includes('/ai/models')) return { body: mappingWithPrimary() }
      if (url.endsWith('/ai/chat') && init?.method === 'POST') {
        return {
          status: 409,
          body: {
            code: 'ai_model_not_configured',
            detail: 'No primary AI model is configured for this tenant.',
            status: 409,
          },
        }
      }
      return { body: [] }
    })

    const wrapper = mountPage()
    await flushPromises()

    await wrapper.find('textarea').setValue('Will this fail?')
    await sendButton(wrapper)?.trigger('click')
    await flushPromises()

    expect((wrapper.find('textarea').element as HTMLTextAreaElement).value).toBe('Will this fail?')
    expect(wrapper.text()).toContain('ai_model_not_configured')
    expect(wrapper.findAll('.msg').length).toBe(0)
  })

  it('renders conversation message counts and deletes after confirmation', async () => {
    const calls = installFetch((url, init) => {
      if (url.includes('/ai/conversations') && init?.method === 'DELETE') {
        return { body: { deleted: true, id: 'c1' } }
      }
      if (url.includes('/ai/conversations')) {
        return {
          body: [
            {
              id: 'c1',
              title: 'Ticket triage',
              created_by: 'alpha.manager',
              created_at: '2026-10-20T10:00:00Z',
              updated_at: '2026-10-20T10:05:00Z',
              archived: false,
              message_count: 5,
            },
          ],
        }
      }
      if (url.includes('/ai/models')) return { body: mappingWithPrimary() }
      return { body: [] }
    })

    const wrapper = mountPage()
    await flushPromises()

    expect(wrapper.text()).toContain('Ticket triage')
    expect(wrapper.find('.conv-meta').text()).toContain('5 intelligence.messageCount')

    const deleteButton = wrapper
      .findAll('button')
      .find(button => button.attributes('aria-label') === 'intelligence.deleteConversation')
    expect(deleteButton).toBeTruthy()
    await deleteButton?.trigger('click')
    await flushPromises()

    const deleteCall = calls.find(call => call.init?.method === 'DELETE')
    expect(deleteCall?.url).toBe('http://api.test/v1/ai/conversations/c1')
  })
})
