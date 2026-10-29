import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { useAuth } from '../lib/auth'
import { handleCallback } from '../lib/oidc'
import { api } from '../lib/api'

export default function AuthCallback() {
  const { cfg, setUser } = useAuth(); const nav = useNavigate(); const [err, setErr] = useState('')
  useEffect(() => {
    if (!cfg?.oidc) return
    handleCallback(cfg.oidc).then(async (to) => { setUser(await api('/api/auth/me')); nav(to, { replace: true }) }).catch((e) => setErr(e.message))
  }, [cfg]) // eslint-disable-line react-hooks/exhaustive-deps
  return <div className="flex h-full items-center justify-center p-6">{err ? <div className="card card-pad max-w-md text-center"><h2 className="font-display text-xl font-bold">Sign-in failed</h2><p className="mt-2 text-sm text-muted">{err}</p><a className="btn-primary mt-4 inline-flex" href="/login">Back to sign in</a></div> : <span className="flex items-center gap-2 text-sm text-muted"><Loader2 className="h-4 w-4 animate-spin" />Completing single sign-on…</span>}</div>
}
