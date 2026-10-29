import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Loader2, ShieldCheck } from 'lucide-react'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { AuthShell, Field, PasswordMeter } from '../components/AuthShell'

export default function Setup() {
  const { adopt } = useAuth(); const nav = useNavigate()
  const [needed, setNeeded] = useState<boolean | null>(null); const [f, setF] = useState<any>({ full_name: '', username: '', email: '', password: '', confirm: '' })
  const [errs, setErrs] = useState<Record<string, string>>({}); const [err, setErr] = useState(''); const [busy, setBusy] = useState(false)
  useEffect(() => { api('/api/auth/setup').then((r) => setNeeded(r.needed)).catch(() => setNeeded(false)) }, [])
  const set = (k: string) => (e: any) => { setErrs((x) => { const { [k]: _drop, ...rest } = x; void _drop; return rest }); setF({ ...f, [k]: e.target.value }) }
  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setBusy(true); setErr(''); setErrs({})
    try { const r = await api('/api/auth/setup', { method: 'POST', json: f }); adopt(r.token, r.user); nav('/admin', { replace: true }) }
    catch (x: any) { setErr(x.message); setErrs(x.fields || {}) } finally { setBusy(false) }
  }
  return (
    <AuthShell title="First-run setup">
      {needed === null ? <Loader2 className="h-5 w-5 animate-spin" /> : !needed ? <p className="text-sm" data-testid="setup-done">Setup is complete: an administrator already exists. <Link className="text-primary underline" to="/login">Sign in</Link>.</p> :
        <form onSubmit={submit} className="space-y-3" noValidate>
          <p className="text-sm text-muted">No administrator exists yet. Create the first one. This form stops working as soon as an administrator exists.</p>
          {(['full_name', 'username', 'email'] as const).map((k) => <Field key={k} id={`st-${k}`} label={{ full_name: 'Full name', username: 'Username', email: 'Email' }[k]} err={errs[k]}><input id={`st-${k}`} className="input" value={f[k]} onChange={set(k)} type={k === 'email' ? 'email' : 'text'} /></Field>)}
          <Field id="st-password" label="Password" err={errs.password}><input id="st-password" type="password" autoComplete="new-password" className="input" value={f.password} onChange={set('password')} /><PasswordMeter pw={f.password} username={f.username} email={f.email} /></Field>
          <Field id="st-confirm" label="Confirm password" err={errs.confirm}><input id="st-confirm" type="password" autoComplete="new-password" className="input" value={f.confirm} onChange={set('confirm')} /></Field>
          {err && <div role="alert" className="rounded-xl bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}
          <button className="btn-primary" disabled={busy}><ShieldCheck className="h-4 w-4" />Create administrator</button>
        </form>}
    </AuthShell>
  )
}
