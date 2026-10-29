import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Loader2, UserPlus } from 'lucide-react'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { AuthShell, Field, PasswordMeter } from '../components/AuthShell'

const EMPTY = { full_name: '', username: '', email: '', phone: '', password: '', confirm: '', role: 'college', institution_name: '', aicte_id: '', state: '', designation: '', region: '', consent: false }

export default function Signup() {
  const { adopt } = useAuth(); const nav = useNavigate()
  const [o, setO] = useState<any>(null); const [f, setF] = useState<any>(EMPTY); const [errs, setErrs] = useState<Record<string, string>>({}); const [err, setErr] = useState(''); const [busy, setBusy] = useState(false)
  useEffect(() => { api('/api/auth/signup/options').then(setO).catch((e) => setErr(e.message)) }, [])
  const set = (k: string) => (e: any) => { setErrs((x) => { const { [k]: _drop, ...rest } = x; void _drop; return rest }); setF({ ...f, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value }) }
  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setErr(''); setErrs({})
    if (f.password !== f.confirm) { setErrs({ confirm: 'The two passwords do not match.' }); return }
    setBusy(true)
    try {
      const r = await api('/api/auth/signup', { method: 'POST', json: f })
      adopt(r.token, r.user); nav(r.status === 'approved' ? '/' : '/onboarding', { replace: true })
    } catch (x: any) { setErr(x.message); setErrs(x.fields || {}) } finally { setBusy(false) }
  }
  const role = o?.roles.find((r: any) => r.value === f.role)
  const inp = (k: string, props: any = {}) => <input id={`su-${k}`} data-testid={`su-${k}`} className="input" value={f[k]} onChange={set(k)} aria-invalid={!!errs[k]} aria-describedby={errs[k] ? `su-${k}-err` : undefined} {...props} />
  return (
    <AuthShell title="Create an account" wide>
      <form onSubmit={submit} className="space-y-4" noValidate>
        <div className="grid gap-3 md:grid-cols-2">
          <Field id="su-full_name" label="Full name" err={errs.full_name}>{inp('full_name', { autoComplete: 'name', required: true })}</Field>
          <Field id="su-username" label="Username" err={errs.username} hint="3-32 characters: a-z, 0-9, . _ -">{inp('username', { autoComplete: 'username', required: true, onChange: (e: any) => set('username')({ target: { type: 'text', value: e.target.value.toLowerCase() } }) })}</Field>
          <Field id="su-email" label="Email" err={errs.email}>{inp('email', { type: 'email', autoComplete: 'email', required: true })}</Field>
          <Field id="su-phone" label="Mobile number" err={errs.phone}>{inp('phone', { type: 'tel', autoComplete: 'tel', placeholder: '98765 43210', required: true })}</Field>
          <Field id="su-password" label="Password" err={errs.password}>{inp('password', { type: 'password', autoComplete: 'new-password', required: true })}<PasswordMeter pw={f.password} username={f.username} email={f.email} /></Field>
          <Field id="su-confirm" label="Confirm password" err={errs.confirm}>{inp('confirm', { type: 'password', autoComplete: 'new-password', required: true })}</Field>
        </div>
        <fieldset><legend className="label">I am a</legend>
          <div className="grid gap-2 sm:grid-cols-2" role="radiogroup">{(o?.roles || []).map((r: any) => (
            <label key={r.value} className={`card flex cursor-pointer items-start gap-2 p-3 text-sm ${f.role === r.value ? 'border-primary ring-2 ring-primary/20' : ''}`}>
              <input type="radio" name="role" value={r.value} checked={f.role === r.value} onChange={set('role')} data-testid={`su-role-${r.value}`} className="mt-1" />
              <span><b>{r.label}</b><span className="block text-xs text-muted">{r.needs_approval ? 'Needs administrator approval before you get access.' : 'Access to your institution straight away (first representative of a new institution).'}</span></span></label>))}</div>
          {errs.role && <div className="mt-1 text-xs text-red-600">{errs.role}</div>}</fieldset>
        {f.role === 'college' ? <div className="grid gap-3 md:grid-cols-2">
          <Field id="su-institution_name" label="Institution name" err={errs.institution_name}>{inp('institution_name', { autoComplete: 'organization' })}</Field>
          <Field id="su-aicte_id" label="AICTE institution ID (or application ID)" err={errs.aicte_id}>{inp('aicte_id', { placeholder: '1-1234567890' })}</Field>
          <Field id="su-state" label="State / UT" err={errs.state}><select id="su-state" data-testid="su-state" className="input" value={f.state} onChange={set('state')}><option value="">Choose…</option>{(o?.states || []).map((s: string) => <option key={s}>{s}</option>)}</select></Field>
          <Field id="su-designation" label="Designation" err={errs.designation}>{inp('designation', { placeholder: 'Principal' })}</Field>
        </div> : <div className="grid gap-3 md:grid-cols-2">
          {(f.role === 'officer' || f.role === 'senior_officer') && <Field id="su-region" label={f.role === 'officer' ? 'Region' : 'Region (optional)'} err={errs.region} hint="Region names are editable defaults.">
            <select id="su-region" data-testid="su-region" className="input" value={f.region} onChange={set('region')}><option value="">{f.role === 'officer' ? 'Choose…' : 'All regions'}</option>{(o?.regions || []).map((r: any) => <option key={r.code} value={r.code}>{r.name}</option>)}</select></Field>}
          <Field id="su-designation" label="Designation" err={errs.designation}>{inp('designation', { placeholder: f.role === 'evc_member' ? 'Professor, Civil Engg.' : 'Deputy Director' })}</Field>
        </div>}
        <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={f.consent} onChange={set('consent')} data-testid="su-consent" className="mt-1" />
          <span>I agree that the details above are used only to verify my identity and role in this prototype.{errs.consent && <span className="block text-xs text-red-600">{errs.consent}</span>}</span></label>
        {role?.needs_approval && <p className="rounded bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:bg-amber-500/10 dark:text-amber-200">{role.label} access is never self-granted: an administrator verifies and approves it.</p>}
        {err && <div role="alert" className="rounded-xl bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-500/10 dark:text-red-300">{err}</div>}
        <div className="flex flex-wrap items-center gap-3"><button className="btn-primary" disabled={busy || !o} data-testid="su-submit">{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <UserPlus className="h-4 w-4" />}Create account</button>
          <span className="text-sm">Already registered? <Link className="text-primary underline" to="/login">Sign in</Link></span></div>
      </form>
    </AuthShell>
  )
}
