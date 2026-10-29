import { createContext, useContext, useEffect, useRef, useState, ReactNode } from 'react'
import { api } from './api'
import { OidcCfg, startLogin, endSession, refresh, schedule } from './oidc'

export type User = { id: number; email: string; name: string; title: string; role: 'college' | 'officer' | 'senior_officer' | 'admin'; role_label: string; college: string | null; college_id: number | null; avatar_seed: string }
export type AuthCfg = { mode: 'local' | 'oidc'; idle_timeout_min: number; oidc: OidcCfg | null; demo_accounts: boolean }
type Ctx = { user: User | null; loading: boolean; cfg: AuthCfg | null; login: (e: string, p: string) => Promise<User>; sso: (returnTo?: string) => Promise<void>; logout: (reason?: string) => void; setUser: (u: User | null) => void }
const Ctx = createContext<Ctx>(null!)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)
  const [cfg, setCfg] = useState<AuthCfg | null>(null)
  const last = useRef(Date.now())
  useEffect(() => {
    const out = () => setUser(null)
    window.addEventListener('sealcheck:logout', out)
    api<AuthCfg>('/api/auth/config').then(async (c) => {
      setCfg(c)
      if (c.mode === 'oidc' && c.oidc && sessionStorage.getItem('sealcheck.refresh')) await refresh(c.oidc).catch(() => localStorage.removeItem('sealcheck.token'))
      if (localStorage.getItem('sealcheck.token')) await api<User>('/api/auth/me').then(setUser).catch(() => setUser(null))
    }).catch(() => {}).finally(() => setLoading(false))
    return () => window.removeEventListener('sealcheck:logout', out)
  }, [])
  const logout = (reason?: string) => {
    if (localStorage.getItem('sealcheck.token')) api('/api/auth/logout', { method: 'POST' }).catch(() => {})
    localStorage.removeItem('sealcheck.token'); setUser(null)
    if (reason) sessionStorage.setItem('sealcheck.logout_reason', reason)
    if (cfg?.mode === 'oidc' && cfg.oidc) endSession(cfg.oidc)
  }
  // idle timeout (both modes): sign out after N minutes without input
  useEffect(() => {
    if (!user || !cfg) return
    const bump = () => { last.current = Date.now() }
    const evs = ['mousemove', 'keydown', 'pointerdown', 'scroll', 'touchstart']
    evs.forEach((e) => window.addEventListener(e, bump, { passive: true }))
    const iv = window.setInterval(() => { if (Date.now() - last.current > cfg.idle_timeout_min * 60000) logout('You were signed out after a period of inactivity.') }, 15000)
    return () => { evs.forEach((e) => window.removeEventListener(e, bump)); clearInterval(iv) }
  }, [user, cfg]) // eslint-disable-line react-hooks/exhaustive-deps
  const login = async (email: string, password: string) => {
    const r = await api<{ token: string; user: User }>('/api/auth/login', { method: 'POST', json: { email, password } })
    localStorage.setItem('sealcheck.token', r.token); setUser(r.user); return r.user
  }
  const sso = async (returnTo = '/') => { if (cfg?.oidc) await startLogin(cfg.oidc, returnTo) }
  return <Ctx.Provider value={{ user, loading, cfg, login, sso, logout, setUser }}>{children}</Ctx.Provider>
}
export const useAuth = () => useContext(Ctx)
export const isStaff = (u: User | null) => !!u && u.role !== 'college'
export { schedule }
