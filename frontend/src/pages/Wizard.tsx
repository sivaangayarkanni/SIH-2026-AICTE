import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams, Link } from 'react-router-dom'
import { ArrowLeft, ArrowRight, CheckCircle2, CloudUpload, FileText, Loader2, Save, Send, TriangleAlert } from 'lucide-react'
import clsx from 'clsx'
import { api, fmtDate } from '../lib/api'
import { PageHeader, Skeleton, StatusChip } from '../components/ui'
import { useToast } from '../components/Toast'
import { Safeguard } from '../components/Safeguard'

const FIELDS: { k: string; label: string; hint?: string; type?: string; req?: boolean }[] = [
  { k: 'institution_name', label: 'Institution name', req: true },
  { k: 'trust_name', label: 'Trust / society (applicant)', req: true },
  { k: 'address', label: 'Address of the institution', req: true },
  { k: 'survey_no', label: 'Survey / plot number', hint: 'e.g. 142/3B', req: true },
  { k: 'land_area', label: 'Land area', hint: 'e.g. 12.5 acres', req: true },
  { k: 'lease_start', label: 'Lease start date', type: 'date' },
  { k: 'lease_end', label: 'Lease end date', type: 'date' },
  { k: 'lease_term', label: 'Lease term (years)', type: 'number' },
  { k: 'signatory', label: 'Authorised signatory', hint: 'Name, designation', req: true },
]

function validateInst(v: Record<string, string>) {
  const e: Record<string, string> = {}
  for (const f of FIELDS) if (f.req && !(v[f.k] || '').trim()) e[f.k] = 'Required'
  if (v.land_area && !/\d/.test(v.land_area)) e.land_area = 'Enter a number with unit, e.g. 12.5 acres'
  if (v.lease_start && v.lease_end && v.lease_end <= v.lease_start) e.lease_end = 'Must be after the start date'
  if (v.lease_term && (+v.lease_term <= 0 || +v.lease_term > 99)) e.lease_term = 'Between 1 and 99'
  return e
}

export default function Wizard() {
  const { id } = useParams(); const nav = useNavigate(); const toast = useToast()
  const [meta, setMeta] = useState<any>(null); const [app, setApp] = useState<any>(null); const [step, setStep] = useState(0)
  const [inst, setInst] = useState<Record<string, string>>({}); const [errs, setErrs] = useState<Record<string, string>>({}); const [saved, setSaved] = useState<string | null>(null)
  const [cat, setCat] = useState(''); const [busy, setBusy] = useState(false); const [cc, setCc] = useState<any>(null)
  useEffect(() => { api('/api/meta').then(setMeta) }, [])
  const loadApp = () => id && api(`/api/applications/${id}`).then(setApp)
  useEffect(() => {
    if (!id) { setApp(null); setStep(0); return }
    loadApp()
    api(`/api/wf/apps/${id}/draft`).then((d) => { setInst(d.data?.institution || {}); setStep(Math.max(1, d.step || 1)); setSaved(d.updated_at) })
  }, [id])
  const running = app?.documents.some((d: any) => d.job && !['done', 'failed'].includes(d.job.status))
  useEffect(() => { if (!running) return; const t = setInterval(loadApp, 1500); return () => clearInterval(t) }, [running])
  const docs: string[] = useMemo(() => (meta && app ? meta.categories.find((c: any) => c.id === app.category)?.docs || [] : []), [meta, app])
  const steps = ['Category', 'Institution details', ...docs.map((d) => meta?.doc_types[d]?.label || d), 'Review & submit']
  const last = steps.length - 1
  useEffect(() => { if (id && step === last && last > 1) api(`/api/wf/apps/${id}/crosscheck`).then(setCc) }, [step, last, id, app])

  const save = async (s = step, quiet = false) => {
    if (!id) return
    const r = await api(`/api/wf/apps/${id}/draft`, { method: 'PUT', json: { step: s, data: { institution: inst } } })
    setSaved(r.updated_at); if (!quiet) toast('success', 'Draft saved', 'You can close this page and resume later.')
  }
  const validStep = (s: number): string | null => {
    if (s === 1) { const e = validateInst(inst); setErrs(e); return Object.keys(e).length ? 'Please fix the highlighted fields.' : null }
    if (s >= 2 && s < last) { const dt = docs[s - 2]; return app.documents.some((d: any) => d.doc_type === dt) ? null : 'Upload this document to continue (or save the draft and come back).' }
    return null
  }
  const next = async () => { const e = validStep(step); if (e) { toast('error', 'This step is incomplete', e); return } const n = Math.min(last, step + 1); setStep(n); await save(n, true) }
  const create = async () => {
    setBusy(true)
    try { const a = await api('/api/applications', { method: 'POST', json: { category: cat } }); await api(`/api/wf/apps/${a.id}/draft`, { method: 'PUT', json: { step: 1, data: { institution: {} } } }); nav(`/apply/${a.id}`, { replace: true }) }
    catch (e: any) { toast('error', 'Could not create', e.message) } finally { setBusy(false) }
  }
  const upload = async (dt: string, f: File) => {
    const fd = new FormData(); fd.append('file', f); fd.append('doc_type', dt)
    if (dt === 'lab_photos') fd.append('lab_type', 'CCE')
    setBusy(true)
    try { await api(`/api/applications/${id}/documents`, { method: 'POST', body: fd }); toast('success', 'Uploaded', 'Verification has started.'); loadApp() }
    catch (e: any) { toast('error', 'Upload rejected', e.message) } finally { setBusy(false) }
  }
  const submit = async () => {
    for (let s = 1; s < last; s++) { const e = validStep(s); if (e) { setStep(s); toast('error', `Step ${s + 1} is incomplete`, e); return } }
    setBusy(true)
    try { await save(last, true); await api(`/api/applications/${id}/submit`, { method: 'POST' }); toast('success', 'Submitted to AICTE', 'The application has been routed to its first stage.'); nav(`/applications/${id}`) }
    catch (e: any) { toast('error', 'Could not submit', e.message) } finally { setBusy(false) }
  }
  if (!meta || (id && !app)) return <Skeleton className="h-96" />
  if (app?.submitted_at) return <div className="card card-pad text-center"><h2 className="font-display text-xl font-bold">Already submitted</h2><Link className="btn-primary mt-3" to={`/applications/${id}`}>Open application</Link></div>
  const pct = Math.round((step / Math.max(1, last)) * 100)
  return (
    <>
      <PageHeader eyebrow={`Step ${step + 1} of ${id ? steps.length : '…'}`} title="Application form" desc="A step-by-step form. Each step is checked before you move on; your progress is saved as a draft you can resume." />
      <div className="card mb-4 px-5 py-3" data-testid="wizard-progress">
        <div className="flex items-center justify-between text-xs text-muted"><span>{steps[step]}</span><span>{pct}% · {saved ? `draft saved ${fmtDate(saved)}` : 'not saved yet'}</span></div>
        <div className="mt-2 h-2 overflow-hidden rounded-full bg-surface-2" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}><div className="h-full rounded-full bg-primary transition-all" style={{ width: `${pct}%` }} /></div>
        {id && <ol className="mt-2 flex flex-wrap gap-1">{steps.map((s, i) => <li key={i}><button className={clsx('chip', i === step ? 'bg-primary text-primary-fg' : i < step ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-500/15 dark:text-emerald-300' : 'bg-surface-2 text-muted')} onClick={() => i <= step && setStep(i)}>{i + 1}. {s}</button></li>)}</ol>}
      </div>
      <div className="card card-pad" data-testid={`wizard-step-${step}`}>
        {step === 0 && !id && <>
          <div className="text-sm font-semibold">What are you applying for?</div>
          <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">{meta.categories.map((c: any) => (
            <button key={c.id} onClick={() => setCat(c.id)} aria-pressed={cat === c.id} className={clsx('card relative p-3 text-left text-sm hover:border-primary', cat === c.id && 'border-primary ring-4 ring-primary/15')}>
              {cat === c.id && <CheckCircle2 className="absolute right-2 top-2 h-4 w-4 text-primary" />}<b className="pr-5">{c.label}</b><div className="text-xs text-muted">{c.docs.length} documents</div></button>))}</div>
          <button className="btn-primary mt-4" disabled={!cat || busy} onClick={create} data-testid="wizard-create">{busy && <Loader2 className="h-4 w-4 animate-spin" />}Start form<ArrowRight className="h-4 w-4" /></button>
        </>}
        {step === 0 && id && <p className="text-sm">Category: <b>{app.category_label}</b> · {app.ref}. Continue to fill in the institution details.</p>}
        {step === 1 && <div className="grid gap-3 md:grid-cols-2">{FIELDS.map((f) => (
          <div key={f.k}><label className="label" htmlFor={`f-${f.k}`}>{f.label}{f.req && ' *'}</label>
            <input id={`f-${f.k}`} data-testid={`f-${f.k}`} type={f.type || 'text'} className={clsx('input', errs[f.k] && 'border-red-500')} placeholder={f.hint} value={inst[f.k] || ''} onChange={(e) => setInst({ ...inst, [f.k]: e.target.value })} />
            {errs[f.k] && <div className="mt-1 text-xs text-red-600">{errs[f.k]}</div>}</div>))}
          <p className="text-xs text-muted md:col-span-2">These values are compared with the text of every uploaded document (cross-document check). Differences are listed for correction before scrutiny.</p></div>}
        {step >= 2 && step < last && (() => {
          const dt = docs[step - 2]; const info = meta.doc_types[dt]; const have = app.documents.filter((d: any) => d.doc_type === dt)
          return <div>
            <div className="flex items-start gap-2"><FileText className="mt-0.5 h-5 w-5 text-primary" /><div><div className="font-semibold">{info?.label}</div><div className="text-xs text-muted">{info?.clause}</div></div></div>
            {have.map((d: any) => <div key={d.id} className="mt-3 flex items-center gap-2 text-sm"><CheckCircle2 className="h-4 w-4 text-emerald-600" />{d.filename}<StatusChip status={d.status} /></div>)}
            <label className="btn-ghost mt-4 cursor-pointer"><CloudUpload className="h-4 w-4" />{have.length ? 'Upload a corrected version' : 'Choose file'}
              <input type="file" className="hidden" data-testid="wizard-file" accept=".pdf,.jpg,.jpeg,.png" onChange={(e) => e.target.files?.[0] && upload(dt, e.target.files[0])} /></label>
            {busy && <Loader2 className="ml-2 inline h-4 w-4 animate-spin" />}
          </div>
        })()}
        {step === last && last > 1 && <div data-testid="wizard-review">
          <div className="text-sm font-semibold">Review</div>
          <ul className="mt-2 grid gap-1 text-sm md:grid-cols-2">{FIELDS.map((f) => <li key={f.k}><span className="text-muted">{f.label}:</span> {inst[f.k] || '—'}</li>)}</ul>
          <div className="mt-3 text-sm">{app.documents.length} document(s) uploaded for {docs.length} checklist items.</div>
          {cc && (cc.mismatches.length ? <div className="mt-3 rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-900 dark:bg-red-500/10 dark:text-red-200">
            <div className="flex items-center gap-2 font-semibold"><TriangleAlert className="h-4 w-4" />{cc.mismatches.length} item(s) to be corrected / re-uploaded</div>
            <ul className="mt-1 list-disc pl-5">{cc.mismatches.map((m: any, i: number) => <li key={i}>{m.field_label}: “{m.a.value}” ({m.a.source}) vs “{m.b.value}” ({m.b.source}{m.b.page ? `, p${m.b.page}` : ''})</li>)}</ul>
            <p className="mt-1 text-xs">You can still submit; officers will see the same list.</p></div>
            : <div className="mt-3 flex items-center gap-2 text-sm text-emerald-700"><CheckCircle2 className="h-4 w-4" />No cross-document mismatches found.</div>)}
        </div>}
      </div>
      {id && <div className="mt-4 flex flex-wrap items-center gap-2">
        <button className="btn-ghost" disabled={step <= 1} onClick={() => setStep(step - 1)}><ArrowLeft className="h-4 w-4" />Back</button>
        <button className="btn-ghost" data-testid="wizard-save" onClick={() => save()}><Save className="h-4 w-4" />Save draft</button>
        <span className="flex-1" />
        {step < last ? <button className="btn-primary" data-testid="wizard-next" onClick={next}>Next<ArrowRight className="h-4 w-4" /></button>
          : <button className="btn-primary" data-testid="wizard-submit" disabled={busy || running} onClick={submit}><Send className="h-4 w-4" />Submit to AICTE</button>}
      </div>}
      <div className="mt-4"><Safeguard compact /></div>
    </>
  )
}
