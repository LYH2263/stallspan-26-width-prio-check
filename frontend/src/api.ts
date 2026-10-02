export interface ApiErrorBody {
  field?: string
  field_label?: string
  message: string
}

export class ApiError extends Error {
  status: number
  body: ApiErrorBody | null
  constructor(status: number, body: ApiErrorBody | null, raw: string) {
    super(body?.message || raw || `请求失败（${status}）`)
    this.status = status
    this.body = body
  }
  /** 接口点名字段与摊主页提示的同一叫法 */
  get fieldLabel(): string | undefined {
    return this.body?.field_label || this.body?.field
  }
}

export async function api<T = any>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch('/api' + path, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    ...init,
  })
  if (!res.ok) {
    const raw = await res.text()
    let body: ApiErrorBody | null = null
    try { body = raw ? JSON.parse(raw) : null } catch { body = null }
    throw new ApiError(res.status, body, raw)
  }
  if (res.status === 204) return undefined as T
  return res.json()
}
