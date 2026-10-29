import { useEffect, useState } from 'react'
import { Database, Cpu, Package, CheckCircle2, XCircle } from 'lucide-react'
import { api } from '../lib/api'
import { PageHeader, Skeleton, Stat } from '../components/ui'

export default function Admin() {
  const [h, setH] = useState<any>(null)
  useEffect(() => { api('/api/admin/health').then(setH) }, [])
  if (!h) return <Skeleton className="h-[500px]" />
  return (
    <>
      <PageHeader eyebrow="Operations" title="System health" desc="Live counters from this running instance. Durations are measured on this machine for the bundled synthetic samples — not a benchmark." />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat icon={Cpu} label="Jobs completed" value={`${h.jobs.done}/${h.jobs.total}`} hint={`${h.jobs.failed} failed · ${h.jobs.queued} queued`} tone="green" />
        <Stat icon={Cpu} label="Avg job time (measured)" value={`${h.jobs.measured_avg_ms ?? '–'} ms`} hint={`max ${h.jobs.measured_max_ms ?? '–'} ms`} />
        <Stat icon={Database} label="Data on disk" value={`${h.disk_data_mb} MB`} hint={h.database.url} tone="purple" />
        <Stat icon={Package} label="Python" value={h.python} />
      </div>
      <div className="mt-5 grid gap-5 lg:grid-cols-2">
        <div className="card card-pad"><div className="text-sm font-semibold">Database tables</div><div className="mt-2 grid grid-cols-2 gap-2">{Object.entries(h.database.tables).map(([k, v]: any) => <div key={k} className="flex justify-between rounded-xl bg-surface-2 px-3 py-2 text-sm"><span className="text-muted">{k}</span><b className="tabular-nums">{v}</b></div>)}</div></div>
        <div className="card card-pad"><div className="text-sm font-semibold">Analysis components</div><div className="mt-2 space-y-1.5">{Object.entries(h.components).map(([k, v]: any) => <div key={k} className="flex items-center justify-between rounded-xl bg-surface-2 px-3 py-2 text-sm"><span>{k}</span><span className="flex items-center gap-1.5 text-muted">{v === false ? <><XCircle className="h-4 w-4 text-slate-400" />not installed (fallback active)</> : <><CheckCircle2 className="h-4 w-4 text-emerald-500" />{v === true ? 'available' : v}</>}</span></div>)}</div></div>
      </div>
    </>
  )
}
