import { useEffect, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { ArrowRight, Fingerprint, Lock, ScanSearch, ShieldCheck, Network, Scale, Loader2, Palette } from 'lucide-react'
import { useAuth } from '../lib/auth'
import { api } from '../lib/api'
import { Logo } from '../components/Logo'
import { Avatar } from '../components/Avatar'
import { useToast } from '../components/Toast'
import { THEMES, useTheme } from '../lib/theme'
import { DemoNotice, GovBar, Tricolour, UtilityBar, Masthead, PortalFooter } from '../components/Portal'

const ROLE_DESC: Record<string, string> = {
  college: 'Upload documents, see readiness and fix issues', officer: 'Scrutinise the priority queue and decide',
  senior_officer: 'Approve two-person security overrides', admin: 'Security center, PII vault, system health',
}

export default function Login() {
  const { login, user, cfg, sso } = useAuth(); const nav = useNavigate(); const loc = useLocation() as any; const toast = useToast()
  const { theme, setTheme } = useTheme()
  const [accounts, setAccounts] = useState<any[]>([]); const [pw, setPw] = useState('Demo@2026')
  const [email, setEmail] = useState(''); const [password, setPassword] = useState(''); const [busy, setBusy] = useState<string | null>(null); const [err, setErr] = useState('')
  const [reason] = useState(() => { const r = sessionStorage.getItem('sealcheck.logout_reason'); sessionStorage.removeItem('sealcheck.logout_reason'); return r || new URLSearchParams(window.location.search).get('error') })
  useEffect(() => { if (!cfg || !cfg.demo_accounts) return; api('/api/auth/demo-accounts').then((r) => { setAccounts(r.accounts); setPw(r.password) }).catch(() => {}) }, [cfg])
  const [setupNeeded, setSetupNeeded] = useState(false)
  useEffect(() => { if (cfg?.signup) api('/api/auth/setup').then((r) => setSetupNeeded(!!r.needed)).catch(() => {}) }, [cfg])
  useEffect(() => { if (user) nav(loc.state?.from || '/', { replace: true }) }, [user])
  const go = async (e: string, p: string) => {
    setBusy(e); setErr('')
    try { const u = await login(e, p); toast('success', `Welcome, ${u.name}`, u.role_label) } catch (x: any) { setErr(x.message) } finally { setBusy(null) }
  }
  const feats = [
    { i: Lock, t: 'Zero-trust intake', d: 'Malware scan, CDR and an isolated sandbox for every file' },
    { i: ScanSearch, t: 'Forensics that show proof', d: 'Hidden text, overlays and broken DSC signatures highlighted on the page' },
    { i: Network, t: 'Cross-college collusion', d: 'Shared faculty PANs and recycled lab photos linked in a graph' },
    { i: Scale, t: 'Humans decide', d: 'Deterministic policy, explained by AI agents, signed off by officers' },
  ]
  const portal = theme === 'portal'
  const panel = (
        <div className="w-full max-w-[540px] animate-fadeUp">
          <h2 className="font-display text-3xl font-bold">{portal ? 'Sign in to the SealCheck prototype' : 'Sign in'}</h2>
          {portal && <p role="note" className="mt-2 rounded border-l-4 border-[#b34000] bg-accent-soft px-3 py-2 text-[13px] text-ink">This is the sign-in for a hackathon prototype. It is <b>not</b> the AICTE portal login. Do not enter AICTE or government portal passwords here.</p>}
          {reason && <div role="status" className="mt-3 rounded-xl bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:bg-amber-500/10 dark:text-amber-200">{reason}</div>}
          {cfg?.mode === 'google' ? <>
            <p className="mt-1 text-sm text-muted">Sign in with your Google account. First-time users fill in a short profile; AICTE officer access is approved by an administrator.</p>
            {cfg.google?.enabled
              ? <a className="btn-primary mt-6 flex w-full justify-center py-3" data-testid="google-login" href={`/api/auth/google/start?return_to=${encodeURIComponent(loc.state?.from || '/')}`} onClick={() => setBusy('google')}>
                  {busy === 'google' ? <Loader2 className="h-4 w-4 animate-spin" /> : <GoogleG />}Continue with Google</a>
              : <><button className="btn-primary mt-6 w-full py-3 opacity-60" data-testid="google-login" disabled><GoogleG />Continue with Google</button>
                  <div role="status" data-testid="google-not-configured" className="mt-3 rounded-xl bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:bg-amber-500/10 dark:text-amber-200">Google sign-in is not configured on this deployment yet. The administrator needs to add the Google OAuth client ID and secret.</div></>}
            <p className="mt-3 text-xs text-muted">OpenID Connect · Authorization Code + PKCE · verified Google email required</p>
          </> : cfg?.mode === 'oidc' ? <>
            <p className="mt-1 text-sm text-muted">Use your AICTE single sign-on account. Officers are asked for a one-time code (TOTP).</p>
            <button className="btn-primary mt-6 w-full py-3" data-testid="sso-login" disabled={!!busy} onClick={async () => { setBusy('sso'); setErr(''); try { await sso(loc.state?.from || '/') } catch (x: any) { setErr(x.message); setBusy(null) } }}>
              {busy === 'sso' ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldCheck className="h-4 w-4" />}Sign in with single sign-on</button>
            {err && <div role="alert" className="mt-3 rounded-xl bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-500/10 dark:text-red-300">{err}</div>}
            <p className="mt-3 text-xs text-muted">OpenID Connect · Authorization Code + PKCE · {cfg.oidc?.issuer}</p>
          </> : <>
          <p className="mt-1 text-sm text-muted">Sign in with your username (or email) and password.{cfg?.demo_accounts ? ' Or pick a demo persona below.' : ''}</p>
          {setupNeeded && <div role="status" className="mt-3 rounded-xl bg-amber-50 px-3 py-2 text-sm text-amber-900" data-testid="setup-needed">No administrator exists yet. <Link className="font-semibold underline" to="/setup">Run first-time setup</Link>.</div>}
          <form className="mt-5 space-y-3" onSubmit={(e) => { e.preventDefault(); go(email, password) }}>
            <div className="grid gap-3 sm:grid-cols-2">
              <div><label className="label" htmlFor="em">Username or email</label><input id="em" data-testid="signin-username" className="input" type="text" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder={cfg?.demo_accounts ? 'officer' : 'your.username'} autoComplete="username" autoCapitalize="none" spellCheck={false} /></div>
              <div><label className="label" htmlFor="pw">Password</label><input id="pw" data-testid="signin-password" className="input" type="password" required value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" /></div>
            </div>
            {err && <div role="alert" className="rounded-xl bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-500/10 dark:text-red-300">{err}</div>}
            <button className="btn-primary w-full py-2.5" disabled={!!busy} data-testid="signin-submit">{busy === email ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldCheck className="h-4 w-4" />}Sign in securely</button>
          </form>
          {cfg?.signup && <p className="mt-3 text-sm">New to SealCheck? <Link to="/signup" className="font-semibold text-primary underline" data-testid="goto-signup">Create an account</Link> · College representatives get access straight away; officer and EVC roles are approved by an administrator.</p>}
          {cfg?.demo_accounts && <>
          <div className="my-5 flex items-center gap-3 text-xs text-muted"><span className="h-px flex-1 bg-line" />demo personas (development only)<span className="h-px flex-1 bg-line" /></div>
          <div className="grid gap-2.5 sm:grid-cols-2">
            {accounts.length === 0 && Array.from({ length: 8 }).map((_, i) => <div key={i} className="skeleton h-[68px]" />)}
            {accounts.map((a) => (
              <button key={a.id} onClick={() => go(a.email, pw)} disabled={!!busy} data-testid={`demo-${a.email}`}
                className="card group flex items-center gap-3 p-3 text-left transition hover:-translate-y-0.5 hover:border-primary hover:shadow-pop">
                <Avatar seed={a.avatar_seed} size={42} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-semibold">{a.name}</span>
                  <span className="block truncate text-[11.5px] text-muted">{a.college ? a.college.replace(/ (of|&).*/, '…') : a.title}</span>
                  <span className="mt-0.5 block truncate text-[10.5px] font-semibold uppercase tracking-wide text-primary" title={ROLE_DESC[a.role]}>{a.role_label}</span>
                </span>
                {busy === a.email ? <Loader2 className="h-4 w-4 animate-spin text-primary" /> : <ArrowRight className="h-4 w-4 text-muted transition group-hover:translate-x-0.5 group-hover:text-primary" />}
              </button>
            ))}
          </div></>}
          </>}
          <div className="mt-6 flex items-center justify-between rounded-2xl border border-line bg-surface px-4 py-3">
            <span className="flex items-center gap-2 text-xs font-semibold text-muted"><Palette className="h-4 w-4" />Theme</span>
            <div className="flex gap-2">{THEMES.map((t) => (
              <button key={t.id} onClick={() => setTheme(t.id)} title={t.name} aria-label={`Use ${t.name} theme`}
                className={`h-7 w-7 rounded-full ring-offset-2 ring-offset-surface transition ${theme === t.id ? 'ring-2 ring-primary' : 'hover:scale-110'}`} style={{ background: `linear-gradient(135deg, ${t.swatch[0]} 55%, ${t.swatch[1]} 55%)` }} />
            ))}</div>
          </div>
          {cfg?.demo_accounts && <p className="mt-4 text-center text-[11px] text-muted">Development build with synthetic demo data. All demo accounts use the password <span className="kbd">{pw}</span>.</p>}
        </div>
  )
  if (portal) return (
    <div className="flex min-h-full flex-col bg-bg" data-layout="portal">
      <GovBar /><Tricolour /><DemoNotice /><UtilityBar />
      <header className="border-b border-line bg-surface"><Masthead /></header>
      <main id="main-content" tabIndex={-1} className="mx-auto grid w-full max-w-[1360px] flex-1 gap-6 px-4 py-8 md:px-8 lg:grid-cols-[1fr_560px]">
        <section className="card self-start overflow-hidden p-0">
          <div className="card-head px-5 py-3 text-[15px] font-bold uppercase tracking-wide">About SealCheck</div>
          <div className="p-5">
            <h1 className="font-display text-[26px] font-bold leading-tight text-primary dark:text-ink">Verify every approval document. Trust nothing until it is proven.</h1>
            <p className="mt-3 text-[15px] leading-relaxed text-muted">SealCheck checks college submissions for forgery, expiry and collusion, and shows officers exactly where the evidence is, so decisions are fast, fair and defensible.</p>
            <ul className="mt-5 grid gap-3 sm:grid-cols-2">
              {feats.map((f) => <li key={f.t} className="flex gap-3 rounded border border-line bg-surface-2 p-3"><f.i className="mt-0.5 h-5 w-5 shrink-0 text-[color:var(--link)]" /><span><span className="block text-sm font-bold">{f.t}</span><span className="block text-[13px] text-muted">{f.d}</span></span></li>)}
            </ul>
            <div className="mt-5 rounded px-3 py-2 text-[13px] font-semibold text-[#111]" style={{ background: 'var(--amber)' }}>Smart India Hackathon 2026 · Problem statement SIH26261{cfg?.demo_accounts ? ' · synthetic demo data only' : ' · prototype, not an official AICTE system'}</div>
          </div>
        </section>
        <section className="card p-6">{panel}</section>
      </main>
      <PortalFooter />
    </div>
  )
  return (
    <div className="flex min-h-full flex-col lg:flex-row">
      <section className="relative overflow-hidden px-6 py-8 text-white sm:px-8 sm:py-10 lg:sticky lg:top-0 lg:h-screen lg:w-[52%] lg:overflow-hidden lg:px-12 lg:py-10 2xl:px-14" style={{ background: 'linear-gradient(150deg, var(--hero-a), var(--hero-b))' }}>
        <div className="grid-bg absolute inset-0 opacity-60" />
        <div className="absolute -right-32 -top-32 h-96 w-96 rounded-full bg-white/10 blur-3xl" />
        <div className="relative">
          <Logo light size={40} />
          <div className="mt-8 inline-flex lg:mt-10 items-center gap-2 rounded-full bg-white/10 px-3 py-1 text-xs font-semibold backdrop-blur"><Fingerprint className="h-3.5 w-3.5" />Smart India Hackathon · AICTE · SIH26261</div>
          <h1 className="mt-4 max-w-xl font-display text-[30px] font-bold leading-[1.1] sm:text-[38px] 2xl:text-[44px]">Verify every approval document. Trust nothing until it is proven.</h1>
          <p className="mt-4 hidden max-w-lg text-[15px] sm:block leading-relaxed text-white/80">SealCheck checks college submissions for forgery, expiry and collusion — and shows officers exactly where the evidence is, so decisions are fast, fair and defensible.</p>
          <div className="mt-7 hidden max-w-xl gap-3 sm:grid sm:grid-cols-2">
            {feats.map((f) => (
              <div key={f.t} className="rounded-2xl border border-white/15 bg-white/[.07] p-4 backdrop-blur">
                <f.i className="h-5 w-5 text-white/90" /><div className="mt-2 text-sm font-semibold">{f.t}</div><div className="mt-0.5 text-xs leading-relaxed text-white/70">{f.d}</div>
              </div>
            ))}
          </div>
          <HeroArt />
        </div>
      </section>
      <section className="flex flex-1 items-center justify-center bg-bg px-4 py-8 sm:px-6 sm:py-10">
        {panel}
      </section>
    </div>
  )
}

function GoogleG() {
  return <svg aria-hidden width="18" height="18" viewBox="0 0 48 48" className="rounded-full bg-white p-[2px]"><path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9 3.6l6.7-6.7C35.6 2.5 30.2 0 24 0 14.6 0 6.6 5.4 2.6 13.3l7.8 6C12.3 13.4 17.7 9.5 24 9.5z"/><path fill="#4285F4" d="M46.1 24.6c0-1.6-.1-3.1-.4-4.6H24v9h12.4c-.5 2.9-2.2 5.3-4.6 6.9l7.4 5.7c4.3-4 6.9-9.9 6.9-17z"/><path fill="#FBBC05" d="M10.4 28.7A14.5 14.5 0 0 1 9.5 24c0-1.6.3-3.2.9-4.7l-7.8-6A24 24 0 0 0 0 24c0 3.9.9 7.5 2.6 10.7l7.8-6z"/><path fill="#34A853" d="M24 48c6.5 0 11.9-2.1 15.9-5.8l-7.4-5.7c-2.1 1.4-4.8 2.3-8.5 2.3-6.3 0-11.7-3.9-13.6-9.6l-7.8 6C6.6 42.6 14.6 48 24 48z"/></svg>
}

function HeroArt() {
  return (
    <div className="hero-art mt-7 max-w-xl rounded-2xl border border-white/15 bg-white/[.06] p-4 backdrop-blur" aria-hidden>
      <div className="flex items-center gap-3">
        <div className="relative h-[92px] w-[72px] shrink-0 rounded-md bg-white p-2 shadow-xl">
          {[0, 1, 2, 3, 4, 5].map((i) => <div key={i} className="mb-1.5 h-1 rounded bg-slate-300" style={{ width: `${90 - i * 9}%` }} />)}
          <div className="absolute left-1.5 top-[44px] h-3 w-14 rounded-sm border-2 border-red-500 bg-red-400/20" />
          <div className="absolute bottom-1.5 right-1.5 h-4 w-4 rounded-full border-2 border-emerald-500" />
        </div>
        <div className="flex-1 space-y-1.5 text-[11.5px]">
          {[['CDR + sandbox', 'done'], ['PDF forensics', 'Hidden text found'], ['DSC ByteRange', 'Modified after signing'], ['Policy engine', 'Mismatch Detected']].map(([a, b], i) => (
            <div key={a} className="flex items-center gap-2 rounded-lg bg-white/10 px-2.5 py-1.5" style={{ animation: `fadeUp .5s ${i * 0.15}s both` }}>
              <span className={`h-1.5 w-1.5 rounded-full ${i === 0 ? 'bg-emerald-400' : 'bg-amber-300'}`} /><span className="font-semibold">{a}</span><span className="ml-auto text-white/70">{b}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
