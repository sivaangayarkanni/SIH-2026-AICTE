import { useEffect, useState } from 'react'
import { Database, Cpu, Package, CheckCircle2, XCircle, UserCheck } from 'lucide-react'
import { useAuth } from '../lib/auth'
import { useToast } from '../components/Toast'
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
      <AccessRequests />
      <UserAccounts />
    </>
  )
}

const REQ_LABEL: Record<string, string> = { college: 'College rep', officer: 'Regional officer', senior_officer: 'Bureau officer', evc_member: 'EVC member', admin: 'Administrator' }

function UserAccounts() {
  const { user } = useAuth(); const toast = useToast()
  const [rows, setRows] = useState<any[] | null>(null); const [tmp, setTmp] = useState<any>(null)
  const load = () => api('/api/admin/users').then(setRows).catch(() => setRows([]))
  useEffect(() => { if (user?.role === 'admin') load() }, [user]) // eslint-disable-line react-hooks/exhaustive-deps
  if (user?.role !== 'admin') return null
  const reset = async (r: any) => {
    if (!window.confirm(`Reset the password for ${r.username || r.email}? Their current sessions end and they must set a new password.`)) return
    try { setTmp(await api(`/api/admin/users/${r.id}/reset-password`, { method: 'POST' })); load() } catch (e: any) { toast('error', 'Could not reset', e.message) }
  }
  const role = async (r: any, v: string) => {
    try { await api(`/api/admin/users/${r.id}/role`, { method: 'POST', json: { role: v } }); toast('success', 'Role changed', `${r.username || r.email}: ${REQ_LABEL[v] || v}`); load() } catch (e: any) { toast('error', 'Could not change role', e.message); load() }
  }
  return (
    <div className="card card-pad mt-5" data-testid="user-accounts">
      <div className="text-sm font-semibold">User accounts</div>
      <p className="mt-1 text-xs text-muted">Role changes and password resets sign the person out everywhere and are written to the audit log.</p>
      {tmp && <div role="status" className="mt-3 rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-500/10 dark:text-amber-200" data-testid="temp-password">
        Temporary password for <b>{tmp.username}</b>: <code className="kbd select-all">{tmp.temporary_password}</code><div className="text-xs">{tmp.note}</div>
        <button className="btn-ghost btn-sm mt-2" onClick={() => setTmp(null)}>I have passed it on — hide</button></div>}
      {!rows ? <Skeleton className="mt-3 h-24" /> : <div className="mt-3 max-h-[420px] overflow-auto"><table className="w-full text-sm"><thead><tr className="text-left text-xs text-muted"><th className="py-1.5 pr-3">User</th><th className="pr-3">Username</th><th className="pr-3">Role</th><th className="pr-3">Last sign-in</th><th /></tr></thead>
        <tbody>{rows.map((r) => <tr key={r.id} className="border-t border-line">
          <td className="py-1.5 pr-3">{r.name}<div className="text-xs text-muted">{r.email}</div></td><td className="pr-3 font-mono text-xs">{r.username || '—'}{r.locked && <span className="chip ml-1 bg-red-100 text-red-800">locked</span>}</td>
          <td className="pr-3">{r.id === user.id ? r.role_label : <select aria-label={`Role for ${r.email}`} className="input py-1 text-xs" value={r.role} onChange={(e) => role(r, e.target.value)}>
            {['pending', 'college', 'officer', 'senior_officer', 'evc_member', 'admin'].map((x) => <option key={x} value={x} disabled={x === 'college' && !r.college_id}>{x === 'pending' ? 'No access (pending)' : REQ_LABEL[x]}</option>)}</select>}</td>
          <td className="pr-3 text-xs">{r.last_login_at ? new Date(r.last_login_at + 'Z').toLocaleString('en-IN') : '—'}</td>
          <td className="py-1.5">{r.id !== user.id && <button className="btn-ghost btn-sm" onClick={() => reset(r)}>Reset password</button>}</td></tr>)}</tbody></table></div>}
    </div>
  )
}

function AccessRequests() {
  const { user } = useAuth(); const toast = useToast()
  const [rows, setRows] = useState<any[] | null>(null); const [tab, setTab] = useState('pending'); const [busy, setBusy] = useState<number | null>(null)
  const load = () => api(`/api/admin/access-requests?status=${tab}`).then(setRows).catch(() => setRows([]))
  useEffect(() => { if (user?.role === 'admin') load() }, [tab, user]) // eslint-disable-line react-hooks/exhaustive-deps
  if (user?.role !== 'admin') return null
  const act = async (r: any, ok: boolean, role?: string) => {
    const note = ok ? '' : (window.prompt('Reason for declining (shown to the requester):') ?? null)
    if (note === null) return
    setBusy(r.user_id)
    try { await api(`/api/admin/access-requests/${r.user_id}/${ok ? 'approve' : 'reject'}`, { method: 'POST', json: { role, note } }); toast('success', ok ? 'Access approved' : 'Request declined', r.email); load() }
    catch (e: any) { toast('error', 'Could not update', e.message) } finally { setBusy(null) }
  }
  return (
    <div className="card card-pad mt-5" data-testid="access-requests">
      <div className="flex flex-wrap items-center gap-2"><UserCheck className="h-5 w-5 text-primary" /><div className="text-sm font-semibold">Access requests</div>
        <div className="ml-auto flex gap-1">{['pending', 'approved', 'rejected', 'all'].map((t) => <button key={t} className={tab === t ? 'btn-primary btn-sm' : 'btn-ghost btn-sm'} onClick={() => setTab(t)}>{t}</button>)}</div></div>
      <p className="mt-1 text-xs text-muted">Officer and administrator roles are never self-assigned. Approve only people you have verified through an official channel.</p>
      {!rows ? <Skeleton className="mt-3 h-24" /> : rows.length === 0 ? <p className="mt-3 text-sm text-muted">No {tab === 'all' ? '' : tab} requests.</p> :
        <div className="mt-3 overflow-x-auto"><table className="w-full text-sm"><thead><tr className="text-left text-xs text-muted"><th className="py-1.5 pr-3">Person</th><th className="pr-3">Requested</th><th className="pr-3">Institution / office</th><th className="pr-3">Contact</th><th className="pr-3">Status</th><th /></tr></thead>
          <tbody>{rows.map((r) => <tr key={r.user_id} className="border-t border-line align-top">
            <td className="py-2 pr-3"><b>{r.full_name || '(form not submitted)'}</b><div className="text-xs text-muted">{r.designation}</div></td>
            <td className="pr-3">{REQ_LABEL[r.requested_role] || '–'}</td>
            <td className="pr-3">{r.institution_name}<div className="text-xs text-muted">{r.aicte_id} · {r.state}</div></td>
            <td className="pr-3">{r.email}<div className="text-xs text-muted">{r.phone}</div></td>
            <td className="pr-3">{r.status}{r.decided_by && <div className="text-xs text-muted">{r.decided_by}</div>}</td>
            <td className="whitespace-nowrap py-2">{r.status === 'pending' && <div className="flex gap-1">
              <button className="btn-primary btn-sm" data-testid={`approve-${r.user_id}`} disabled={busy === r.user_id} onClick={() => act(r, true, r.requested_role)}>Approve as {REQ_LABEL[r.requested_role] || r.requested_role}</button>
              {r.requested_role === 'officer' && <button className="btn-ghost btn-sm" disabled={busy === r.user_id} onClick={() => act(r, true, 'senior_officer')}>as Bureau officer</button>}
              <button className="btn-ghost btn-sm" disabled={busy === r.user_id} onClick={() => act(r, false)}>Decline</button></div>}</td>
          </tr>)}</tbody></table></div>}
    </div>
  )
}
