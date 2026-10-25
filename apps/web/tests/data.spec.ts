import { ref } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { DataSource, Dataset, IngestJob } from '~/shared/types'
import DataPage from '~/pages/data.vue'
import { useLocale } from '~/composables/locale'

interface FetchCall {
  url: string
  init?: RequestInit
}

type Reply = { status?: number; body: unknown }

let pollSettings = { dataPollIntervalMs: 1, dataPollBudgetMs: 500 }
let routeQuery: Record<string, string | string[]> = {}

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

async function waitFor(predicate: () => boolean, timeout = 3000) {
  const started = Date.now()
  while (Date.now() - started < timeout) {
    await flushPromises()
    if (predicate()) return
    await new Promise(resolve => setTimeout(resolve, 5))
  }
  throw new Error('condition not met before timeout')
}

const postgresSource: DataSource = {
  id: 'src-1',
  name: 'Support DB',
  kind: 'postgres',
  config: {
    host: 'db.internal',
    dbname: 'support',
    password: 'hunter2-secret',
  },
  read_only: true,
  status: 'connected',
  last_tested_at: '2026-10-20T10:00:00Z',
  last_error: null,
  has_secret: true,
  created_at: '2026-10-20T09:00:00Z',
  updated_at: '2026-10-20T10:00:00Z',
}

const restSource: DataSource = {
  id: 'src-2',
  name: 'CRM API',
  kind: 'rest',
  config: { base_url: 'https://api-user:pa55-word@api.example.com/records' },
  read_only: true,
  status: 'untested',
  last_tested_at: null,
  last_error: null,
  has_secret: true,
  created_at: '2026-10-20T09:00:00Z',
  updated_at: '2026-10-20T09:00:00Z',
}

const dataset: Dataset = {
  dataset_id: 'ds-1',
  name: 'Support tickets',
  revision: 3,
  latest_revision: 3,
  latest_revision_state: 'published',
  grain_confirmed: true,
  grain: ['ticket_id'],
  row_count: 240,
}

const job: IngestJob = {
  id: 'job-1',
  data_source_id: 'src-1',
  name: 'Support tickets ingest',
  target_table: 'public.tickets',
  mode: 'full',
  watermark_column: null,
  watermark_value: null,
  schedule_cron: null,
  max_rows: null,
  status: 'active',
  created_at: '2026-10-20T09:00:00Z',
  updated_at: '2026-10-20T09:00:00Z',
  latest_run: null,
}

function runFixture(overrides: Record<string, unknown> = {}) {
  return {
    id: 'run-1',
    job_id: 'job-1',
    status: 'queued',
    started_at: null,
    finished_at: null,
    rows_read: 0,
    rows_written: 0,
    dataset_id: null,
    upload_id: null,
    error: null,
    stats: {},
    created_at: '2026-10-20T09:05:00Z',
    ...overrides,
  }
}

function mountPage() {
  return mount(DataPage, {
    global: {
      stubs: {
        NuxtLink: { props: ['to'], template: '<a :href="to"><slot /></a>' },
      },
    },
  })
}

function baseHandler(url: string): Reply | null {
  if (url.endsWith('/connectors')) return { body: [postgresSource, restSource] }
  if (url.endsWith('/jobs')) return { body: [job] }
  if (url.endsWith('/datasets')) return { body: [dataset] }
  return null
}

beforeEach(() => {
  useLocale().setLocale('en')
  pollSettings = { dataPollIntervalMs: 1, dataPollBudgetMs: 500 }
  routeQuery = {}
  vi.stubGlobal('computed', (fn: () => unknown) => ref(fn()))
  vi.stubGlobal('useState', <T,>(_key: string, init: () => T) => ref(init()))
  vi.stubGlobal('useRuntimeConfig', () => ({
    public: { apiBase: 'http://api.test/v1', ...pollSettings },
  }))
  vi.stubGlobal('useRoute', () => ({ query: routeQuery }))
  vi.stubGlobal('confirm', vi.fn(() => true))
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('data workspace page', () => {
  it('renders redacted source targets and never leaks credentials', async () => {
    installFetch(url => baseHandler(url) ?? { body: [] })

    const wrapper = mountPage()
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('db.internal/support')
    expect(text).toContain('https://api.example.com/records')
    expect(text).not.toContain('hunter2-secret')
    expect(text).not.toContain('pa55-word')
    expect(text).not.toContain('api-user')
  })

  it('renders real test latency and the backend failure message', async () => {
    const broken: DataSource = {
      ...postgresSource,
      id: 'src-3',
      name: 'Broken DB',
      status: 'untested',
      last_tested_at: null,
    }
    installFetch((url, init) => {
      if (url.endsWith('/connectors/src-1/test') && init?.method === 'POST') {
        return { body: { status: 'connected', latency_ms: 42, server_version: 'PostgreSQL 16' } }
      }
      if (url.endsWith('/connectors/src-3/test') && init?.method === 'POST') {
        return {
          status: 422,
          body: { code: 'connector_error', detail: 'PostgreSQL connection test failed.' },
        }
      }
      if (url.endsWith('/connectors')) return { body: [postgresSource, broken] }
      if (url.endsWith('/jobs')) return { body: [job] }
      if (url.endsWith('/datasets')) return { body: [dataset] }
      return { body: [] }
    })

    const wrapper = mountPage()
    await flushPromises()

    const rows = wrapper.findAll('tr.source-row')
    const successRow = rows.find(row => row.text().includes('Support DB'))
    const failureRow = rows.find(row => row.text().includes('Broken DB'))
    expect(successRow).toBeTruthy()
    expect(failureRow).toBeTruthy()

    const successTest = successRow?.findAll('button').find(button => button.text() === 'Test')
    await successTest?.trigger('click')
    await waitFor(() => wrapper.find('.test-result').exists())

    const successText = wrapper
      .findAll('.test-result')
      .find(node => node.text().includes('connected'))
    expect(successText).toBeTruthy()
    expect(successText?.text().replace(/\s+/g, ' ')).toContain('connected · 42 ms')

    const failureTest = failureRow?.findAll('button').find(button => button.text() === 'Test')
    await failureTest?.trigger('click')
    await waitFor(() =>
      wrapper.findAll('.test-result').some(node => node.text().includes('test failed')),
    )

    const failureText = wrapper
      .findAll('.test-result')
      .map(node => node.text())
      .join(' ')
    expect(failureText).toContain('PostgreSQL connection test failed.')
  })

  it('renders exactly the returned preview rows and the truncated notice', async () => {
    installFetch((url) => {
      if (url.endsWith('/connectors/src-1/tables')) {
        return { body: [{ schema: 'public', name: 'tickets', kind: 'table' }] }
      }
      if (url.includes('/tables/public.tickets/preview')) {
        return {
          body: {
            connector_id: 'src-1',
            table: 'public.tickets',
            columns: ['ticket_id', 'subject'],
            rows: [
              [1, 'Printer down'],
              [2, 'VPN issue'],
            ],
            row_count: 2,
            limit: 50,
            truncated: true,
          },
        }
      }
      return baseHandler(url) ?? { body: [] }
    })

    const wrapper = mountPage()
    await flushPromises()

    const browseButton = wrapper.findAll('button').find(button => button.text() === 'Browse')
    await browseButton?.trigger('click')
    await flushPromises()

    const tableOption = wrapper.find('.table-option')
    expect(tableOption.exists()).toBe(true)
    await tableOption.trigger('click')
    await waitFor(() => wrapper.find('.preview-table').exists())

    const headers = wrapper.findAll('.preview-table thead th').map(th => th.text())
    expect(headers).toEqual(['ticket_id', 'subject'])
    const rows = wrapper.findAll('.preview-table tbody tr')
    expect(rows).toHaveLength(2)
    expect(rows[0].text()).toContain('Printer down')
    expect(rows[1].text()).toContain('VPN issue')
    expect(wrapper.find('.truncated-notice').exists()).toBe(true)
  })

  it('poll queued to succeeded and renders the real rows written', async () => {
    pollSettings = { dataPollIntervalMs: 1, dataPollBudgetMs: 500 }
    let started = false
    let polls = 0

    installFetch((url, init) => {
      if (url.endsWith('/jobs/job-1/run') && init?.method === 'POST') {
        started = true
        return { status: 202, body: { run_id: 'run-1', status: 'queued' } }
      }
      if (url.endsWith('/jobs/job-1')) {
        if (!started) return { body: { ...job, latest_run: null } }
        polls += 1
        const status = polls < 2 ? 'queued' : polls < 3 ? 'running' : 'succeeded'
        const succeeded = status === 'succeeded'
        return {
          body: {
            ...job,
            latest_run: runFixture({
              status,
              rows_read: succeeded ? 240 : 0,
              rows_written: succeeded ? 240 : 0,
              started_at: '2026-10-20T09:05:00Z',
              finished_at: succeeded ? '2026-10-20T09:05:02Z' : null,
              dataset_id: succeeded ? 'ds-1' : null,
            }),
          },
        }
      }
      return baseHandler(url) ?? { body: [] }
    })

    const wrapper = mountPage()
    await flushPromises()

    const runButton = wrapper.findAll('button').find(button => button.text() === 'Run now')
    expect(runButton).toBeTruthy()
    await runButton?.trigger('click')

    await waitFor(() => wrapper.text().includes('240 rows written'))

    expect(wrapper.text()).toContain('succeeded')
    expect(wrapper.text()).toContain('Run succeeded.')
    expect(wrapper.findAll('button').some(button => button.text() === 'Run now')).toBe(true)
  })

  it('shows the honest still-running state after the poll budget expires', async () => {
    pollSettings = { dataPollIntervalMs: 1, dataPollBudgetMs: 25 }
    let started = false

    installFetch((url, init) => {
      if (url.endsWith('/jobs/job-1/run') && init?.method === 'POST') {
        started = true
        return { status: 202, body: { run_id: 'run-1', status: 'queued' } }
      }
      if (url.endsWith('/jobs/job-1')) {
        if (!started) return { body: { ...job, latest_run: null } }
        return {
          body: {
            ...job,
            latest_run: runFixture({ status: 'queued' }),
          },
        }
      }
      return baseHandler(url) ?? { body: [] }
    })

    const wrapper = mountPage()
    await flushPromises()

    const runButton = wrapper.findAll('button').find(button => button.text() === 'Run now')
    await runButton?.trigger('click')

    await waitFor(() => wrapper.find('.still-running').exists())
    expect(wrapper.find('.still-running').text()).toContain('still running')
    expect(wrapper.text()).not.toContain('Run succeeded.')
  })

  it('renders the error text for a failed job', async () => {
    const failedJob: IngestJob = {
      ...job,
      latest_run: {
        ...runFixture({
          status: 'failed',
          error: 'Watermark column "updated_at" was not returned by the source.',
          started_at: '2026-10-20T09:05:00Z',
          finished_at: '2026-10-20T09:05:01Z',
        }),
      },
    }
    installFetch((url) => {
      if (url.endsWith('/connectors')) return { body: [postgresSource] }
      if (url.endsWith('/jobs')) return { body: [failedJob] }
      if (url.endsWith('/datasets')) return { body: [dataset] }
      return { body: [] }
    })

    const wrapper = mountPage()
    await flushPromises()

    const jobError = wrapper.find('.job-error')
    expect(jobError.exists()).toBe(true)
    expect(jobError.text()).toContain('Watermark column "updated_at" was not returned by the source.')
  })

  it('shows fail with the real violations count and the empty rules state', async () => {
    routeQuery = { dataset: 'ds-1' }
    const qualityFor = (rules: unknown[]) => ({
      dataset_id: 'ds-1',
      revision: 3,
      profile: [
        {
          column_name: 'ticket_id',
          dtype: 'integer',
          row_count: 240,
          null_count: 0,
          null_rate: 0,
          distinct_count: 240,
          min_value: 1,
          max_value: 240,
        },
      ],
      rules,
    })
    const failRule = {
      rule: {
        id: 'qr-1',
        dataset_id: 'ds-1',
        column_name: 'ticket_id',
        kind: 'not_null',
        params: {},
        severity: 'error',
        created_at: '2026-10-20T09:00:00Z',
      },
      latest_result: {
        id: 'qres-1',
        status: 'fail',
        observed: { violations: 7, checked: 240 },
        checked_at: '2026-10-20T09:06:00Z',
      },
    }

    installFetch((url) => {
      if (url.endsWith('/connectors')) return { body: [] }
      if (url.endsWith('/jobs')) return { body: [] }
      if (url.endsWith('/datasets/ds-1/quality')) return { body: qualityFor([failRule]) }
      if (url.endsWith('/datasets')) return { body: [dataset] }
      return { body: [] }
    })

    const wrapper = mountPage()
    await waitFor(() => wrapper.find('.rule-status').exists())

    const status = wrapper.find('.rule-status')
    expect(status.text()).toBe('fail')
    expect(status.attributes('data-status')).toBe('fail')
    expect(wrapper.find('.violations').text()).toContain('7 violations')

    wrapper.unmount()
    installFetch((url) => {
      if (url.endsWith('/connectors')) return { body: [] }
      if (url.endsWith('/jobs')) return { body: [] }
      if (url.endsWith('/datasets/ds-1/quality')) return { body: qualityFor([]) }
      if (url.endsWith('/datasets')) return { body: [dataset] }
      return { body: [] }
    })
    const empty = mountPage()
    await waitFor(() => empty.find('.quality-empty.no-rules').exists())
    expect(empty.find('.quality-empty.no-rules').text()).toContain('No quality rules')
  })

  it('says there is no profile and offers a real profile action', async () => {
    routeQuery = { dataset: 'ds-1' }
    installFetch((url) => {
      if (url.endsWith('/connectors')) return { body: [] }
      if (url.endsWith('/jobs')) return { body: [] }
      if (url.endsWith('/datasets/ds-1/quality')) {
        return { body: { dataset_id: 'ds-1', revision: 3, profile: [], rules: [] } }
      }
      if (url.endsWith('/datasets')) return { body: [dataset] }
      return { body: [] }
    })

    const wrapper = mountPage()
    await waitFor(() => wrapper.find('.quality-empty.no-profile').exists())

    const button = wrapper
      .findAll('button')
      .find(item => item.text() === 'Profile now')
    expect(button).toBeTruthy()
    expect(wrapper.text()).not.toContain('null_rate')
  })

  it('renders Arabic copy without leaking English locale keys', async () => {
    useLocale().setLocale('ar')
    installFetch(url => baseHandler(url) ?? { body: [] })

    const wrapper = mountPage()
    await flushPromises()

    const text = wrapper.text()
    expect(text).toMatch(/[\u0600-\u06FF]/)
    expect(text).not.toMatch(/\b(data|jobs|common|nav)\./)
    expect(text).toContain('مساحة البيانات')
  })
})
