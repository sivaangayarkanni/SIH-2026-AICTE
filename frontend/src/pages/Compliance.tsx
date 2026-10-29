import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { CheckCircle2, CloudUpload, FileDown, Plus, XCircle } from 'lucide-react'
import clsx from 'clsx'
import { api, download, fmtDay } from '../lib/api'
import { PageHeader, Skeleton, Tabs, Modal, Empty } from '../components/ui'
import { useToast } from '../components/Toast'
import { Safeguard } from '../components/Safeguard'
import { useAuth } from '../lib/auth'

const TONE: Record<string, string> = { open: 'bg-amber-100 text-amber-800', submitted: 'bg-blue-100 text-blue-800', verified: 'bg-emerald-100 text-emerald-800', rejected: 'bg-red-100 text-red-800', valid: 'bg-emerald-100 text-emerald-800', renewal_submitted: 'bg-blue-100 text-blue-800', renewed: 'bg-emerald-100 text-emerald-800', expired: 'bg-red-100 text-red-800' }

export default function Compliance() {
  const { user } = useAuth(); const toast = useToast(); const [tab, setTab] = useState('undertakings')
  const [ut, setUt] = useState<any[] | null>(null); const [dv, setDv] = useState<any[] | null>(null)
  const [up, setUp] = useState<any>(null); const [file, setFile] = useState<File | null>(null); const [note, setNote] = useState(''); const [until, setUntil] = useState('')
  const [ver, setVer] = useState<any>(null); const [remark, setRemark] = useState(''); const [add, setAdd] = useState(false); const [nu, setNu] = useState<any>({ application_id: '', condition: '', evidence_required: '', due_date: '' })
  const college = user?.role === 'college'; const decider = user?.role === 'officer' || user?.role === 'senior_officer'
  const load = () => { api('/api/wf/undertakings').then(setUt); api('/api/wf/validity').then(setDv) }
  useEffect(load, [])
  const submit = async () => {
    const fd = new FormData(); fd.append('file', file!); fd.append('note', note); if (up.kind === 'dv') fd.append('valid_until', until)
    try { await api(up.kind === 'ut' ? `/api/wf/undertakings/${up.x.id}/submit` : `/api/wf/validity/${up.x.id}/renew`, { method: 'POST', body: fd }); toast('success', 'Evidence submitted', 'An officer will verify it.'); setUp(null); setFile(null); load() }
    catch (e: any) { toast('error', 'Upload rejected', e.message) }
  }
  const verify = async (accept: boolean) => {
    try { await api(ver.kind === 'ut' ? `/api/wf/undertakings/${ver.x.id}/verify` : `/api/wf/validity/${ver.x.id}/verify`, { method: 'POST', json: { accept, remark } }); toast('success', accept ? 'Verified' : 'Sent back'); setVer(null); setRemark(''); load() }
    catch (e: any) { toast('error', 'Could not record', e.message) }
  }
  const create = async () => {
    try { await api('/api/wf/undertakings', { method: 'POST', json: { ...nu, application_id: +nu.application_id } }); toast('success', 'Undertaking recorded'); setAdd(false); load() }
    catch (e: any) { toast('error', 'Could not create', e.message) }
  }
  const Subs = ({ x }: { x: any }) => <>{x.submissions.map((c: any) => <button key={c.id} className="mr-1 inline-flex items-center gap-1 text-xs text-primary hover:underline" onClick={() => download(`/api/wf/compliance/${c.id}/file`, c.filename)}><FileDown className="h-3 w-3" />{c.filename}</button>)}</>
  if (!ut || !dv) return <Skeleton className="h-96" />
  return (
    <>
      <PageHeader eyebrow="Post-approval" title="Undertakings & document validity" desc="Conditions to be met after approval, and certificates with an expiry date. Each one carries its own reminders and escalation."
        actions={decider && <button className="btn-primary" onClick={() => setAdd(true)}><Plus className="h-4 w-4" />Record undertaking</button>} />
      <Safeguard />
      <div className="mb-3"><Tabs value={tab} onChange={setTab} tabs={[{ id: 'undertakings', label: `Undertakings (${ut.length})` }, { id: 'validity', label: `Document validity (${dv.length})` }]} /></div>
      {tab === 'undertakings' ? <div className="card p-0" data-testid="ut-table">{!ut.length ? <div className="p-4"><Empty title="No undertakings." /></div> :
        <table className="w-full text-sm"><thead className="table-head"><tr><th className="px-5 py-2 text-left">Condition</th><th className="text-left">Application</th><th className="text-left">Due</th><th className="text-left">Status</th><th className="px-5 text-right">Action</th></tr></thead>
          <tbody>{ut.map((x) => <tr key={x.id} className="border-b border-line/60 align-top last:border-0"><td className="max-w-md px-5 py-2.5">{x.condition}<div className="text-xs text-muted">Evidence: {x.evidence_required || '—'}</div><Subs x={x} />{x.remark && <div className="text-xs text-muted">Remark: {x.remark}</div>}</td>
            <td><Link className="font-mono text-xs text-primary" to={`/applications/${x.application_id}`}>{x.ref}</Link><div className="text-xs text-muted">{x.college}</div></td>
            <td className={clsx(x.overdue && 'font-semibold text-red-600')}>{fmtDay(x.due_date)}</td><td><span className={clsx('chip', TONE[x.status])}>{x.status}</span></td>
            <td className="px-5 text-right">{college && ['open', 'rejected'].includes(x.status) && <button className="btn-primary btn-sm" data-testid="ut-submit" onClick={() => setUp({ kind: 'ut', x })}><CloudUpload className="h-3.5 w-3.5" />Submit evidence</button>}
              {decider && x.status === 'submitted' && <button className="btn-ghost btn-sm" data-testid="ut-verify" onClick={() => setVer({ kind: 'ut', x })}>Verify</button>}</td></tr>)}</tbody></table>}</div>
        : <div className="card p-0" data-testid="dv-table">{!dv.length ? <div className="p-4"><Empty title="No tracked documents." /></div> :
          <table className="w-full text-sm"><thead className="table-head"><tr><th className="px-5 py-2 text-left">Document</th><th className="text-left">Institution</th><th className="text-left">Valid until</th><th className="text-left">Status</th><th className="px-5 text-right">Action</th></tr></thead>
            <tbody>{dv.map((x) => <tr key={x.id} className="border-b border-line/60 last:border-0"><td className="px-5 py-2.5">{x.label}<div><Subs x={x} /></div></td><td>{x.college}</td>
              <td className={clsx(x.flag === 'expired' && 'font-semibold text-red-600', x.flag === 'expiring' && 'font-semibold text-amber-600')}>{fmtDay(x.valid_until)}<div className="text-xs">{x.days_left < 0 ? `${-x.days_left} d ago` : `${x.days_left} d left`}</div></td>
              <td><span className={clsx('chip', TONE[x.status])}>{x.status.replace('_', ' ')}</span></td>
              <td className="px-5 text-right">{college && ['valid', 'expired'].includes(x.status) && <button className="btn-primary btn-sm" data-testid="dv-renew" onClick={() => setUp({ kind: 'dv', x })}><CloudUpload className="h-3.5 w-3.5" />Upload renewal</button>}
                {decider && x.status === 'renewal_submitted' && <button className="btn-ghost btn-sm" onClick={() => setVer({ kind: 'dv', x })}>Verify</button>}</td></tr>)}</tbody></table>}</div>}
      <Modal open={!!up} onClose={() => setUp(null)} title={up?.kind === 'ut' ? 'Submit compliance evidence' : 'Upload renewed document'}>
        <input type="file" accept=".pdf,.jpg,.jpeg,.png" onChange={(e) => setFile(e.target.files?.[0] || null)} />
        {up?.kind === 'dv' && <><label className="label mt-3">New valid-until date</label><input type="date" className="input" value={until} onChange={(e) => setUntil(e.target.value)} /></>}
        <label className="label mt-3">Note</label><textarea className="input" value={note} onChange={(e) => setNote(e.target.value)} />
        <button className="btn-primary mt-3" disabled={!file || (up?.kind === 'dv' && !until)} onClick={submit}>Submit</button>
      </Modal>
      <Modal open={!!ver} onClose={() => setVer(null)} title="Verify submission">
        <p className="text-sm text-muted">Open the attached file(s) before recording your finding.</p>{ver && <Subs x={ver.x} />}
        <label className="label mt-3">Remark</label><textarea className="input" value={remark} onChange={(e) => setRemark(e.target.value)} />
        <div className="mt-3 flex gap-2"><button className="btn-primary" onClick={() => verify(true)}><CheckCircle2 className="h-4 w-4" />Accept</button><button className="btn-ghost" disabled={remark.trim().length < 5} onClick={() => verify(false)}><XCircle className="h-4 w-4" />Send back (remark needed)</button></div>
      </Modal>
      <Modal open={add} onClose={() => setAdd(false)} title="Record undertaking">
        <label className="label">Application ID</label><input className="input" value={nu.application_id} onChange={(e) => setNu({ ...nu, application_id: e.target.value })} />
        <label className="label mt-2">Condition (as worded in the approval letter)</label><textarea className="input" value={nu.condition} onChange={(e) => setNu({ ...nu, condition: e.target.value })} />
        <label className="label mt-2">Evidence required</label><input className="input" value={nu.evidence_required} onChange={(e) => setNu({ ...nu, evidence_required: e.target.value })} />
        <label className="label mt-2">Due date</label><input type="date" className="input" value={nu.due_date} onChange={(e) => setNu({ ...nu, due_date: e.target.value })} />
        <button className="btn-primary mt-3" onClick={create}>Save</button>
      </Modal>
    </>
  )
}
