import { useEffect, useMemo, useState } from 'react'
import { Link2, Search, Loader2, CheckCircle2, XCircle } from 'lucide-react'
import { api, fmtDate } from '../lib/api'
import { PageHeader, Skeleton } from '../components/ui'
import { useToast } from '../components/Toast'

export default function Audit() {
  const [rows, setRows] = useState<any[] | null>(null); const [v, setV] = useState<any>(null); const [q, setQ] = useState(''); const [busy, setBusy] = useState(false); const [open, setOpen] = useState<number | null>(null)
  const toast = useToast()
  useEffect(() => { api('/api/audit?limit=500').then(setRows); api('/api/audit/verify').then(setV) }, [])
  const verify = async () => { setBusy(true); const r = await api('/api/audit/verify'); setV(r); setBusy(false); toast(r.valid ? 'success' : 'error', r.valid ? 'Chain verified' : 'Chain broken', r.valid ? `${r.entries} entries, every hash matches.` : r.reason) }
  const list = useMemo(() => (rows || []).filter((r) => !q || `${r.action} ${r.actor} ${r.target}`.toLowerCase().includes(q.toLowerCase())), [rows, q])
  return (
    <>
      <PageHeader eyebrow="Tamper-evident" title="Audit log" desc="Append-only, hash-chained record of every sign-in, upload, analysis, question, decision and override."
        actions={<button data-tour="verify" className="btn-primary" onClick={verify} disabled={busy}>{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Link2 className="h-4 w-4" />}Verify chain</button>} />
      {v && <div className={`mb-4 flex items-center gap-3 rounded-2xl border p-4 text-sm ${v.valid ? 'border-emerald-300 bg-emerald-50 text-emerald-900 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-200' : 'border-red-300 bg-red-50 text-red-800'}`}>{v.valid ? <CheckCircle2 className="h-5 w-5" /> : <XCircle className="h-5 w-5" />}<span>{v.valid ? <>Chain intact: <b>{v.entries}</b> entries. Head hash <span className="font-mono text-xs">{v.head?.slice(0, 32)}…</span></> : <>Broken at entry #{v.broken_at}: {v.reason}</>}</span></div>}
      <div className="card overflow-hidden">
        <div className="border-b border-line p-4"><div className="relative"><Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" /><input className="input pl-9" placeholder="Filter by action, actor or target" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Filter audit log" /></div></div>
        {!rows ? <div className="p-5"><Skeleton className="h-80" /></div> : (
          <div className="overflow-x-auto"><table className="w-full text-sm"><thead className="bg-surface-2"><tr className="table-head"><th className="px-4 py-2.5">#</th><th>Time</th><th>Action</th><th>Actor</th><th>Target</th><th>Hash → previous</th></tr></thead>
            <tbody>{list.map((r) => <>
              <tr key={r.id} className="cursor-pointer border-t border-line hover:bg-surface-2" onClick={() => setOpen(open === r.id ? null : r.id)}>
                <td className="px-4 py-2 tabular-nums text-muted">{r.id}</td><td className="whitespace-nowrap">{fmtDate(r.ts)}</td><td><span className="kbd">{r.action}</span></td><td className="max-w-[240px] truncate">{r.actor}</td><td className="text-muted">{r.target}</td>
                <td className="font-mono text-[11px] text-muted">{r.hash.slice(0, 10)} → {r.prev_hash.slice(0, 10)}</td></tr>
              {open === r.id && <tr key={`d${r.id}`} className="bg-surface-2"><td colSpan={6} className="px-4 py-3"><pre className="whitespace-pre-wrap break-all font-mono text-xs">{JSON.stringify({ role: r.role, details: r.details, hash: r.hash, prev_hash: r.prev_hash }, null, 2)}</pre></td></tr>}
            </>)}</tbody></table></div>
        )}
      </div>
    </>
  )
}
