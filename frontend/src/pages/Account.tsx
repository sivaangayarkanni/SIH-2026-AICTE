import { useState } from 'react'
import { KeyRound, LogOut, Loader2 } from 'lucide-react'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { useToast } from '../components/Toast'
import { Field, PasswordMeter } from '../components/AuthShell'

export default function Account() {
  const { user, adopt, logout } = useAuth(); const toast = useToast()
  const [f, setF] = useState({ current: '', new: '', confirm: '' }); const [errs, setErrs] = useState<Record<string, string>>({}); const [err, setErr] = useState(''); const [busy, setBusy] = useState(false)
  const set = (k: string) => (e: any) => { setErrs((x) => { const { [k]: _drop, ...rest } = x; void _drop; return rest }); setF({ ...f, [k]: e.target.value }) }
  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setBusy(true); setErr(''); setErrs({})
    try { const r = await api('/api/auth/password', { method: 'POST', json: f }); const me = await (await fetch('/api/auth/me', { headers: { Authorization: `Bearer ${r.token}` } })).json(); adopt(r.token, me); setF({ current: '', new: '', confirm: '' }); toast('success', 'Password changed', 'Every other session was signed out.') }
    catch (x: any) { setErr(x.message); setErrs(x.fields || {}) } finally { setBusy(false) }
  }
  const everywhere = async () => { if (!window.confirm('Sign out on every device, including this one?')) return; await api('/api/auth/logout-all', { method: 'POST' }).catch(() => {}); logout('You signed out everywhere.') }
  return (
    <div className="mx-auto max-w-xl space-y-4" data-testid="account-page">
      <div><h1 className="font-display text-2xl font-bold">My account</h1><p className="text-sm text-muted">{user?.name} · {user?.username ? <span className="font-mono">{user.username}</span> : user?.email} · {user?.role_label}</p></div>
      {user?.must_change_password && <div role="alert" className="rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">An administrator reset your password. Choose a new one to continue.</div>}
      <form onSubmit={submit} className="card card-pad space-y-3" noValidate>
        <div className="flex items-center gap-2 font-semibold"><KeyRound className="h-4 w-4" />Change password</div>
        <Field id="pw-current" label={user?.must_change_password ? 'Temporary password' : 'Current password'} err={errs.current}><input id="pw-current" type="password" autoComplete="current-password" className="input" value={f.current} onChange={set('current')} /></Field>
        <Field id="pw-new" label="New password" err={errs.new}><input id="pw-new" type="password" autoComplete="new-password" className="input" value={f.new} onChange={set('new')} /><PasswordMeter pw={f.new} username={user?.username || ''} email={user?.email} /></Field>
        <Field id="pw-confirm" label="Confirm new password" err={errs.confirm}><input id="pw-confirm" type="password" autoComplete="new-password" className="input" value={f.confirm} onChange={set('confirm')} /></Field>
        {err && <div role="alert" className="rounded-xl bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}
        <button className="btn-primary" disabled={busy} data-testid="pw-submit">{busy && <Loader2 className="h-4 w-4 animate-spin" />}Change password</button>
      </form>
      <div className="card card-pad flex items-center justify-between gap-3 text-sm"><span>Lost a device or shared a computer? End every session.</span><button className="btn-ghost" onClick={everywhere} data-testid="logout-all"><LogOut className="h-4 w-4" />Sign out everywhere</button></div>
    </div>
  )
}
