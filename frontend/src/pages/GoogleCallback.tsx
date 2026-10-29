import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { useAuth, User } from '../lib/auth'
import { api } from '../lib/api'

/** Landing page after /api/auth/google/callback: the server puts our session token in the URL fragment
 *  (never sent to any server, removed from history immediately). */
export default function GoogleCallback() {
  const { setUser } = useAuth(); const nav = useNavigate(); const [err, setErr] = useState('')
  useEffect(() => {
    const h = new URLSearchParams(window.location.hash.slice(1))
    window.history.replaceState(null, '', '/auth/google')
    const tok = h.get('token'); const to = h.get('return_to') || '/'
    if (!tok) { setErr('No session was returned. Please try signing in again.'); return }
    localStorage.setItem('sealcheck.token', tok)
    api<User>('/api/auth/me').then((u) => { setUser(u); nav(u.role === 'pending' ? '/onboarding' : (to.startsWith('/') && !to.startsWith('//') ? to : '/'), { replace: true }) })
      .catch((e) => { localStorage.removeItem('sealcheck.token'); setErr(e.message) })
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  return <div className="flex h-full items-center justify-center p-6">{err
    ? <div className="card card-pad max-w-md text-center"><h2 className="font-display text-xl font-bold">Sign-in failed</h2><p className="mt-2 text-sm text-muted">{err}</p><a className="btn-primary mt-4 inline-flex" href="/login">Back to sign in</a></div>
    : <span className="flex items-center gap-2 text-sm text-muted"><Loader2 className="h-4 w-4 animate-spin" />Completing Google sign-in…</span>}</div>
}
