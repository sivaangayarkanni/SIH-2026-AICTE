export class ApiError extends Error { status: number; constructor(s: number, m: string) { super(m); this.status = s } }

export const getToken = () => localStorage.getItem('sealcheck.token') || ''

export async function api<T = any>(path: string, opts: RequestInit & { json?: any } = {}): Promise<T> {
  const headers: Record<string, string> = { ...(opts.headers as any) }
  const t = getToken()
  if (t) headers.Authorization = `Bearer ${t}`
  let body = opts.body
  if (opts.json !== undefined) { headers['Content-Type'] = 'application/json'; body = JSON.stringify(opts.json) }
  let r: Response
  try { r = await fetch(path, { ...opts, headers, body }) } catch { throw new ApiError(0, 'You appear to be offline. The request could not reach the server.') }
  if (r.status === 401 && !path.includes('/auth/login')) {
    localStorage.removeItem('sealcheck.token'); window.dispatchEvent(new Event('sealcheck:logout'))
  }
  if (!r.ok) {
    let msg = r.statusText
    try { const j = await r.json(); msg = typeof j.detail === 'string' ? j.detail : (j.detail?.[0]?.msg ?? JSON.stringify(j.detail)) } catch { /* not json */ }
    throw new ApiError(r.status, msg)
  }
  const ct = r.headers.get('content-type') || ''
  return (ct.includes('json') ? r.json() : (r.blob() as any)) as Promise<T>
}

export async function download(path: string, filename: string) {
  const blob = await api<Blob>(path)
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a'); a.href = url; a.download = filename; a.click()
  setTimeout(() => URL.revokeObjectURL(url), 2000)
}

export const authedUrl = (path: string) => `${path}${path.includes('?') ? '&' : '?'}token=${encodeURIComponent(getToken())}`

export const fmtDate = (s?: string | null) => s ? new Date(s + (s.endsWith('Z') || s.includes('+') ? '' : 'Z')).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' }) : '—'
export const fmtDay = (s?: string | null) => s ? new Date(s + (s.endsWith('Z') || s.includes('+') ? '' : 'Z')).toLocaleDateString('en-IN', { dateStyle: 'medium' }) : '—'
export const fmtSize = (n: number) => n > 1e6 ? `${(n / 1e6).toFixed(1)} MB` : `${Math.round(n / 1024)} KB`
