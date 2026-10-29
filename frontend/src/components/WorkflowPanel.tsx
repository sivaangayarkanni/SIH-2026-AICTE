import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, CheckCircle2, Circle, CornerUpLeft, FileDown, GitBranch, RotateCcw, Send, TriangleAlert, Undo2 } from 'lucide-react'
import clsx from 'clsx'
import { api, download, fmtDate, fmtDay } from '../lib/api'
import { useToast } from './Toast'
import { Modal } from './ui'
import { Safeguard } from './Safeguard'

export function WorkflowPanel({ appId, role, onChanged }: { appId: number; role: string; onChanged?: () => void }) {
  const [d, setD] = useState<any>(null); const [modal, setModal] = useState<'' | 'return' | 'revert' | 'advance'>(''); const [text, setText] = useState(''); const [busy, setBusy] = useState(false)
  const toast = useToast()
  const load = () => api(`/api/wf/apps/${appId}`).then(setD).catch(() => setD({ error: true }))
  useEffect(() => { load() }, [appId])
  if (!d) return <div className="skeleton mb-4 h-24" />
  if (d.error) return null
  const w = d.workflow; const staff = ['officer', 'senior_officer', 'admin'].includes(role)
  const mm = d.crosscheck?.mismatches || []
  const act = async (path: string, body: any, ok: string) => {
    setBusy(true)
    try { const r = await api(`/api/wf/apps/${appId}/${path}`, { method: 'POST', json: body }); setD(r); toast('success', ok); setModal(''); setText(''); onChanged?.() }
    catch (e: any) { toast('error', 'Not allowed', e.message) } finally { setBusy(false) }
  }
  return (
    <div className="card mb-4 px-5 py-4" data-testid="workflow-panel">
      <div className="flex flex-wrap items-center gap-2">
        <GitBranch className="h-4 w-4 text-primary" /><span className="text-sm font-semibold">Approval workflow</span>
        {w ? <><span className="chip bg-surface-2 text-muted">Route: {w.route_label}</span><span className="chip bg-surface-2 text-muted">{w.region_name}</span>
          <span className={clsx('chip', w.state === 'returned' ? 'bg-amber-100 text-amber-800' : w.state === 'completed' ? 'bg-emerald-100 text-emerald-800' : w.overdue ? 'bg-red-100 text-red-800' : 'bg-sky-100 text-sky-800')} data-testid="wf-state">
            {w.state === 'returned' ? 'With institution for correction' : w.state === 'awaiting_decision' ? 'Awaiting competent authority decision' : w.state === 'completed' ? 'Completed' : w.overdue ? `Overdue (due ${fmtDay(w.stage_due_at)})` : `Due ${fmtDay(w.stage_due_at)}`}</span></>
          : <span className="chip bg-surface-2 text-muted">Not routed yet · will follow “{d.route_preview?.label}” on submission</span>}
        <span className="flex-1" />
        {staff && w && w.state === 'active' && <>
          <button className="btn-primary btn-sm" data-testid="wf-advance" onClick={() => setModal('advance')}><ArrowRight className="h-3.5 w-3.5" />Complete {w.current_label}</button>
          <button className="btn-ghost btn-sm" data-testid="wf-return" onClick={() => { setText(mm.length ? `Cross-document mismatches: ${mm.map((m: any) => m.field_label).join(', ')}` : ''); setModal('return') }}><CornerUpLeft className="h-3.5 w-3.5" />Return to institution</button>
        </>}
        {staff && w && w.stage_index > 0 && w.state !== 'completed' && <button className="btn-ghost btn-sm" data-testid="wf-revert" onClick={() => setModal('revert')}><Undo2 className="h-3.5 w-3.5" />Revert stage</button>}
        {(staff || role === 'evc_member') && <button className="btn-ghost btn-sm" onClick={() => download(`/api/wf/apps/${appId}/evc-summary.pdf`, `EVC_summary_${appId}.pdf`)}><FileDown className="h-3.5 w-3.5" />EVC summary PDF</button>}
        {role === 'college' && w?.state === 'returned' && <button className="btn-primary btn-sm" data-testid="wf-resubmit" onClick={() => act('resubmit', { note: 'Corrected and re-uploaded' }, 'Resubmitted to AICTE')}><RotateCcw className="h-3.5 w-3.5" />Resubmit after correction</button>}
      </div>
      {w && <ol className="mt-3 flex flex-wrap items-center gap-1.5" data-testid="wf-stages">{w.stages.map((s: any, i: number) => (
        <li key={s.id} className="flex items-center gap-1.5">
          <span className={clsx('chip', s.done ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-500/15 dark:text-emerald-300' : s.current ? 'bg-primary text-primary-fg' : 'bg-surface-2 text-muted')}>
            {s.done ? <CheckCircle2 className="h-3.5 w-3.5" /> : <Circle className="h-3.5 w-3.5" />}{s.label}</span>
          {i < w.stages.length - 1 && <ArrowRight className="h-3.5 w-3.5 text-muted" />}
        </li>))}</ol>}
      {w?.state === 'returned' && <div className="mt-3 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:bg-amber-500/10 dark:text-amber-200"><b>Returned for correction:</b> {w.return_reason}</div>}
      {mm.length > 0 && <div className="mt-3" data-testid="crosscheck">
        <div className="flex items-center gap-2 text-sm font-semibold text-red-700 dark:text-red-300"><TriangleAlert className="h-4 w-4" />{mm.length} cross-document mismatch{mm.length > 1 ? 'es' : ''} · to be corrected / re-uploaded by the institution
          {staff && <button className="btn-ghost btn-sm ml-auto" data-testid="cc-notify" onClick={() => api(`/api/wf/apps/${appId}/crosscheck/notify`, { method: 'POST' }).then((r) => toast('success', r.sent ? 'Mismatch notice sent to the institution' : 'Already sent', `${r.mismatches} item(s)`)).catch((e) => toast('error', 'Failed', e.message))}><Send className="h-3.5 w-3.5" />Notify institution</button>}</div>
        <div className="mt-2 overflow-x-auto"><table className="w-full text-sm"><thead><tr className="table-head"><th className="py-1.5">Field</th><th>Value A (source · page)</th><th>Value B (source · page)</th><th>Action</th></tr></thead>
          <tbody>{mm.map((m: any, i: number) => <tr key={i} className="border-t border-line align-top">
            <td className="py-1.5 font-medium">{m.field_label}{m.within_document && <span className="chip ml-1 bg-red-100 text-red-800">within one document</span>}</td>
            <td><span className="font-mono">{m.a.value}</span><div className="text-xs text-muted">{m.a.source}{m.a.page ? ` · p${m.a.page}` : ''}{m.a.hidden ? ' · hidden text' : ''}</div></td>
            <td><span className="font-mono">{m.b.value}</span><div className="text-xs text-muted">{m.b.source}{m.b.page ? ` · p${m.b.page}` : ''}{m.b.hidden ? ' · hidden text' : ''}</div></td>
            <td className="text-xs">{m.action}</td></tr>)}</tbody></table></div>
        <p className="mt-1 text-xs text-muted">{d.crosscheck.note}</p>
      </div>}
      {mm.length === 0 && d.crosscheck?.fields?.length > 0 && <div className="mt-3 flex items-center gap-2 text-sm text-emerald-700 dark:text-emerald-300" data-testid="crosscheck-ok"><CheckCircle2 className="h-4 w-4" />Core fields consistent across {d.crosscheck.sources.length} sources ({d.crosscheck.fields.map((f: any) => f.label).join(', ')})</div>}
      {w && w.history.length > 0 && <details className="mt-3"><summary className="cursor-pointer text-xs font-semibold uppercase tracking-wide text-muted">Stage history ({w.history.length})</summary>
        <ul className="mt-2 space-y-1 text-sm">{w.history.map((h: any, i: number) => <li key={i}><span className="font-mono text-xs text-muted">{fmtDate(h.at)}</span> · <b>{h.action}</b> {h.from_label && <>{h.from_label} → </>}{h.to_label || (h.to === 'institution' ? 'institution' : '')}{h.reason && <> — <i>{h.reason}</i></>} <span className="text-xs text-muted">({h.actor})</span></li>)}</ul></details>}
      {(d.evc_visits?.length > 0 || d.undertakings?.length > 0) && <div className="mt-2 flex flex-wrap gap-2 text-xs">
        {d.evc_visits.map((v: any) => <Link key={v.id} to="/evc" className="chip bg-purple-100 text-purple-800 dark:bg-purple-500/15 dark:text-purple-300">EVC visit: {v.status}{v.scheduled_for ? ` · ${fmtDay(v.scheduled_for)}` : ''}</Link>)}
        {d.undertakings.map((u: any) => <Link key={u.id} to="/compliance" className={clsx('chip', u.overdue ? 'bg-red-100 text-red-800' : 'bg-emerald-100 text-emerald-800')}>Undertaking #{u.id}: {u.status}</Link>)}
      </div>}
      <div className="mt-3"><Safeguard compact /></div>
      <Modal open={!!modal} onClose={() => setModal('')} title={modal === 'return' ? 'Return to institution' : modal === 'revert' ? 'Revert to the previous stage' : `Complete ${w?.current_label}`}>
        <label className="label" htmlFor="wf-text">{modal === 'advance' ? 'Note (optional)' : 'Reason (recorded in the audit trail)'}</label>
        <textarea id="wf-text" data-testid="wf-text" className="input min-h-[90px]" value={text} onChange={(e) => setText(e.target.value)} />
        <p className="mt-2 text-xs text-muted">{modal === 'advance' ? 'The application moves automatically to the next configured stage.' : 'A reason of at least 5 characters is required.'}</p>
        <div className="mt-3 flex justify-end gap-2"><button className="btn-ghost" onClick={() => setModal('')}>Cancel</button>
          <button className="btn-primary" data-testid="wf-confirm" disabled={busy || (modal !== 'advance' && text.trim().length < 5)} onClick={() => modal === 'advance' ? act('advance', { note: text }, 'Stage completed') : modal === 'return' ? act('return', { reason: text, items: mm.map((m: any) => m.field_label) }, 'Returned to the institution') : act('revert', { reason: text }, 'Stage reverted')}>Confirm</button></div>
      </Modal>
    </div>
  )
}
