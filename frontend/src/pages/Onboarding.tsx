import { FormEvent, useEffect, useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { Clock, Loader2, LogOut, ShieldCheck, XCircle } from 'lucide-react'
import { useAuth, User } from '../lib/auth'
import { api } from '../lib/api'
import { Logo } from '../components/Logo'
import { useToast } from '../components/Toast'

type Opts = { states: string[]; email: string; name: string; roles: { value: string; label: string }[] }
const EMPTY = { full_name: '', requested_role: 'college', institution_name: '', aicte_id: '', state: '', designation: '', phone: '', consent: false }

export default function Onboarding() {
  const { user, loading, setUser, logout } = useAuth(); const nav = useNavigate(); const toast = useToast()
  const [opts, setOpts] = useState<Opts | null>(null); const [prof, setProf] = useState<any>(null)
  const [f, setF] = useState<typeof EMPTY>(EMPTY); const [busy, setBusy] = useState(false); const [err, setErr] = useState<string[]>([])
  useEffect(() => {
    if (!user) return
    api<Opts>('/api/auth/onboarding/options').then((o) => { setOpts(o); setF((x) => ({ ...x, full_name: x.full_name || o.name })) })
    api<{ profile: any }>('/api/auth/profile').then((r) => { setProf(r.profile); if (r.profile?.full_name) setF((x) => ({ ...x, ...Object.fromEntries(Object.entries(r.profile).filter(([k, v]) => k in EMPTY && v != null)), consent: false })) })
  }, [user])
  if (loading) return null
  if (!user) return <Navigate to="/login" replace />
  if (user.role !== 'pending' && user.role !== 'admin') return <Navigate to="/" replace />
  const set = (k: keyof typeof EMPTY) => (e: any) => setF({ ...f, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setBusy(true); setErr([])
    try {
      const r = await api<{ status: string; user: User; profile: any }>('/api/auth/onboarding', { method: 'POST', json: f })
      setUser(r.user); setProf(r.profile)
      if (r.status === 'approved') { toast('success', 'Access granted', r.user.college || r.user.role_label); nav('/', { replace: true }) }
    } catch (x: any) { setErr(String(x.message).split('\n')) } finally { setBusy(false) }
  }
  const status = prof?.status
  return (
    <div className="flex min-h-full items-start justify-center bg-bg px-4 py-10">
      <div className="w-full max-w-[720px]">
        <div className="mb-5 flex items-center justify-between"><Logo size={36} /><button className="btn-ghost btn-sm" onClick={() => logout()}><LogOut className="h-4 w-4" />Sign out</button></div>
        {status === 'pending' && <div className="card card-pad mb-5 flex gap-3" data-testid="access-pending"><Clock className="h-6 w-6 shrink-0 text-amber-500" /><div><h2 className="font-display text-lg font-bold">Waiting for administrator approval</h2><p className="mt-1 text-sm text-muted">Your request for <b>{prof.requested_role === 'officer' ? 'AICTE officer' : prof.requested_role === 'evc_member' ? 'EVC member' : 'college representative'}</b> access ({prof.institution_name}, {prof.aicte_id}) was received. An administrator must approve it before you can use SealCheck. You can update the details below while you wait.</p></div></div>}
        {status === 'rejected' && <div className="card card-pad mb-5 flex gap-3" data-testid="access-rejected"><XCircle className="h-6 w-6 shrink-0 text-red-500" /><div><h2 className="font-display text-lg font-bold">Access request declined</h2><p className="mt-1 text-sm text-muted">{prof.decision_note || 'An administrator declined this request.'} Contact your AICTE regional office if you think this is a mistake.</p></div></div>}
        {status !== 'rejected' && <form className="card card-pad space-y-4" onSubmit={submit} data-testid="onboarding-form">
          <div><h1 className="font-display text-2xl font-bold">Complete your SealCheck profile</h1>
            <p className="mt-1 text-sm text-muted">Signed in with Google as <b>{opts?.email || user.email}</b>. College representatives of a new institution get access to that institution straight away. AICTE officer access, and a second representative for an institution already registered, need administrator approval.</p></div>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field id="full_name" label="Full name"><input id="full_name" className="input" required minLength={3} maxLength={120} value={f.full_name} onChange={set('full_name')} autoComplete="name" /></Field>
            <Field id="requested_role" label="I am a"><select id="requested_role" className="input" value={f.requested_role} onChange={set('requested_role')}>{(opts?.roles || []).map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}</select></Field>
            <Field id="institution_name" label={f.requested_role !== 'college' ? 'AICTE office / organisation' : 'Institution name'}><input id="institution_name" className="input" required minLength={3} maxLength={200} value={f.institution_name} onChange={set('institution_name')} autoComplete="organization" /></Field>
            <Field id="aicte_id" label={f.requested_role !== 'college' ? 'Office / employee ID' : 'AICTE institution ID or application ID'}><input id="aicte_id" className="input" required pattern="[A-Za-z0-9][A-Za-z0-9/\-]{3,19}" title="4-20 letters, digits, - or /" value={f.aicte_id} onChange={set('aicte_id')} placeholder="1-1234567890" /></Field>
            <Field id="state" label="State / union territory"><select id="state" className="input" required value={f.state} onChange={set('state')}><option value="">Choose…</option>{(opts?.states || []).map((s) => <option key={s}>{s}</option>)}</select></Field>
            <Field id="designation" label="Designation"><input id="designation" className="input" required minLength={2} maxLength={120} value={f.designation} onChange={set('designation')} placeholder="Principal / Registrar / Deputy Director" autoComplete="organization-title" /></Field>
            <Field id="phone" label="Mobile number"><input id="phone" className="input" required type="tel" inputMode="tel" pattern="(\+91[\s\-]?)?[6-9][0-9\s\-]{9,12}" title="10-digit Indian mobile number" value={f.phone} onChange={set('phone')} placeholder="+91 98xxxxxxxx" autoComplete="tel" /></Field>
            <Field id="official_email" label="Official email (from Google)"><input id="official_email" className="input" readOnly value={opts?.email || user.email} /></Field>
          </div>
          <label className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-1" required checked={f.consent} onChange={set('consent')} data-testid="consent" />
            <span>I confirm these details are correct and agree that SealCheck stores them, my Google account email and an audit log of my actions to verify approval documents. This is a prototype, not an official AICTE system.</span></label>
          {err.length > 0 && <div role="alert" className="rounded-xl bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-500/10 dark:text-red-300">{err.map((e, i) => <div key={i}>{e}</div>)}</div>}
          <button className="btn-primary w-full py-2.5" disabled={busy} data-testid="onboarding-submit">{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldCheck className="h-4 w-4" />}{status === 'pending' ? 'Update request' : 'Submit'}</button>
        </form>}
      </div>
    </div>
  )
}

function Field({ id, label, children }: { id: string; label: string; children: any }) {
  return <div><label className="label" htmlFor={id}>{label}</label>{children}</div>
}
