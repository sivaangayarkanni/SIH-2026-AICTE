import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Upload, FileText, Image as ImageIcon, Send, CheckCircle2, XCircle, RotateCcw, ShieldAlert, Download, Gavel, Sparkles, FolderOpen, Loader2, ArrowLeft, AlertTriangle, CloudOff, Wand2, Clock, PanelLeftClose, PanelLeftOpen } from 'lucide-react'
import clsx from 'clsx'
import { api, download, fmtDate, fmtDay } from '../lib/api'
import { useAuth } from '../lib/auth'
import { WorkflowPanel } from '../components/WorkflowPanel'
import { queueUpload, uploadNow, useOnline } from '../lib/offline'
import { StatusChip, DecisionChip, RiskBadge, Ring, Skeleton, Modal, SEV } from '../components/ui'
import { DocPanel } from '../components/DocPanel'
import { Avatar } from '../components/Avatar'
import { useToast } from '../components/Toast'

export default function ApplicationDetail() {
  const { id } = useParams(); const { user } = useAuth(); const staff = ['officer', 'senior_officer', 'admin'].includes(user!.role)
  const [a, setA] = useState<any>(null); const [err, setErr] = useState(''); const [sel, setSel] = useState<number | null>(null); const [side, setSide] = useState(() => localStorage.getItem('sealcheck.side') !== 'closed')
  const load = useCallback(() => api(`/api/applications/${id}`).then((x) => { setA(x); setSel((s) => s ?? (x.documents.find((d: any) => d.status !== 'Verified') || x.documents[0])?.id ?? null) }).catch((e) => setErr(e.message)), [id])
  useEffect(() => { setA(null); setSel(null); load() }, [id])
  const running = a?.documents.some((d: any) => d.job && !['done', 'failed'].includes(d.job.status))
  useEffect(() => { if (!running) return; const t = setInterval(load, 1000); return () => clearInterval(t) }, [running, load])
  if (err) return <div className="card card-pad text-center"><h2 className="font-display text-xl font-bold">Application unavailable</h2><p className="mt-1 text-sm text-muted">{err}</p><Link className="btn-primary mt-4" to="/applications">Back to applications</Link></div>
  if (!a) return <div className="space-y-4"><Skeleton className="h-28" /><div className="grid gap-4 lg:grid-cols-[340px_1fr]"><Skeleton className="h-[600px]" /><Skeleton className="h-[600px]" /></div></div>
  const draft = !a.submitted_at
  return (
    <>
      <Link to={staff ? '/queue' : '/applications'} className="mb-3 inline-flex items-center gap-1 text-sm font-medium text-muted hover:text-primary"><ArrowLeft className="h-4 w-4" />{staff ? 'Priority queue' : 'My applications'}</Link>
      <div className="card mb-4 animate-fadeUp px-5 py-4">
        <div className="flex flex-wrap items-center gap-4">
          <Avatar seed={a.college} size={46} />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2"><h1 className="font-display text-2xl font-bold">{a.ref}</h1><StatusChip status={draft ? 'Draft' : a.status} size="lg" /><DecisionChip d={a.decision} /></div>
            <div className="mt-0.5 text-sm text-muted">{a.college}, {a.college_city} · {a.category_label} · AY {a.academic_year}</div>
          </div>
          <div className="flex items-center gap-6">
            <div><div className="text-[11px] font-semibold uppercase text-muted">Risk</div><RiskBadge score={a.risk_score} /></div>
            {staff && <div><div className="text-[11px] font-semibold uppercase text-muted">Priority</div><div className="font-display text-xl font-bold tabular-nums" title={a.priority.formula}>{a.priority.score}</div></div>}
            <div><div className="text-[11px] font-semibold uppercase text-muted">Deadline</div><div className="text-sm font-semibold">{fmtDay(a.deadline)}</div></div>
          </div>
        </div>
        <Timeline a={a} />
      </div>
      {!draft && <WorkflowPanel appId={a.id} role={user!.role} onChanged={load} />}
      <div className={clsx('grid gap-4', side && 'xl:grid-cols-[330px_1fr]')}>
        {side ? <div className="space-y-4 xl:sticky xl:top-0 xl:max-h-[calc(100vh-110px)] xl:overflow-y-auto xl:pr-1 scroll-thin" data-tour="checklist">
          <button className="btn-ghost btn-sm hidden w-full xl:flex" onClick={() => { setSide(false); localStorage.setItem('sealcheck.side', 'closed') }}><PanelLeftClose className="h-3.5 w-3.5" />Collapse checklist for a wider evidence view</button>
          <Checklist a={a} staff={staff || user!.role === 'evc_member'} sel={sel} setSel={setSel} reload={load} />
          {user!.role === 'college' && <CollegeActions a={a} reload={load} />}
          {staff && <DecisionPanel a={a} reload={load} />}
          {a.guidance && <Guidance a={a} />}
        </div> : <button className="btn-ghost btn-sm justify-self-start" onClick={() => { setSide(true); localStorage.setItem('sealcheck.side', 'open') }}><PanelLeftOpen className="h-3.5 w-3.5" />Show checklist{staff ? ' & decision panel' : ' & actions'}</button>}
        <div className="min-w-0">{sel ? <DocPanel key={sel} docId={sel} staff={staff} onChanged={load} /> : <div className="card card-pad flex h-80 flex-col items-center justify-center text-center"><FolderOpen className="h-10 w-10 text-muted" /><div className="mt-2 font-semibold">No document selected</div><p className="text-sm text-muted">{staff ? 'This application has no documents yet.' : 'Upload a document from the checklist to see its live verification.'}</p></div>}</div>
      </div>
    </>
  )
}

function Timeline({ a }: { a: any }) {
  const analysed = a.documents.length > 0 && a.documents.every((d: any) => d.job?.status === 'done')
  const steps = [
    { t: 'Created', d: fmtDate(a.created_at), on: true },
    { t: 'Documents analysed', d: `${a.documents.filter((d: any) => d.job?.status === 'done').length}/${a.documents.length} done`, on: analysed },
    { t: 'Submitted to AICTE', d: a.submitted_at ? fmtDate(a.submitted_at) : 'not yet', on: !!a.submitted_at },
    { t: 'Officer scrutiny', d: a.overrides.length ? `${a.overrides.length} override request(s)` : a.submitted_at ? 'in queue' : '—', on: !!a.submitted_at },
    { t: 'Decision', d: a.decision ? `${a.decision} · ${fmtDate(a.decided_at)}` : 'pending', on: !!a.decision },
  ]
  return (
    <ol className="mt-3 grid grid-cols-5 gap-2" aria-label="Application timeline">
      {steps.map((s) => (
        <li key={s.t} className="relative">
          <div className={clsx('h-1.5 rounded-full', s.on ? 'bg-primary' : 'bg-line')} />
          <div className="mt-2 flex items-center gap-1.5 text-xs font-semibold">{s.on ? <CheckCircle2 className="h-3.5 w-3.5 text-primary" /> : <Clock className="h-3.5 w-3.5 text-muted" />}{s.t}</div>
          <div className="truncate pl-5 text-[11px] text-muted">{s.d}</div>
        </li>
      ))}
    </ol>
  )
}

function Checklist({ a, staff, sel, setSel, reload }: any) {
  const [samples, setSamples] = useState<any[]>([]); const [picker, setPicker] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null); const [lab, setLab] = useState('Computer Lab')
  const fileRef = useRef<HTMLInputElement>(null); const target = useRef<string>('')
  const online = useOnline(); const toast = useToast()
  const canUpload = !staff && !a.decision
  useEffect(() => { if (canUpload) api('/api/samples').then(setSamples).catch(() => {}) }, [canUpload])
  const send = async (docType: string, blob: Blob, name: string) => {
    setBusy(docType)
    try {
      if (!navigator.onLine) {
        await queueUpload({ appId: a.id, docType, labType: docType === 'lab_photos' ? lab : undefined, name, type: blob.type, blob, queuedAt: new Date().toISOString() })
        toast('info', 'Saved offline', `${name} is queued in this browser and will upload automatically when you are back online.`)
      } else {
        const r = await uploadNow(a.id, docType, blob, name, docType === 'lab_photos' ? lab : undefined)
        toast('success', 'Upload accepted', `Passed the gateway (${r.gateway.malware_scan.engine}). Sandbox analysis started.`)
        setSel(r.document.id)
      }
      await reload()
    } catch (e: any) { toast('error', 'Upload rejected', e.message) } finally { setBusy(null); setPicker(null) }
  }
  const pickFile = (dt: string) => { target.current = dt; fileRef.current?.click() }
  const loadSample = async (name: string, dt: string) => { setBusy(dt); try { const b = await api<Blob>(`/api/samples/${name}`); await send(dt, b, name) } catch (e: any) { toast('error', 'Sample unavailable', e.message); setBusy(null) } }
  const others = a.documents.filter((d: any) => !a.readiness.items.some((i: any) => i.doc_type === d.doc_type))
  return (
    <div className="card">
      <div className="flex items-center gap-4 border-b border-line p-4">
        <Ring value={a.readiness.score} size={72} stroke={8} label="ready" />
        <div className="min-w-0"><div className="text-sm font-semibold">Document checklist</div><p className="mt-0.5 text-xs leading-relaxed text-muted">{a.readiness.explanation}</p></div>
      </div>
      {!online && canUpload && <div className="flex items-center gap-2 border-b border-line bg-amber-50 px-5 py-2 text-xs text-amber-900 dark:bg-amber-500/10 dark:text-amber-200"><CloudOff className="h-4 w-4" />Offline — new uploads are queued on this device.</div>}
      {canUpload && a.readiness.items.some((i: any) => i.doc_type === 'lab_photos') && (
        <div className="border-b border-line px-5 py-3"><label className="label" htmlFor="lab">Lab type for photo uploads</label>
          <select id="lab" className="input py-2" value={lab} onChange={(e) => setLab(e.target.value)}>{['Computer Lab', 'Electronics Lab', 'Mechanical Workshop', 'Civil Engineering Lab', 'Electrical Machines Lab', 'Chemistry Lab'].map((l) => <option key={l}>{l}</option>)}</select></div>
      )}
      <input ref={fileRef} type="file" className="hidden" accept=".pdf,image/jpeg,image/png" onChange={(e) => { const f = e.target.files?.[0]; if (f) send(target.current, f, f.name); e.target.value = '' }} />
      <ul className="divide-y divide-line">
        {a.readiness.items.map((it: any) => {
          const docs = a.documents.filter((d: any) => d.doc_type === it.doc_type)
          const sm = samples.filter((s) => s.doc_type === it.doc_type)
          return (
            <li key={it.doc_type} className="px-4 py-2.5">
              <div className="flex items-center gap-2">
                {it.doc_type === 'lab_photos' ? <ImageIcon className="h-4 w-4 shrink-0 text-muted" /> : <FileText className="h-4 w-4 shrink-0 text-muted" />}
                <span className="min-w-0 flex-1 break-words text-sm font-semibold leading-snug" title={it.label}>{it.label}</span>
                {it.state === 'missing' ? <span className="chip bg-red-100 text-red-800 dark:bg-red-500/15 dark:text-red-300">Missing</span> : <StatusChip status={it.state} />}
              </div>
              {docs.map((d: any) => (
                <button key={d.id} onClick={() => setSel(d.id)} className={clsx('mt-2 flex w-full items-center gap-2 rounded-lg border px-2.5 py-1.5 text-left text-xs transition', sel === d.id ? 'border-primary bg-primary-soft/70' : 'border-line hover:bg-surface-2')}>
                  {d.job && !['done', 'failed'].includes(d.job.status) ? <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" /> : d.findings_count ? <AlertTriangle className="h-3.5 w-3.5 text-amber-500" /> : <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />}
                  <span className="min-w-0 flex-1 truncate">{d.filename}</span>{d.findings_count > 0 && <span className="text-muted">{d.findings_count} issue(s)</span>}
                </button>
              ))}
              {canUpload && (
                <div className="mt-2 flex gap-1.5">
                  <button className="btn-ghost btn-sm flex-1" disabled={!!busy} onClick={() => pickFile(it.doc_type)}>{busy === it.doc_type ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />}{docs.length ? 'Upload new version' : 'Upload file'}</button>
                  {sm.length > 0 && <button className="btn-ghost btn-sm" disabled={!!busy} onClick={() => setPicker(picker === it.doc_type ? null : it.doc_type)} title="Use a synthetic demo file"><Sparkles className="h-3.5 w-3.5" />Sample</button>}
                </div>
              )}
              {picker === it.doc_type && (
                <div className="mt-2 space-y-1 rounded-xl border border-dashed border-primary/50 bg-primary-soft/40 p-2 animate-fadeUp">
                  <div className="px-1 text-[10.5px] font-semibold uppercase tracking-wide text-muted">Synthetic demo files</div>
                  {sm.map((s) => <button key={s.file} className="block w-full rounded-lg px-2 py-1.5 text-left text-xs hover:bg-surface" onClick={() => loadSample(s.file, it.doc_type)}><b>{s.file}</b><span className="block text-muted">{s.story} · expected: {s.expected_status}</span></button>)}
                </div>
              )}
            </li>
          )
        })}
        {others.map((d: any) => <li key={d.id} className="px-5 py-3"><button onClick={() => setSel(d.id)} className="flex w-full items-center gap-2 text-left text-sm"><FileText className="h-4 w-4 text-muted" /><span className="flex-1 truncate">{d.label}</span><StatusChip status={d.status} /></button></li>)}
      </ul>
    </div>
  )
}

function CollegeActions({ a, reload }: any) {
  const toast = useToast(); const [busy, setBusy] = useState(false)
  if (a.decision === 'Changes Requested') return (
    <div className="card card-pad"><div className="text-sm font-semibold">Changes requested by AICTE</div><p className="mt-1 text-sm text-muted">{a.decision_reason}</p>
      <button className="btn-primary mt-3 w-full" onClick={() => api(`/api/applications/${a.id}/reopen`, { method: 'POST' }).then(() => { toast('success', 'Application reopened', 'Upload corrected documents, then resubmit.'); reload() }).catch((e) => toast('error', 'Could not reopen', e.message))}><RotateCcw className="h-4 w-4" />Reopen to fix and resubmit</button></div>
  )
  if (a.decision) return <div className="card card-pad"><div className="flex items-center gap-2 text-sm font-semibold">Decision: <DecisionChip d={a.decision} /></div><p className="mt-1 text-sm text-muted">{a.decision_reason}</p><button className="btn-ghost mt-3 w-full" onClick={() => download(`/api/applications/${a.id}/decision.pdf`, `${a.ref}_decision.pdf`)}><Download className="h-4 w-4" />Decision letter (PDF)</button></div>
  if (a.submitted_at) return <div className="card card-pad"><div className="flex items-center gap-2 text-sm font-semibold"><CheckCircle2 className="h-4 w-4 text-emerald-500" />Submitted {fmtDate(a.submitted_at)}</div><p className="mt-1 text-xs text-muted">You can still upload newer versions until an officer records a decision.</p></div>
  return (
    <div className="card card-pad">
      <div className="text-sm font-semibold">Ready to submit?</div>
      <p className="mt-1 text-xs text-muted">{a.readiness.complete ? 'All required documents are uploaded.' : `${a.readiness.missing.length} required document(s) still missing. You can submit, but the application will stay "Verification Pending".`}</p>
      <button className="btn-primary mt-3 w-full" disabled={busy || !a.documents.length} onClick={async () => { setBusy(true); try { await api(`/api/applications/${a.id}/submit`, { method: 'POST' }); toast('success', 'Submitted to AICTE', 'Officers have been notified.'); reload() } catch (e: any) { toast('error', 'Submit failed', e.message) } finally { setBusy(false) } }}><Send className="h-4 w-4" />Submit application</button>
    </div>
  )
}

function DecisionPanel({ a, reload }: any) {
  const { user } = useAuth(); const toast = useToast()
  const [reason, setReason] = useState(''); const [busy, setBusy] = useState<string | null>(null)
  const [ov, setOv] = useState(false); const [rh, setRh] = useState(false)
  const canDecide = ['officer', 'senior_officer'].includes(user!.role)
  const flagged = a.documents.filter((d: any) => d.status === 'Mismatch Detected')
  const cleared = new Set(a.overrides.filter((o: any) => o.status === 'approved').map((o: any) => o.document_id))
  const blocked = flagged.filter((d: any) => !cleared.has(d.id))
  const decide = async (decision: string) => {
    setBusy(decision)
    try { await api(`/api/applications/${a.id}/decision`, { method: 'POST', json: { decision, reason } }); toast('success', 'Decision recorded', 'Signed into the hash-chained audit log; the college has been notified.'); setReason(''); reload() }
    catch (e: any) { toast('error', 'Decision blocked', e.message) } finally { setBusy(null) }
  }
  return (
    <div className="card" data-tour="decision">
      <div className="flex items-center gap-2 border-b border-line px-5 py-3.5"><Gavel className="h-4 w-4 text-primary" /><span className="text-sm font-semibold">Officer decision</span></div>
      <div className="space-y-3 p-5">
        {a.decision ? (<>
          <div className="flex items-center gap-2"><DecisionChip d={a.decision} /><span className="text-xs text-muted">{fmtDate(a.decided_at)}</span></div>
          {a.decision_by && <div className="flex items-center gap-2 text-sm"><Avatar seed={a.decision_by.avatar_seed} size={26} />{a.decision_by.name}</div>}
          <p className="rounded-xl bg-surface-2 p-3 text-sm">{a.decision_reason}</p>
          <button className="btn-ghost w-full" onClick={() => download(`/api/applications/${a.id}/decision.pdf`, `${a.ref}_decision.pdf`)}><Download className="h-4 w-4" />Decision letter (PDF)</button>
        </>) : !a.submitted_at ? <p className="text-sm text-muted">The college has not submitted this application yet.</p> : !canDecide ? <p className="text-sm text-muted">Your role ({user!.role_label}) can view but not decide. Decisions are made by Scrutiny or Senior Officers.</p> : (<>
          {blocked.length > 0 && <div className="rounded-xl border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200"><b>{blocked.length} document(s) flagged as possible forgery.</b> Approval is locked until a two-person security override is approved by a different Senior Officer.</div>}
          <label className="label" htmlFor="reason">Reason (recorded in the audit log)</label>
          <textarea id="reason" className="input min-h-[90px]" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Explain the decision in plain words, citing rule IDs where possible." />
          <div className="grid grid-cols-3 gap-2">
            <button className="btn bg-emerald-600 text-white hover:bg-emerald-700 btn-sm py-2" disabled={!!busy || reason.trim().length < 5} onClick={() => decide('approve')} title={blocked.length ? 'Needs approved security override' : ''}>{busy === 'approve' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle2 className="h-3.5 w-3.5" />}Approve</button>
            <button className="btn bg-amber-500 text-white hover:bg-amber-600 btn-sm py-2" disabled={!!busy || reason.trim().length < 5} onClick={() => decide('request_changes')}><RotateCcw className="h-3.5 w-3.5" />Changes</button>
            <button className="btn-danger btn-sm py-2" disabled={!!busy || reason.trim().length < 5} onClick={() => decide('reject')}><XCircle className="h-3.5 w-3.5" />Reject</button>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <button className="btn-ghost btn-sm" onClick={() => setRh(true)}><Wand2 className="h-3.5 w-3.5" />Rejection helper</button>
            <button data-tour="override" className="btn-ghost btn-sm" disabled={!flagged.length} onClick={() => setOv(true)} title={flagged.length ? '' : 'Only for documents with Mismatch Detected'}><ShieldAlert className="h-3.5 w-3.5" />Request override</button>
          </div>
        </>)}
        {a.overrides.length > 0 && <div className="space-y-2 border-t border-line pt-3"><div className="text-xs font-semibold uppercase tracking-wide text-muted">Security overrides</div>{a.overrides.map((o: any) => <div key={o.id} className="rounded-lg border border-line p-2.5 text-xs"><div className="flex items-center justify-between"><b>{o.document}</b><span className={clsx('chip', o.status === 'approved' ? 'bg-emerald-100 text-emerald-800' : o.status === 'rejected' ? 'bg-red-100 text-red-800' : 'bg-amber-100 text-amber-900')}>{o.status}</span></div><div className="mt-1 text-muted">by {o.requested_by.name}{o.approved_by && ` · ${o.status} by ${o.approved_by.name}`}</div></div>)}<Link to="/overrides" className="text-xs font-semibold text-primary">Open overrides →</Link></div>}
      </div>
      <OverrideModal open={ov} onClose={() => setOv(false)} a={a} flagged={flagged} reload={reload} />
      <RejectionHelper open={rh} onClose={() => setRh(false)} a={a} reload={reload} />
    </div>
  )
}

function OverrideModal({ open, onClose, a, flagged, reload }: any) {
  const toast = useToast(); const [doc, setDoc] = useState<number>(0); const [j, setJ] = useState(''); const [busy, setBusy] = useState(false)
  useEffect(() => { if (open) { setDoc(flagged[0]?.id || 0); setJ('') } }, [open])
  const submit = async () => {
    setBusy(true)
    try { await api(`/api/applications/${a.id}/overrides`, { method: 'POST', json: { document_id: doc, justification: j } }); toast('success', 'Override requested', 'A different Senior Officer must approve it. You cannot approve your own request.'); onClose(); reload() }
    catch (e: any) { toast('error', 'Override not created', e.message) } finally { setBusy(false) }
  }
  return (
    <Modal open={open} onClose={onClose} title="Request a two-person security override">
      <div className="space-y-4">
        <div className="flex gap-3 rounded-xl bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-500/10 dark:text-amber-200"><ShieldAlert className="h-5 w-5 shrink-0" /><span>Use only when you have independently confirmed the document is genuine (for example, by calling the issuer). Your request and justification are permanently written to the hash-chained audit log.</span></div>
        <div><label className="label" htmlFor="od">Flagged document</label><select id="od" className="input" value={doc} onChange={(e) => setDoc(+e.target.value)}>{flagged.map((d: any) => <option key={d.id} value={d.id}>{d.label} — {d.filename}</option>)}</select></div>
        <div><label className="label" htmlFor="oj">Justification (at least 20 characters)</label><textarea id="oj" className="input min-h-[110px]" value={j} onChange={(e) => setJ(e.target.value)} placeholder="e.g. Verified with the Sub-Registrar office by phone on 28 Oct; the white box covered a stamp, not data." /><div className={clsx('mt-1 text-right text-xs', j.trim().length >= 20 ? 'text-emerald-600' : 'text-muted')}>{j.trim().length}/20</div></div>
        <div className="flex justify-end gap-2"><button className="btn-ghost" onClick={onClose}>Cancel</button><button className="btn-primary" disabled={busy || j.trim().length < 20 || !doc} onClick={submit}>{busy && <Loader2 className="h-4 w-4 animate-spin" />}Submit for second approval</button></div>
      </div>
    </Modal>
  )
}

function RejectionHelper({ open, onClose, a, reload }: any) {
  const toast = useToast(); const [r, setR] = useState('The application cannot be approved in its current form. Please address each item below and resubmit.'); const [busy, setBusy] = useState(false)
  const gen = async () => {
    setBusy(true)
    try { await api(`/api/applications/${a.id}/rejection-helper`, { method: 'POST', json: { reason: r } }); toast('success', 'Guidance generated', 'The college sees these step-by-step fixes on their dashboard.'); onClose(); reload() }
    catch (e: any) { toast('error', 'Could not generate', e.message) } finally { setBusy(false) }
  }
  return (
    <Modal open={open} onClose={onClose} title="Rejection helper">
      <p className="text-sm text-muted">Turns every failed or warning finding (and every missing document) into a plain-language fix for the college, with rule IDs and page numbers. Generated by rules, not by AI.</p>
      <label className="label mt-4" htmlFor="rr">Covering note</label><textarea id="rr" className="input min-h-[90px]" value={r} onChange={(e) => setR(e.target.value)} />
      <div className="mt-4 flex justify-end gap-2"><button className="btn-ghost" onClick={onClose}>Cancel</button><button className="btn-primary" disabled={busy || r.trim().length < 10} onClick={gen}>{busy && <Loader2 className="h-4 w-4 animate-spin" />}Generate guidance</button></div>
    </Modal>
  )
}

function Guidance({ a }: any) {
  const g = a.guidance
  return (
    <div className="card">
      <div className="flex items-center justify-between border-b border-line px-5 py-3.5"><span className="flex items-center gap-2 text-sm font-semibold"><Wand2 className="h-4 w-4 text-primary" />How to fix ({g.items.length})</span>
        <button className="btn-ghost btn-sm" onClick={() => download(`/api/applications/${a.id}/rejection.pdf`, `${a.ref}_guidance.pdf`)}><Download className="h-3.5 w-3.5" />PDF</button></div>
      <div className="space-y-2 p-5">
        <p className="text-xs text-muted">{g.reason} — {g.by}, {fmtDate(g.at)}</p>
        {g.items.map((it: any, i: number) => <div key={i} className="rounded-xl border border-line p-3 text-sm"><div className="flex items-start gap-2"><span className={clsx('chip px-1.5 py-0 text-[10px] uppercase', SEV[it.severity] || SEV.medium)}>{it.severity}</span><b className="flex-1">{it.document}: {it.issue}</b></div><p className="mt-1 text-xs text-muted">{it.action}</p><div className="mt-1 text-[10.5px] text-muted"><span className="kbd">{it.rule_id}</span>{it.page && ` · page ${it.page}`}</div></div>)}
      </div>
    </div>
  )
}
