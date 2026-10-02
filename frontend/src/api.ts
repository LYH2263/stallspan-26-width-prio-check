export class ApiError extends Error {
  field?: string
  status: number
  constructor(status: number, field: string | undefined, message: string) {
    super(message)
    this.status = status
    this.field = field
  }
}

// 与后端 app/services/rules.py 共用同一套字段 key 与叫法，前端不得另起名字
export const FIELD_LABELS: Record<string, string> = {
  stall_width_m: '摊宽(stall_width_m)',
  priority: '优先级(priority)',
  width_m: '街宽(width_m)',
}

export async function api<T = any>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch('/api' + path, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    ...init,
  })
  if (!res.ok) {
    const text = await res.text()
    let field: string | undefined
    let message = text || res.statusText
    try {
      const j = JSON.parse(text)
      if (j.detail) {
        if (typeof j.detail === 'object' && !Array.isArray(j.detail)) {
          field = j.detail.field
          message = j.detail.message
        } else if (Array.isArray(j.detail)) {
          message = j.detail
            .map((d: any) => {
              const name = d.loc?.slice(1).join('.') ?? ''
              return (name ? FIELD_LABELS[name] || name : '') + ' ' + (d.msg ?? '')
            })
            .join('；')
        } else {
          message = String(j.detail)
        }
      }
    } catch {
      /* 非 JSON 错误体，原样展示 */
    }
    throw new ApiError(res.status, field, message)
  }
  if (res.status === 204) return undefined as T
  return res.json()
}
