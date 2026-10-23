import { ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, useApi } from '~/composables/api'

function stubResponse(status: number, body: unknown) {
  const text = JSON.stringify(body)
  vi.stubGlobal('fetch', vi.fn(async () => ({
    ok: status >= 200 && status < 300,
    status,
    text: async () => text,
  })))
}

beforeEach(() => {
  vi.stubGlobal('computed', (fn: () => unknown) => ref(fn()))
  vi.stubGlobal('useRuntimeConfig', () => ({ public: { apiBase: 'http://api.test/v1' } }))
  vi.stubGlobal('useState', <T,>(_key: string, init: () => T) => ref(init()))
})

describe('ApiError mapping', () => {
  it('maps the flat {code, detail, status} contract', async () => {
    stubResponse(400, { code: 'grain_not_proven', detail: 'uniqueness failed', status: 400 })

    const promise = useApi().get('/datasets/1')
    await expect(promise).rejects.toBeInstanceOf(ApiError)
    await expect(promise).rejects.toMatchObject({
      code: 'grain_not_proven',
      status: 400,
      message: expect.stringContaining('Grain not proven'),
    })
  })

  it('parses the legacy nested-string detail envelope without throwing', async () => {
    stubResponse(422, { detail: '{"code":"x"}' })

    const promise = useApi().get('/datasets/1')
    await expect(promise).rejects.toBeInstanceOf(ApiError)
    await expect(promise).rejects.toMatchObject({
      code: 'x',
      status: 422,
      message: 'Rejected: x',
    })
  })
})
