import { useEffect, useState } from 'react'
import { Check, Moon, Sun, CloudUpload, Trash2, RefreshCw, WifiOff } from 'lucide-react'
import clsx from 'clsx'
import { THEMES, useTheme } from '../lib/theme'
import { useAuth } from '../lib/auth'
import { listQueue, removeQueued, syncQueue, QueuedUpload, useOnline } from '../lib/offline'
import { fmtDate, fmtSize } from '../lib/api'
import { PageHeader, Empty } from '../components/ui'
import { Avatar } from '../components/Avatar'
import { useToast } from '../components/Toast'

export default function Settings() {
  const { theme, setTheme, dark, setDark } = useTheme(); const { user } = useAuth(); const online = useOnline(); const toast = useToast()
  const [q, setQ] = useState<QueuedUpload[]>([])
  const load = () => listQueue().then(setQ)
  useEffect(() => { load(); window.addEventListener('sealcheck:queue', load); window.addEventListener('sealcheck:synced', load); return () => { window.removeEventListener('sealcheck:queue', load); window.removeEventListener('sealcheck:synced', load) } }, [])
  return (
    <>
      <PageHeader eyebrow="Personalise" title="Settings & themes" desc="Your choices are saved in this browser." />
      <div className="grid gap-5 lg:grid-cols-[1fr_380px]">
        <div className="space-y-5">
          <div className="card card-pad">
            <div className="text-sm font-semibold">Colour theme</div>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">{THEMES.map((t) => (
              <button key={t.id} onClick={() => setTheme(t.id)} aria-pressed={theme === t.id} className={clsx('relative overflow-hidden rounded-2xl border-2 text-left transition', theme === t.id ? 'border-primary shadow-pop' : 'border-line hover:border-primary/50')}>
                <div className="flex h-20">{t.swatch.map((c, i) => <div key={c} className="h-full" style={{ background: c, width: i === 0 ? '55%' : i === 1 ? '15%' : '30%' }} />)}</div>
                <div className="p-3"><div className="text-sm font-semibold">{t.name}</div><div className="text-xs text-muted">{t.desc}</div></div>
                {theme === t.id && <span className="absolute right-2 top-2 rounded-full bg-white p-1 text-primary shadow"><Check className="h-4 w-4" /></span>}
              </button>
            ))}</div>
            <div className="mt-4 flex items-center justify-between rounded-xl bg-surface-2 p-3">
              <div className="flex items-center gap-2 text-sm font-semibold">{dark ? <Moon className="h-4 w-4" /> : <Sun className="h-4 w-4" />}Dark mode</div>
              <button role="switch" aria-checked={dark} aria-label="Dark mode" onClick={() => setDark(!dark)} className={clsx('relative h-6 w-11 rounded-full transition', dark ? 'bg-primary' : 'bg-line')}><span className={clsx('absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-all', dark ? 'left-[22px]' : 'left-0.5')} /></button>
            </div>
          </div>
          <div className="card card-pad">
            <div className="flex items-center justify-between"><div className="flex items-center gap-2 text-sm font-semibold"><CloudUpload className="h-4 w-4 text-primary" />Offline upload queue</div>
              <button className="btn-ghost btn-sm" disabled={!online || !q.length} onClick={() => syncQueue().then((r) => { toast(r.failed.length ? 'error' : 'success', `Synced ${r.sent} upload(s)`, r.failed.join('; ') || undefined); load() })}><RefreshCw className="h-3.5 w-3.5" />Sync now</button></div>
            <p className="mt-1 text-xs text-muted">When the connection drops, uploads are stored in this browser (IndexedDB) and sent automatically when you are back online. The app shell is cached by a service worker so pages still open offline.</p>
            <div className="mt-3">{q.length === 0 ? <Empty icon={WifiOff} title="Queue is empty" body="Switch your browser to offline mode and upload a document to try it." /> :
              <ul className="space-y-2">{q.map((it) => <li key={it.id} className="flex items-center gap-3 rounded-xl border border-line p-3 text-sm"><span className="min-w-0 flex-1"><b className="block truncate">{it.name}</b><span className="text-xs text-muted">Application #{it.appId} · {it.docType} · {fmtSize(it.blob.size)} · queued {fmtDate(it.queuedAt)}</span></span><button aria-label="Remove from queue" className="btn-ghost btn-sm" onClick={() => removeQueued(it.id!)}><Trash2 className="h-3.5 w-3.5" /></button></li>)}</ul>}</div>
          </div>
        </div>
        <div className="card card-pad h-fit text-center">
          <Avatar seed={user!.avatar_seed} size={96} /><div className="mt-3 font-display text-xl font-bold">{user!.name}</div><div className="text-sm text-muted">{user!.title}</div>
          <div className="mt-1 text-sm text-muted">{user!.email}</div><div className="mt-3 inline-flex rounded-full bg-primary-soft px-3 py-1 text-xs font-semibold text-primary">{user!.role_label}</div>
          {user!.college && <div className="mt-2 text-sm">{user!.college}</div>}
          <p className="mt-4 text-xs text-muted">Avatars are generated locally from a seed — no photos or third-party services.</p>
        </div>
      </div>
    </>
  )
}
