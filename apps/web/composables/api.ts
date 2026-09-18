import type { ApiErrorBody } from '~/shared/types'

export class ApiError extends Error implements ApiErrorBody {
  status: number
  override message: string
  code?: string
  detail?: unknown

  constructor(status: number, message: string, code?: string, detail?: unknown) {
    super(message)
    this.status = status
    this.message = message
    this.code = code
    this.detail = detail
  }
}

// Demo identity model mirrors the API's DEMO_USERS map. Switching the acting
// user demonstrates separation of duties: a modeler proposes, a manager
// approves — self-approval is refused server-side (§29 QA-018).
export const DEMO_ACTORS = {
  'alpha.manager': { role: 'ops_manager', label: 'A. Manager (ops manager)' },
  'alpha.modeler': { role: 'semantic_modeler', label: 'A. Modeler (semantic modeler)' }
} as const

export type DemoUser = keyof typeof DEMO_ACTORS

export function useApi() {
  const config = useRuntimeConfig()
  const base = computed(() => (config.public.apiBase as string).replace(/\/+$/, ''))
  const user = useState<DemoUser>('demo-user', () => 'alpha.manager')

  function headers(extra: Record<string, string> = {}): Record<string, string> {
    return { 'X-Tenant': 'tenant_alpha', 'X-User': user.value, ...extra }
  }

  async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
    const merged = { ...(init.headers as Record<string, string> | undefined), ...headers() }
    let res: Response
    try {
      res = await fetch(`${base.value}${path}`, { ...init, headers: merged })
    } catch {
      throw new ApiError(0, `Analytics API unreachable at ${base.value} — is the service running on :8100?`)
    }
    const text = await res.text()
    if (!res.ok) {
      let code: string | undefined
      let detail: unknown
      try {
        const parsed = JSON.parse(text)
        detail = parsed.detail ?? parsed
        code = typeof detail === 'object' && detail !== null ? (detail as { code?: string }).code : undefined
      } catch {
        code = undefined
      }
      throw new ApiError(res.status, friendlyMessage(res.status, code, text), code, detail)
    }
    return (text ? JSON.parse(text) : null) as T
  }

  const get = <T>(path: string) => call<T>(path)
  const post = <T>(path: string, body?: unknown) =>
    call<T>(path, {
      method: 'POST',
      headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body)
    })
  const postWithKey = <T>(path: string, idempotencyKey: string, body: unknown) =>
    call<T>(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey },
      body: JSON.stringify(body)
    })
  const putBytes = <T>(path: string, bytes: ArrayBuffer) =>
    call<T>(path, { method: 'PUT', headers: { 'Content-Type': 'application/octet-stream' }, body: bytes })

  function friendlyMessage(status: number, code: string | undefined, raw: string): string {
    if (code === 'grain_not_proven') return 'Grain not proven: uniqueness failed over the full dataset. Pick a key with no nulls and no duplicates.'
    if (code === 'grain_unconfirmed') return 'Publishing is blocked until the business grain is confirmed.'
    if (code === 'self_approval_not_allowed') return 'Self-approval is not allowed. Switch the acting user to approve this definition.'
    if (code === 'approval_not_allowed') return 'This user role cannot approve definitions.'
    if (code === 'revision_not_publishable') return 'Revision is not publishable (not validated, or already published).'
    if (code === 'concurrent_publish_conflict') return 'A concurrent publish moved the pointer first; refresh and retry.'
    if (status === 401) return 'Demo authentication missing (X-Tenant/X-User headers).'
    if (status === 404) return 'Not found for this tenant.'
    if (status === 409) return 'Conflict: ' + (code ?? raw.slice(0, 160))
    if (status === 422) return 'Rejected: ' + (code ?? raw.slice(0, 160))
    return `${status}: ${raw.slice(0, 200)}`
  }

  return { base, user, headers, call, get, post, postWithKey, putBytes }
}
