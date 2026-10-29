import { useEffect, useState } from 'react'
import { ShieldCheck, Code2, ListChecks } from 'lucide-react'
import { api } from '../lib/api'
import { PageHeader, Skeleton, Tabs } from '../components/ui'

export default function Rules() {
  const [r, setR] = useState<any>(null); const [meta, setMeta] = useState<any>(null); const [tab, setTab] = useState('docs')
  useEffect(() => { api('/api/rules').then(setR); api('/api/meta').then(setMeta) }, [])
  if (!r || !meta) return <Skeleton className="h-[600px]" />
  const b = r.bundle
  return (
    <>
      <PageHeader eyebrow="Module 4B" title="AICTE rule bundle" desc="The rule engine and the policy engine are deterministic: the same document always gets the same status. Rules live in a signed YAML bundle so they can be updated without code changes — and cannot be altered silently." />
      <div className="card card-pad mb-5 flex flex-wrap items-center gap-5">
        <ShieldCheck className={`h-10 w-10 ${r.valid ? 'text-emerald-500' : 'text-red-500'}`} />
        <div className="flex-1"><div className="font-semibold">{b?.bundle?.id} · v{b?.bundle?.version}</div><div className="text-sm text-muted">{b?.bundle?.authority} · published {b?.bundle?.published}</div></div>
        <div className="text-right text-sm"><div>{r.verification.algorithm} signature: <b className={r.valid ? 'text-emerald-600' : 'text-red-600'}>{r.valid ? 'valid' : 'INVALID'}</b></div><div className="font-mono text-xs text-muted">{r.verification.sha256?.slice(0, 32)}…</div></div>
      </div>
      <Tabs value={tab} onChange={setTab} tabs={[{ id: 'docs', label: <span className="flex items-center gap-1.5"><ListChecks className="h-4 w-4" />Document rules</span> }, { id: 'policy', label: 'Policy table' }, { id: 'cats', label: 'Categories' }, { id: 'yaml', label: <span className="flex items-center gap-1.5"><Code2 className="h-4 w-4" />Signed YAML</span> }]} />
      <div className="mt-4">
        {tab === 'docs' && <div className="grid gap-4 lg:grid-cols-2">{Object.entries(b.document_types).map(([k, d]: any) => (
          <div key={k} className="card card-pad"><div className="flex items-start justify-between gap-2"><b>{d.label}</b><span className="kbd">{k}</span></div><div className="text-xs text-muted">{d.clause}</div>
            {d.required_fields?.length > 0 && <ul className="mt-2 space-y-1 text-sm">{d.required_fields.map((f: any, i: number) => <li key={i} className="flex items-start gap-2"><span className="kbd shrink-0">F{i + 1}</span><span>{f.name}</span></li>)}</ul>}
            <div className="mt-2 flex flex-wrap gap-1.5 text-xs">{d.validity_required && <span className="chip bg-primary-soft text-primary">validity date required</span>}{d.min_remaining_days > 0 && <span className="chip bg-primary-soft text-primary">≥ {d.min_remaining_days} days remaining</span>}{d.dsc_required && <span className="chip bg-primary-soft text-primary">DSC required</span>}{d.photo && <span className="chip bg-primary-soft text-primary">photo checks</span>}</div>
          </div>))}</div>}
        {tab === 'policy' && <div className="card overflow-hidden"><table className="w-full text-sm"><thead className="bg-surface-2"><tr className="table-head"><th className="px-5 py-2.5">Order</th><th>Rule</th><th>Condition</th><th>Resulting status</th></tr></thead>
          <tbody>{meta.policy_table.map(([id, status, text]: any, i: number) => <tr key={i} className="border-t border-line"><td className="px-5 py-3">{i + 1}</td><td><span className="kbd">{id}</span></td><td className="py-3">{text}</td><td className="font-semibold">{status}</td></tr>)}</tbody></table><p className="border-t border-line px-5 py-3 text-xs text-muted">First match wins. The application's status is its worst document status, or Verification Pending while required documents are missing.</p></div>}
        {tab === 'cats' && <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{b.categories.map((c: any) => <div key={c.id} className="card card-pad"><b className="text-sm">{c.label}</b><ul className="mt-2 list-disc pl-5 text-xs text-muted">{c.docs.map((d: string) => <li key={d}>{b.document_types[d]?.label}</li>)}</ul></div>)}</div>}
        {tab === 'yaml' && <pre className="card max-h-[640px] overflow-auto p-5 font-mono text-xs leading-relaxed scroll-thin">{r.yaml}</pre>}
      </div>
    </>
  )
}
