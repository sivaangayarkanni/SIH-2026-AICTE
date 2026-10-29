import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { CalendarClock, CheckCircle2, FileDown, ListChecks, Users } from 'lucide-react'
import { api, download, fmtDay } from '../lib/api'
import { PageHeader, Skeleton, Modal, Empty, StatusChip } from '../components/ui'
import { useToast } from '../components/Toast'
import { Safeguard } from '../components/Safeguard'
import { useAuth } from '../lib/auth'

export function EvcSummaryView({ appId }: { appId: number }) {
  const [s, setS] = useState<any>(null)
  useEffect(() => { api(`/api/wf/apps/${appId}/evc-summary`).then(setS) }, [appId])
  if (!s) return <Skeleton className="h-48" />
  const g = s.at_a_glance
  return <div data-testid="evc-summary" className="text-sm">
    <div className="grid gap-2 sm:grid-cols-2"><div><b>{s.institution.name}</b> ({s.institution.code})<div className="text-xs text-muted">{s.institution.city}, {s.institution.state} · {s.institution.region}</div></div>
      <div><span className="font-mono text-xs">{s.application.ref}</span> · {s.application.title}<div className="text-xs text-muted">Stage: {s.workflow?.current_label || s.workflow?.current_stage} · state {s.workflow?.state}</div></div></div>
    <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-5">{Object.entries(g).map(([k, v]: any) => <div key={k} className="rounded-lg bg-surface-2 p-2 text-center"><div className="text-lg font-bold">{v}</div><div className="text-[11px] text-muted">{k.replace(/_/g, ' ')}</div></div>)}</div>
    {s.mismatches.length > 0 && <><div className="mt-3 font-semibold">Cross-document mismatches</div><ul className="list-disc pl-5 text-xs">{s.mismatches.map((m: any, i: number) => <li key={i}>{m.field_label}: “{m.a.value}” vs “{m.b.value}” ({m.b.source})</li>)}</ul></>}
    <div className="mt-3 font-semibold">Documents</div>
    <ul className="text-xs">{s.documents.map((d: any, i: number) => <li key={i} className="flex items-center gap-2 py-0.5"><StatusChip status={d.status} />{d.doc_type} · {d.filename}{d.top_findings?.length ? <span className="text-muted">— {d.top_findings.join('; ')}</span> : null}</li>)}</ul>
    {s.validity.length > 0 && <><div className="mt-3 font-semibold">Validity</div><ul className="text-xs">{s.validity.map((v: any, i: number) => <li key={i}>{v.label}: until {fmtDay(v.valid_until)} ({v.days_left} d) · {v.status}</li>)}</ul></>}
    {s.undertakings.length > 0 && <><div className="mt-3 font-semibold">Undertakings</div><ul className="text-xs">{s.undertakings.map((u: any) => <li key={u.id}>{u.condition} · due {fmtDay(u.due_date)} · {u.status}</li>)}</ul></>}
    <div className="mt-3"><Safeguard compact /></div>
  </div>
}

export default function Evc() {
  const { user } = useAuth(); const toast = useToast()
  const [d, setD] = useState<any>(null); const [meta, setMeta] = useState<any>(null); const [members, setMembers] = useState<any[]>([])
  const [sched, setSched] = useState<any>(null); const [rep, setRep] = useState<any>(null); const [sum, setSum] = useState<number | null>(null)
  const [when, setWhen] = useState(''); const [sel, setSel] = useState<number[]>([]); const [chk, setChk] = useState<Record<string, string>>({}); const [remarks, setRemarks] = useState('')
  const isMember = user?.role === 'evc_member'; const decider = user?.role === 'officer' || user?.role === 'senior_officer'
  const load = () => api('/api/wf/evc').then(setD)
  useEffect(() => { load(); api('/api/wf/meta').then(setMeta); if (!isMember) api('/api/wf/evc/members').then(setMembers).catch(() => {}) }, [])
  const doSched = async () => { try { await api(`/api/wf/evc/${sched.id}/schedule`, { method: 'POST', json: { scheduled_for: when, members: sel } }); toast('success', 'Visit scheduled', 'Members and the institution were notified.'); setSched(null); load() } catch (e: any) { toast('error', 'Could not schedule', e.message) } }
  const doRep = async () => { try { await api(`/api/wf/evc/${rep.id}/report`, { method: 'POST', json: { checklist: chk, remarks } }); toast('success', 'Observations saved'); setRep(null); load() } catch (e: any) { toast('error', 'Could not save', e.message) } }
  const complete = async (v: any) => { try { await api(`/api/wf/evc/${v.id}/complete`, { method: 'POST', json: { note: '' } }); toast('success', 'Visit closed', 'The application moved to its next stage.'); load() } catch (e: any) { toast('error', 'Cannot close', e.message) } }
  if (!d) return <Skeleton className="h-96" />
  return (
    <>
      <PageHeader eyebrow="Expert Visit Committee" title={isMember ? 'My EVC visits' : 'EVC queue'} desc={isMember ? 'Record your checklist and remarks. Members record observations only; they do not decide.' : 'Schedule visits, track members\u2019 observations and close completed visits.'} />
      <Safeguard />
      <div className="card p-0" data-testid="evc-queue">
        {d.visits.length === 0 ? <div className="p-4"><Empty title="No EVC visits." /></div> :
          <table className="w-full text-sm"><thead className="table-head"><tr><th className="px-5 py-2 text-left">Application</th><th className="text-left">Status</th><th className="text-left">Visit date</th><th className="text-left">Members</th><th className="px-5 text-right">Actions</th></tr></thead>
            <tbody>{d.visits.map((v: any) => <tr key={v.id} className="border-b border-line/60 last:border-0">
              <td className="px-5 py-2.5"><Link className="font-mono text-xs text-primary" to={`/applications/${v.application_id}`}>{v.ref}</Link><div className="text-xs text-muted">{v.college}</div></td>
              <td><span className="chip bg-surface-2">{v.status.replace('_', ' ')}</span>{v.overdue && <span className="chip ml-1 bg-red-100 text-red-800">overdue</span>}</td>
              <td>{v.scheduled_for ? fmtDay(v.scheduled_for) : <span className="text-xs text-muted">schedule by {fmtDay(v.schedule_by)}</span>}</td>
              <td className="text-xs">{v.members.map((m: any) => <div key={m.id}>{m.name}{v.reports?.[m.id] ? ' ✓' : ''}</div>)}</td>
              <td className="px-5 text-right"><div className="flex flex-wrap justify-end gap-1">
                <button className="btn-ghost btn-sm" onClick={() => setSum(v.application_id)}><ListChecks className="h-3.5 w-3.5" />Summary</button>
                <button className="btn-ghost btn-sm" onClick={() => download(`/api/wf/apps/${v.application_id}/evc-summary.pdf`, `EVC-${v.ref}.pdf`)}><FileDown className="h-3.5 w-3.5" />PDF</button>
                {decider && v.status !== 'completed' && <button className="btn-ghost btn-sm" data-testid="evc-schedule" onClick={() => { setSched(v); setSel(v.members.map((m: any) => m.id)); setWhen((v.scheduled_for || '').slice(0, 16)) }}><CalendarClock className="h-3.5 w-3.5" />Schedule</button>}
                {decider && v.status === 'scheduled' && <button className="btn-primary btn-sm" data-testid="evc-complete" onClick={() => complete(v)}><CheckCircle2 className="h-3.5 w-3.5" />Close visit</button>}
                {isMember && v.status === 'scheduled' && <button className="btn-primary btn-sm" data-testid="evc-report" onClick={() => { setRep(v); setChk(v.my_report?.checklist || {}); setRemarks(v.my_report?.remarks || '') }}><Users className="h-3.5 w-3.5" />My observations</button>}
              </div></td></tr>)}</tbody></table>}
      </div>
      <Modal open={!!sched} onClose={() => setSched(null)} title={`Schedule EVC visit · ${sched?.ref}`}>
        <label className="label">Visit date & time</label><input type="datetime-local" className="input" value={when} onChange={(e) => setWhen(e.target.value)} />
        <div className="label mt-3">Members</div>{members.map((m) => <label key={m.id} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={sel.includes(m.id)} onChange={(e) => setSel(e.target.checked ? [...sel, m.id] : sel.filter((x) => x !== m.id))} />{m.name} <span className="text-xs text-muted">{m.title}</span></label>)}
        {!members.length && <div className="text-sm text-muted">No EVC member accounts exist yet. An admin can approve one in Users.</div>}
        <button className="btn-primary mt-4" disabled={!when || !sel.length} onClick={doSched}>Save schedule</button>
      </Modal>
      <Modal open={!!rep} onClose={() => setRep(null)} title={`Observations · ${rep?.ref}`} wide>
        <div className="space-y-2" data-testid="evc-checklist">{meta?.checklist.map((c: any) => <div key={c.id} className="flex items-center justify-between gap-3 text-sm"><span>{c.label}</span>
          <select className="input w-28" value={chk[c.id] || ''} onChange={(e) => setChk({ ...chk, [c.id]: e.target.value })}><option value="">—</option><option value="yes">Yes</option><option value="no">No</option><option value="na">N/A</option></select></div>)}</div>
        <label className="label mt-3">Remarks</label><textarea className="input min-h-[90px]" value={remarks} onChange={(e) => setRemarks(e.target.value)} />
        <button className="btn-primary mt-3" onClick={doRep}>Save observations</button>
      </Modal>
      <Modal open={sum !== null} onClose={() => setSum(null)} title="EVC summary" wide>{sum !== null && <EvcSummaryView appId={sum} />}</Modal>
    </>
  )
}
