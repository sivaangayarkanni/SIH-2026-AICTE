import { useEffect, useRef, useState } from 'react'
import { UploadCloud, Loader2, ShieldCheck, Download, FileText, Lightbulb, Lock } from 'lucide-react'
import { api, getToken, download } from '../lib/api'
import { PageHeader, StatusChip, RiskBadge, Empty } from '../components/ui'
import { FindingRow } from '../components/DocPanel'
import { useToast } from '../components/Toast'

export default function Readiness() {
  const [meta, setMeta] = useState<any>(null); const [tpl, setTpl] = useState<any[]>([]); const [dt, setDt] = useState('land_document')
  const [res, setRes] = useState<any>(null); const [busy, setBusy] = useState(false); const [drag, setDrag] = useState(false)
  const ref = useRef<HTMLInputElement>(null); const toast = useToast()
  useEffect(() => { api('/api/meta').then(setMeta); api('/api/templates').then(setTpl) }, [])
  const run = async (f: File) => {
    setBusy(true); setRes(null)
    const fd = new FormData(); fd.append('file', f); fd.append('doc_type', dt)
    try {
      const r = await fetch('/api/readiness/precheck', { method: 'POST', body: fd, headers: { Authorization: `Bearer ${getToken()}` } })
      const j = await r.json(); if (!r.ok) throw new Error(j.detail); setRes({ ...j, name: f.name })
    } catch (e: any) { toast('error', 'Pre-check failed', e.message) } finally { setBusy(false) }
  }
  return (
    <>
      <PageHeader eyebrow="Before you submit" title="Readiness assistant" desc="Check a file privately before it becomes part of your application. The same sandbox, forensics and rules run — but nothing is stored, and officers never see it." />
      <div className="grid gap-5 lg:grid-cols-[1fr_360px]">
        <div className="space-y-5">
          <div className="card card-pad">
            <div className="grid gap-3 sm:grid-cols-[1fr_auto]">
              <div><label className="label" htmlFor="dt">Document type</label><select id="dt" className="input" value={dt} onChange={(e) => setDt(e.target.value)}>{meta && Object.entries(meta.doc_types).map(([k, v]: any) => <option key={k} value={k}>{v.label}</option>)}</select></div>
              <div className="flex items-end"><span className="chip bg-emerald-100 text-emerald-800 dark:bg-emerald-500/15 dark:text-emerald-300"><Lock className="h-3.5 w-3.5" />Not stored</span></div>
            </div>
            <div onDragOver={(e) => { e.preventDefault(); setDrag(true) }} onDragLeave={() => setDrag(false)} onDrop={(e) => { e.preventDefault(); setDrag(false); const f = e.dataTransfer.files[0]; if (f) run(f) }}
              onClick={() => ref.current?.click()} role="button" tabIndex={0} onKeyDown={(e) => e.key === 'Enter' && ref.current?.click()}
              className={`mt-4 flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed px-6 py-12 text-center transition ${drag ? 'border-primary bg-primary-soft' : 'border-line hover:border-primary/60 hover:bg-surface-2'}`}>
              {busy ? <Loader2 className="h-10 w-10 animate-spin text-primary" /> : <UploadCloud className="h-10 w-10 text-primary" />}
              <div className="mt-3 font-semibold">{busy ? 'Analysing in a temporary sandbox…' : 'Drop a PDF or photo here, or click to choose'}</div>
              <div className="mt-1 text-xs text-muted">PDF for documents · JPEG/PNG for lab photos · up to 15 MB</div>
            </div>
            <input ref={ref} type="file" className="hidden" accept=".pdf,image/jpeg,image/png" onChange={(e) => { const f = e.target.files?.[0]; if (f) run(f); e.target.value = '' }} />
          </div>
          {res ? (
            <div className="card card-pad animate-fadeUp">
              <div className="flex flex-wrap items-center gap-3"><FileText className="h-5 w-5 text-muted" /><b className="flex-1 truncate">{res.name}</b><span className="text-xs text-muted">Predicted:</span><StatusChip status={res.predicted_status} size="lg" /><RiskBadge score={res.risk_score} /></div>
              <p className="mt-2 text-xs text-muted">{res.note}</p>
              {res.signed_file_guard && <div className="mt-3 flex gap-2 rounded-xl border border-primary/40 bg-primary-soft/60 p-3 text-sm"><ShieldCheck className="h-5 w-5 shrink-0 text-primary" />{res.signed_file_guard}</div>}
              {res.tips.length > 0 && <div className="mt-4 rounded-xl bg-amber-50 p-3 dark:bg-amber-500/10"><div className="flex items-center gap-2 text-sm font-semibold"><Lightbulb className="h-4 w-4 text-amber-500" />How to fix before submitting</div><ul className="mt-1.5 list-disc space-y-1 pl-6 text-sm">{[...new Set(res.tips as string[])].map((t) => <li key={t}>{t}</li>)}</ul></div>}
              <div className="mt-4 space-y-2">{res.findings.map((f: any, i: number) => <FindingRow key={i} f={f} i={i} />)}</div>
            </div>
          ) : <Empty icon={ShieldCheck} title="No file checked yet" body="Results appear here: the predicted status, every check with its rule ID, and plain-language fixes." />}
        </div>
        <div className="card card-pad h-fit">
          <div className="text-sm font-semibold">Smart templates</div>
          <p className="mt-1 text-xs text-muted">Pre-structured drafts that already contain every field the rule engine looks for. Fill them in, have them signed by the issuer, then upload.</p>
          <ul className="mt-3 space-y-1.5">{tpl.map((t) => (
            <li key={t.name}><button onClick={() => download(`/api/templates/${t.name}`, t.name).then(() => toast('success', 'Template downloaded', t.name))} className="flex w-full items-center gap-2 rounded-xl border border-line px-3 py-2 text-left text-sm hover:border-primary hover:bg-surface-2">
              <span className={`rounded-md px-1.5 py-0.5 text-[10px] font-bold ${t.name.endsWith('.pdf') ? 'bg-red-100 text-red-700' : 'bg-blue-100 text-blue-700'}`}>{t.name.split('.').pop()!.toUpperCase()}</span>
              <span className="flex-1 truncate">{t.name.replace(/_/g, ' ').replace(/\.(pdf|docx)$/, '')}</span><Download className="h-4 w-4 text-muted" /></button></li>
          ))}</ul>
        </div>
      </div>
    </>
  )
}
