import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ShieldAlert, CheckCircle2, XCircle, Loader2, ArrowRight } from 'lucide-react'
import clsx from 'clsx'
import { api, fmtDate } from '../lib/api'
import { useAuth } from '../lib/auth'
import { PageHeader, Skeleton, Empty, Modal } from '../components/ui'
import { Avatar } from '../components/Avatar'
import { useToast } from '../components/Toast'

export default function Overrides() {
  const { user } = useAuth(); const toast = useToast()
  const [list, setList] = useState<any[] | null>(null); const [act, setAct] = useState<{ o: any; approve: boolean } | null>(null); const [note, setNote] = useState(''); const [busy, setBusy] = useState(false)
  const load = () => api('/api/overrides').then(setList)
  useEffect(() => { load() }, [])
  const go = async () => {
    setBusy(true)
    try { await api(`/api/overrides/${act!.o.id}/${act!.approve ? 'approve' : 'reject'}`, { method: 'POST', json: { note } }); toast('success', act!.approve ? 'Override approved' : 'Override rejected', 'Recorded in the audit chain.'); setAct(null); setNote(''); load() }
    catch (e: any) { toast('error', 'Action blocked', e.message) } finally { setBusy(false) }
  }
  return (
    <>
      <PageHeader eyebrow="Two-person rule" title="Security overrides" desc="A flagged forgery can only be cleared when one officer requests an override and a different Senior Officer approves it. Nobody can approve their own request." />
      <div data-tour="overrides">
      {!list ? <Skeleton className="h-60" /> : list.length === 0 ? <Empty icon={ShieldAlert} title="No override requests" body="Requests appear here when an officer asks to clear a document flagged as Mismatch Detected." /> : (
        <div className="space-y-3">{list.map((o) => {
          const mine = o.requested_by.id === user!.id
          return (
            <div key={o.id} className="card card-pad animate-fadeUp">
              <div className="flex flex-wrap items-start gap-4">
                <Avatar seed={o.requested_by.avatar_seed} size={42} />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2"><b>{o.document}</b><span className={clsx('chip', o.status === 'approved' ? 'bg-emerald-100 text-emerald-800' : o.status === 'rejected' ? 'bg-red-100 text-red-800' : 'bg-amber-100 text-amber-900')}>{o.status}</span><span className="text-xs text-muted">→ proposed: {o.proposed_status}</span></div>
                  <div className="text-xs text-muted">Requested by {o.requested_by.name} ({o.requested_by.role_label}) · {fmtDate(o.created_at)}</div>
                  <p className="mt-2 rounded-xl bg-surface-2 p-3 text-sm">“{o.justification}”</p>
                  {o.approved_by && <div className="mt-2 flex items-center gap-2 text-sm"><Avatar seed={o.approved_by.avatar_seed} size={24} /><span><b>{o.approved_by.name}</b> {o.status}: {o.approver_note}</span></div>}
                </div>
                <div className="flex flex-col gap-2">
                  <Link to={`/applications/${o.application_id}`} className="btn-ghost btn-sm">Open application<ArrowRight className="h-3.5 w-3.5" /></Link>
                  {o.status === 'pending' && user!.role === 'senior_officer' && (mine ? <span className="max-w-[180px] text-xs text-muted">You requested this — a different Senior Officer must decide.</span> : <>
                    <button className="btn btn-sm bg-emerald-600 text-white hover:bg-emerald-700" onClick={() => setAct({ o, approve: true })}><CheckCircle2 className="h-3.5 w-3.5" />Approve</button>
                    <button className="btn-danger btn-sm" onClick={() => setAct({ o, approve: false })}><XCircle className="h-3.5 w-3.5" />Reject</button></>)}
                  {o.status === 'pending' && user!.role !== 'senior_officer' && <span className="max-w-[180px] text-xs text-muted">Awaiting a Senior Officer.</span>}
                </div>
              </div>
            </div>
          )
        })}</div>
      )}
      <Modal open={!!act} onClose={() => setAct(null)} title={act?.approve ? 'Approve security override' : 'Reject security override'}>
        <p className="text-sm text-muted">{act?.approve ? 'Approving lets the requesting officer approve the application despite the forgery flag. Only do this if you agree the evidence has been explained.' : 'The flag stays in place and the application cannot be approved.'}</p>
        <label className="label mt-4" htmlFor="n">Your note</label><textarea id="n" className="input min-h-[90px]" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Reason for your decision (at least 5 characters)" />
        <div className="mt-4 flex justify-end gap-2"><button className="btn-ghost" onClick={() => setAct(null)}>Cancel</button><button className={act?.approve ? 'btn bg-emerald-600 text-white' : 'btn-danger'} disabled={busy || note.trim().length < 5} onClick={go}>{busy && <Loader2 className="h-4 w-4 animate-spin" />}Confirm</button></div>
      </Modal>
      </div>
    </>
  )
}
