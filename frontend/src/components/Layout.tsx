import { Tour } from './Tour'
import { ReactNode, useEffect, useRef, useState } from 'react'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import { LayoutDashboard, FileStack, FilePlus2, ClipboardCheck, ListOrdered, ShieldAlert, Network, ShieldCheck, ScrollText, BookOpenCheck, Settings, Workflow, Bell, Wifi, WifiOff, LogOut, Activity, Menu, Moon, Sun, CloudUpload } from 'lucide-react'
import clsx from 'clsx'
import { Logo } from './Logo'
import { GovBar, Tricolour, UtilityBar, Masthead, PortalNav, Breadcrumbs, PortalFooter, useLabel } from './Portal'
import { Avatar } from './Avatar'
import { useAuth } from '../lib/auth'
import { useTheme } from '../lib/theme'
import { api, fmtDate } from '../lib/api'
import { useOnline, useQueueCount, syncQueue } from '../lib/offline'
import { useToast } from './Toast'

type Item = { to: string; label: string; icon: any; roles: string[] }
export const NAV: { group: string; items: Item[] }[] = [
  { group: 'Overview', items: [
    { to: '/', label: 'Dashboard', icon: LayoutDashboard, roles: ['college', 'officer', 'senior_officer', 'admin'] },
    { to: '/how-it-works', label: 'How it works', icon: Workflow, roles: ['college', 'officer', 'senior_officer', 'admin'] },
  ] },
  { group: 'College workspace', items: [
    { to: '/applications', label: 'My applications', icon: FileStack, roles: ['college'] },
    { to: '/applications/new', label: 'New application', icon: FilePlus2, roles: ['college'] },
    { to: '/readiness', label: 'Readiness assistant', icon: ClipboardCheck, roles: ['college'] },
  ] },
  { group: 'Scrutiny', items: [
    { to: '/queue', label: 'Priority queue', icon: ListOrdered, roles: ['officer', 'senior_officer', 'admin'] },
    { to: '/applications', label: 'All applications', icon: FileStack, roles: ['officer', 'senior_officer', 'admin'] },
    { to: '/overrides', label: 'Security overrides', icon: ShieldAlert, roles: ['officer', 'senior_officer', 'admin'] },
    { to: '/collusion', label: 'Collusion graph', icon: Network, roles: ['officer', 'senior_officer', 'admin'] },
  ] },
  { group: 'Trust & governance', items: [
    { to: '/security', label: 'Security center', icon: ShieldCheck, roles: ['college', 'officer', 'senior_officer', 'admin'] },
    { to: '/audit', label: 'Audit log', icon: ScrollText, roles: ['officer', 'senior_officer', 'admin'] },
    { to: '/rules', label: 'Rule bundles', icon: BookOpenCheck, roles: ['college', 'officer', 'senior_officer', 'admin'] },
    { to: '/admin', label: 'System health', icon: Activity, roles: ['admin', 'senior_officer', 'officer'] },
    { to: '/notifications', label: 'Notification centre', icon: Bell, roles: ['college', 'officer', 'senior_officer', 'admin'] },
    { to: '/settings', label: 'Settings & themes', icon: Settings, roles: ['college', 'officer', 'senior_officer', 'admin'] },
  ] },
]

const ROLE_CHIP: Record<string, string> = {
  college: 'bg-sky-100 text-sky-800 dark:bg-sky-500/15 dark:text-sky-300', officer: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-500/15 dark:text-emerald-300',
  senior_officer: 'bg-purple-100 text-purple-800 dark:bg-purple-500/15 dark:text-purple-300', admin: 'bg-rose-100 text-rose-800 dark:bg-rose-500/15 dark:text-rose-300',
}

export function Layout({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth()
  const { dark, setDark, theme, lang } = useTheme(); const t = useLabel()
  const online = useOnline(), queued = useQueueCount()
  const toast = useToast(), nav = useNavigate(), loc = useLocation()
  const [notes, setNotes] = useState<any[]>([])
  const [open, setOpen] = useState<'bell' | 'me' | null>(null)
  const [mobile, setMobile] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const load = () => api('/api/notifications').then(setNotes).catch(() => {})
    load(); const t = setInterval(load, 15000); return () => clearInterval(t)
  }, [])
  useEffect(() => { setOpen(null); setMobile(false); window.scrollTo(0, 0) }, [loc.pathname])
  useEffect(() => {
    const s = (e: any) => toast('success', 'Offline queue synced', `${e.detail} upload(s) sent to the server.`)
    window.addEventListener('sealcheck:synced', s); return () => window.removeEventListener('sealcheck:synced', s)
  }, [toast])
  useEffect(() => { const c = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(null) }; document.addEventListener('mousedown', c); return () => document.removeEventListener('mousedown', c) }, [])
  if (!user) return null
  const unread = notes.filter((n) => !n.read).length

  const actions = (<>
          <span className={clsx('chip hidden sm:inline-flex', online ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-500/15 dark:text-emerald-300' : 'bg-red-100 text-red-800')} title={online ? 'Connected' : 'Offline — uploads will be queued and synced automatically'}>
            {online ? <Wifi className="h-3.5 w-3.5" /> : <WifiOff className="h-3.5 w-3.5" />}{online ? 'Online' : 'Offline'}
          </span>
          {queued > 0 && <button onClick={() => syncQueue()} className="chip bg-amber-100 text-amber-900" title="Uploads waiting to sync"><CloudUpload className="h-3.5 w-3.5" />{queued} queued</button>}
          <span className={clsx('chip hidden sm:inline-flex', ROLE_CHIP[user.role])}>{user.role_label}</span>
          <button className="rounded-xl p-2 text-muted hover:bg-surface-2 hover:text-ink" aria-label="Toggle dark mode" onClick={() => setDark(!dark)}>{dark ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}</button>
          <div className="relative">
            <button className="relative rounded-xl p-2 text-muted hover:bg-surface-2 hover:text-ink" aria-label={`Notifications, ${unread} unread`} onClick={() => setOpen(open === 'bell' ? null : 'bell')}>
              <Bell className="h-5 w-5" />{unread > 0 && <span className="absolute right-1 top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-accent px-1 text-[10px] font-bold text-white">{unread}</span>}
            </button>
            {open === 'bell' && (
              <div className="card animate-fadeUp absolute right-0 mt-2 w-96 overflow-hidden p-0 shadow-pop">
                <div className="flex items-center justify-between border-b border-line px-4 py-3"><b className="text-sm">Notifications</b>
                  <span className="flex gap-3"><button className="text-xs font-semibold text-primary" onClick={() => api('/api/notifications/read', { method: 'POST' }).then(() => setNotes(notes.map((n) => ({ ...n, read: true }))))}>Mark all read</button>
                  <button data-testid="open-notification-centre" className="text-xs font-semibold text-primary" onClick={() => { setOpen(null); nav('/notifications') }}>View all</button></span></div>
                <div className="max-h-96 overflow-y-auto scroll-thin">
                  {notes.length === 0 && <div className="p-6 text-center text-sm text-muted">You are all caught up.</div>}
                  {notes.map((n) => (
                    <button key={n.id} onClick={() => n.link && nav(n.link)} className="flex w-full gap-3 border-b border-line/60 px-4 py-3 text-left hover:bg-surface-2">
                      <span className={clsx('mt-1.5 h-2 w-2 shrink-0 rounded-full', n.read ? 'bg-line' : 'bg-accent')} />
                      <span><span className="block text-sm">{n.message}</span><span className="text-xs text-muted">{fmtDate(n.created_at)}</span></span>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
          <div className="relative">
            <button className="flex items-center gap-2 rounded-xl p-1 pr-2 hover:bg-surface-2" onClick={() => setOpen(open === 'me' ? null : 'me')} aria-label="Account menu">
              <Avatar seed={user.avatar_seed} size={34} title={user.name} />
              <span className="hidden text-left xl:block"><span className="block text-sm font-semibold leading-tight">{user.name}</span><span className="block text-xs text-muted">{user.title}</span></span>
            </button>
            {open === 'me' && (
              <div className="card animate-fadeUp absolute right-0 mt-2 w-72 p-2 shadow-pop">
                <div className="flex items-center gap-3 p-3"><Avatar seed={user.avatar_seed} size={44} /><div className="min-w-0"><div className="truncate font-semibold">{user.name}</div><div className="truncate text-xs text-muted">{user.email}</div></div></div>
                <button className="w-full rounded-lg px-3 py-2 text-left text-sm hover:bg-surface-2" onClick={() => nav('/settings')}>Settings & themes</button>
                <button className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm text-red-600 hover:bg-red-50 dark:hover:bg-red-500/10" onClick={() => { logout(); nav('/login') }}><LogOut className="h-4 w-4" />Sign out</button>
              </div>
            )}
          </div>
  </>)

  const side = (
    <aside className="flex h-full w-[264px] flex-col bg-side text-side-ink">
      <div className="px-5 py-5"><Logo light /></div>
      <nav className="flex-1 space-y-5 overflow-y-auto px-3 pb-4 scroll-thin" aria-label="Main" lang={lang}>
        {NAV.map((g) => {
          const items = g.items.filter((i) => i.roles.includes(user.role))
          if (!items.length) return null
          return (
            <div key={g.group}>
              <div className="px-3 pb-1.5 text-[10.5px] font-bold uppercase tracking-[.14em] text-side-ink/50">{t(g.group)}</div>
              {items.map((i) => (
                <NavLink key={i.to + i.label} to={i.to} end={i.to === '/' || i.to === '/applications'}
                  className={({ isActive }) => clsx('group mb-0.5 flex items-center gap-3 rounded-xl px-3 py-2 text-[13.5px] font-medium transition',
                    isActive ? 'bg-side-active text-white shadow-lg shadow-black/20' : 'hover:bg-white/5 hover:text-white')}>
                  <i.icon className="h-[18px] w-[18px]" />{t(i.label)}
                </NavLink>
              ))}
            </div>
          )
        })}
      </nav>
      <div className="m-3 rounded-2xl bg-white/5 p-3.5 text-xs">
        <div className="flex items-center gap-2 font-semibold text-white"><ShieldCheck className="h-4 w-4 text-emerald-400" />Zero-trust mode</div>
        <p className="mt-1 leading-relaxed text-side-ink/70">Every file is sandboxed, every action is hash-chained, and AI only explains — humans decide.</p>
      </div>
    </aside>
  )

  if (theme === 'portal') return (
    <div className="flex min-h-full flex-col bg-bg" data-layout="portal">
      <GovBar /><Tricolour /><UtilityBar />
      <header className="relative z-40 border-b border-line bg-surface" ref={ref}>
        <Masthead right={<div className="flex items-center gap-2">
          <button className="rounded-lg p-2 hover:bg-surface-2 lg:hidden" aria-label="Open menu" onClick={() => setMobile(true)}><Menu className="h-5 w-5" /></button>
          {actions}</div>} />
      </header>
      <div className="relative z-30 hidden lg:block"><PortalNav groups={NAV} role={user.role} /></div>
      {mobile && <div className="fixed inset-0 z-50 flex lg:hidden"><div>{side}</div><div className="flex-1 bg-black/40" onClick={() => setMobile(false)} /></div>}
      <Breadcrumbs groups={NAV} />
      <Tour /><main id="main-content" tabIndex={-1} className="flex-1"><div className="mx-auto max-w-[1360px] px-4 py-6 md:px-8">{children}</div></main>
      <PortalFooter />
    </div>
  )

  return (
    <div className="flex h-full">
      <div className="hidden lg:block">{side}</div>
      {mobile && <div className="fixed inset-0 z-50 flex lg:hidden"><div>{side}</div><div className="flex-1 bg-black/40" onClick={() => setMobile(false)} /></div>}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-40 flex h-16 items-center gap-3 border-b border-line bg-surface/85 px-4 backdrop-blur md:px-6" ref={ref}>
          <button className="rounded-lg p-2 hover:bg-surface-2 lg:hidden" aria-label="Open menu" onClick={() => setMobile(true)}><Menu className="h-5 w-5" /></button>
          <div className="hidden min-w-0 md:block">
            <div className="truncate text-sm font-semibold">{user.college || 'All India Council for Technical Education'}</div>
            <div className="text-xs text-muted">Academic year 2026-27 · Approval cycle</div>
          </div>
          <div className="flex-1" />
          {actions}
        </header>
        <Tour /><main id="main-content" tabIndex={-1} className="flex-1 overflow-y-auto scroll-thin"><div className="mx-auto max-w-[1360px] px-4 py-7 md:px-8">{children}</div></main>
      </div>
    </div>
  )
}
