import { useEffect, useRef, useState } from 'react'
import { ShieldCheck, KeyRound, Timer, Link2, Lock, Eye, Server, Fingerprint, Loader2, CheckCircle2, XCircle, Ban, HardDrive } from 'lucide-react'
import clsx from 'clsx'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { PageHeader, Skeleton, Term } from '../components/ui'
import { useToast } from '../components/Toast'

export default function Security() {
  const { user } = useAuth(); const [o, setO] = useState<any>(null)
  const load = () => api('/api/security/overview').then(setO)
  useEffect(() => { load() }, [])
  if (!o) return <Skeleton className="h-[600px]" />
  return (
    <>
      <PageHeader eyebrow="Zero-trust controls" title="Security center" desc="Every control below is live: run the demos to see the tokens expire, the KMS encrypt, and the audit chain verify itself." />
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Tile icon={Server} t="Sandbox isolation" ok={o.sandbox.backend !== 'process'} d={`${o.sandbox.backend} · CPU ${o.sandbox.cpu_limit_s}s · ${o.sandbox.memory_limit_mb} MB`} />
        <Tile icon={Ban} t="Network egress" ok={o.sandbox.backend !== 'process'} d={o.sandbox.egress} />
        <Tile icon={HardDrive} t={<Term t="WORM" />} ok={o.worm.read_only === o.worm.originals} d={`${o.worm.read_only}/${o.worm.originals} originals read-only`} />
        <Tile icon={Fingerprint} t="Malware gateway" ok d={o.malware_engine} />
      </div>
      <Backends b={o.backends} />
      <div className="mt-5 grid gap-5 xl:grid-cols-2">
        <TokenDemo ttl={o.token_ttl_s} />
        <ChainCard initial={o.audit_chain} />
        <KmsDemo kms={o.kms} />
        <div className="card card-pad"><div className="flex items-center gap-2 text-sm font-semibold"><ShieldCheck className="h-4 w-4 text-primary" />Signed rule bundle</div>
          <p className="mt-1 text-xs text-muted">Rules are loaded only if their Ed25519 signature verifies; a tampered YAML stops all analysis.</p>
          <div className="mt-3 space-y-1 text-sm"><Row k="Bundle" v={o.rules_bundle.bundle} /><Row k="Algorithm" v={o.rules_bundle.algorithm} /><Row k="SHA-256" v={<span className="font-mono text-xs">{o.rules_bundle.sha256.slice(0, 32)}…</span>} /><Row k="Signature" v={o.rules_bundle.valid ? <span className="font-semibold text-emerald-600">valid ✓</span> : <span className="font-semibold text-red-600">INVALID</span>} /></div>
        </div>
        <Rbac o={o} />
        {user!.role !== 'college' && <PiiVault admin={user!.role === 'admin'} />}
        <div className="card card-pad xl:col-span-2"><div className="text-sm font-semibold">Recent sandbox jobs (measured)</div>
          <div className="mt-3 overflow-x-auto"><table className="w-full text-sm"><thead><tr className="table-head"><th className="py-2">Job</th><th>Document</th><th>Status</th><th>Duration</th><th>Job token id</th></tr></thead>
            <tbody>{o.sandbox.recent_jobs.map((j: any) => <tr key={j.id} className="border-t border-line"><td className="py-2">#{j.id}</td><td>#{j.document_id}</td><td>{j.status}</td><td className="tabular-nums">{j.duration_ms} ms</td><td className="font-mono text-xs">{j.token_jti}</td></tr>)}</tbody></table></div>
          <p className="mt-2 text-xs text-muted">{o.sandbox.egress}</p>
        </div>
      </div>
    </>
  )
}
const Row = ({ k, v }: any) => <div className="flex justify-between gap-3 border-b border-line/60 py-1.5 last:border-0"><span className="text-muted">{k}</span><span className="text-right">{v}</span></div>
function Tile({ icon: I, t, d, ok }: any) {
  return <div className="card card-pad animate-fadeUp"><div className="flex items-center justify-between"><span className="rounded-xl bg-primary-soft p-2 text-primary"><I className="h-5 w-5" /></span>{ok ? <CheckCircle2 className="h-5 w-5 text-emerald-500" /> : <XCircle className="h-5 w-5 text-red-500" />}</div><div className="mt-3 text-sm font-semibold">{t}</div><div className="mt-0.5 text-xs text-muted">{d}</div></div>
}

function TokenDemo({ ttl }: { ttl: number }) {
  const [tok, setTok] = useState<any>(null); const [left, setLeft] = useState(0); const [res, setRes] = useState<any>(null); const [len, setLen] = useState(10)
  const t = useRef<any>()
  useEffect(() => () => clearInterval(t.current), [])
  const issue = async () => {
    const r = await api('/api/security/token-demo', { method: 'POST', json: { ttl: len } }); setTok(r); setRes(null)
    clearInterval(t.current); const tick = () => setLeft(Math.max(0, r.claims.exp - Math.floor(Date.now() / 1000))); tick(); t.current = setInterval(tick, 250)
  }
  const verify = async () => setRes(await api('/api/security/token-verify', { method: 'POST', json: { token: tok.token } }))
  return (
    <div className="card card-pad"><div className="flex items-center gap-2 text-sm font-semibold"><Timer className="h-4 w-4 text-primary" />Job-scoped tokens ({ttl}s lifetime)</div>
      <p className="mt-1 text-xs text-muted">Each sandbox job gets an HMAC token valid for one job and at most {ttl} seconds. Results returned after expiry are rejected. Try a short token and verify it before and after it expires.</p>
      <div className="mt-3 flex flex-wrap items-center gap-2"><label className="text-xs text-muted" htmlFor="ttl">Lifetime</label><select id="ttl" className="input w-auto py-1.5" value={len} onChange={(e) => setLen(+e.target.value)}>{[5, 10, 30, 60].map((x) => <option key={x} value={x}>{x} s</option>)}</select>
        <button className="btn-primary btn-sm" onClick={issue}>Issue token</button><button className="btn-ghost btn-sm" disabled={!tok} onClick={verify}>Verify now</button></div>
      {tok && <div className="mt-3 flex items-center gap-4">
        <div className="relative h-16 w-16"><svg viewBox="0 0 36 36" className="h-16 w-16 -rotate-90"><circle cx="18" cy="18" r="15.5" fill="none" stroke="rgb(var(--line))" strokeWidth="3" /><circle cx="18" cy="18" r="15.5" fill="none" stroke={left ? 'rgb(var(--primary))' : '#ef4444'} strokeWidth="3" strokeDasharray="97.4" strokeDashoffset={97.4 * (1 - left / len)} style={{ transition: 'stroke-dashoffset .25s linear' }} /></svg><span className="absolute inset-0 flex items-center justify-center font-display text-lg font-bold tabular-nums">{left}</span></div>
        <div className="min-w-0 flex-1 text-xs"><div className="break-all font-mono text-muted">{tok.token.slice(0, 64)}…</div><div className="mt-1">jti <b className="font-mono">{tok.claims.jti}</b> · job #{tok.claims.job}</div></div>
      </div>}
      {res && <div className={clsx('mt-3 rounded-xl p-2.5 text-sm animate-fadeUp', res.valid ? 'bg-emerald-50 text-emerald-800 dark:bg-emerald-500/10 dark:text-emerald-300' : 'bg-red-50 text-red-700 dark:bg-red-500/10 dark:text-red-300')}>{res.valid ? `Valid — ${res.seconds_left}s left. A worker result would be accepted.` : `Rejected — ${res.reason}`}</div>}
    </div>
  )
}

function ChainCard({ initial }: any) {
  const [c, setC] = useState(initial); const [busy, setBusy] = useState(false); const toast = useToast()
  const verify = async () => { setBusy(true); try { const r = await api('/api/audit/verify'); setC(r); toast(r.valid ? 'success' : 'error', r.valid ? 'Audit chain intact' : 'Audit chain broken', r.valid ? `${r.entries} entries re-hashed.` : r.reason) } finally { setBusy(false) } }
  return (
    <div className="card card-pad"><div className="flex items-center gap-2 text-sm font-semibold"><Link2 className="h-4 w-4 text-primary" />Hash-chained audit log</div>
      <p className="mt-1 text-xs text-muted">Every entry stores the SHA-256 of the previous one. Editing or deleting any past row breaks every hash after it. The database layer refuses updates and deletes on this table.</p>
      <div className="mt-3 flex items-center gap-1 overflow-hidden">{Array.from({ length: 7 }).map((_, i) => <div key={i} className="flex items-center"><div className={clsx('flex h-9 w-12 items-center justify-center rounded-lg border-2 text-[10px] font-mono', c.valid ? 'border-emerald-400 bg-emerald-50 dark:bg-emerald-500/10' : 'border-red-400 bg-red-50')}>#{Math.max(1, c.entries - 6 + i)}</div>{i < 6 && <span className="h-0.5 w-3 bg-line" />}</div>)}</div>
      <div className="mt-3 space-y-1 text-sm"><Row k="Entries" v={c.entries} /><Row k="Status" v={c.valid ? <span className="font-semibold text-emerald-600">unbroken ✓</span> : <span className="font-semibold text-red-600">broken at #{c.broken_at}</span>} /><Row k="Head hash" v={<span className="font-mono text-xs">{(c.head || '').slice(0, 24)}…</span>} /></div>
      <button className="btn-primary btn-sm mt-3" onClick={verify} disabled={busy}>{busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />}Re-verify entire chain</button>
    </div>
  )
}

function KmsDemo({ kms }: any) {
  const [p, setP] = useState('ABCDE1234F'); const [r, setR] = useState<any>(null)
  return (
    <div className="card card-pad"><div className="flex items-center gap-2 text-sm font-semibold"><KeyRound className="h-4 w-4 text-primary" />Envelope encryption (<Term t="KMS" />)</div>
      <p className="mt-1 text-xs text-muted">{kms.provider} · key <span className="font-mono">{kms.key_id}</span> · {kms.pii_records} PII records protected.</p>
      <div className="mt-3 flex gap-2"><input className="input py-2" value={p} onChange={(e) => setP(e.target.value)} aria-label="Plaintext to encrypt" /><button className="btn-primary btn-sm" disabled={!p} onClick={() => api('/api/security/kms-demo', { method: 'POST', json: { plaintext: p } }).then(setR)}><Lock className="h-3.5 w-3.5" />Encrypt</button></div>
      {r && <div className="mt-3 space-y-2 text-xs animate-fadeUp">
        {Object.entries(typeof r.envelope === 'string' ? { envelope: r.envelope } : r.envelope).map(([k, v]: any) => <div key={k}><span className="font-semibold">{k}</span><div className="break-all rounded-lg bg-surface-2 p-2 font-mono text-muted">{String(v)}</div></div>)}
        <div className="rounded-lg bg-emerald-50 p-2 text-emerald-800 dark:bg-emerald-500/10 dark:text-emerald-300">Decrypted back: <b>{r.decrypted}</b></div><p className="text-muted">{r.explanation}</p></div>}
    </div>
  )
}

function Rbac({ o }: any) {
  const roles = o.rbac.roles
  return (
    <div className="card card-pad xl:col-span-2"><div className="flex items-center gap-2 text-sm font-semibold"><ShieldCheck className="h-4 w-4 text-primary" /><Term t="RBAC" /> permission matrix</div>
      <p className="mt-1 text-xs text-muted">Enforced on every API call. Plus <Term t="ABAC" />: you are signed in as <b>{o.you.role}</b> with row scope <b>{o.you.row_scope}</b>.</p>
      <div className="mt-3 overflow-x-auto"><table className="w-full text-sm"><thead><tr className="table-head"><th className="py-2">Action</th>{roles.map((r: string) => <th key={r} className="px-3 text-center">{r}</th>)}</tr></thead>
        <tbody>{Object.entries(o.rbac.matrix).map(([a, allowed]: any) => <tr key={a} className="border-t border-line"><td className="py-2">{a}</td>{roles.map((r: string) => <td key={r} className="text-center">{allowed.includes(r) ? <CheckCircle2 className="mx-auto h-4 w-4 text-emerald-500" /> : <span className="text-line">—</span>}</td>)}</tr>)}</tbody></table></div>
    </div>
  )
}

function PiiVault({ admin }: { admin: boolean }) {
  const [rows, setRows] = useState<any[]>([]); const [shown, setShown] = useState<Record<number, string>>({}); const toast = useToast()
  useEffect(() => { api('/api/security/pii').then(setRows).catch(() => {}) }, [])
  const reveal = async (id: number) => { const justification = window.prompt('Reason for revealing this value (min 20 characters, e.g. case reference). This is audited.') || ''; if (!justification) return; try { const r = await api(`/api/security/pii/${id}/reveal`, { method: 'POST', json: { justification } }); setShown((s) => ({ ...s, [id]: r.value })); toast('info', 'PII revealed', 'This access was written to the audit log.') } catch (e: any) { toast('error', 'Not allowed', e.message) } }
  return (
    <div className="card card-pad xl:col-span-2"><div className="flex items-center gap-2 text-sm font-semibold"><Eye className="h-4 w-4 text-primary" /><Term t="PII" /> vault</div>
      <p className="mt-1 text-xs text-muted">PAN numbers found in faculty lists are stored encrypted and shown masked. Cross-college matching uses an HMAC blind index, so no one needs the plain value. {admin ? 'As Administrator you may reveal a value with a written justification; each reveal is audited and alerted.' : 'Only an Administrator can reveal a value.'}</p>
      <div className="mt-3 overflow-x-auto"><table className="w-full text-sm"><thead><tr className="table-head"><th className="py-2">Institution</th><th>Type</th><th>Masked</th><th>Ciphertext</th><th>Key</th><th /></tr></thead>
        <tbody>{rows.map((p) => <tr key={p.id} className="border-t border-line"><td className="py-2">{p.college}</td><td>{p.kind}</td><td className="font-mono">{shown[p.id] || p.masked}</td><td className="max-w-[220px] truncate font-mono text-xs text-muted">{p.ciphertext}</td><td className="font-mono text-xs">{p.key_id}</td>
          <td className="text-right">{admin && !shown[p.id] && <button className="btn-ghost btn-sm" onClick={() => reveal(p.id)}>Reveal</button>}</td></tr>)}</tbody></table></div>
    </div>
  )
}

const DEV_ONLY: Record<string, string[]> = { database: ['sqlite'], auth: ['local'], sandbox: ['process'], kms: ['soft'], storage: ['fs'], queue: ['thread'], env: ['development'] }
const LABEL: Record<string, string> = { database: 'Database', auth: 'Login', sandbox: 'Sandbox', kms: 'Key management', storage: 'Write-once storage', queue: 'Job queue', vision: 'Photo vision', llm: 'LLM wording', notify: 'Alert channels', revocation: 'OCSP / CRL', issuer_connectors: 'Issuer connectors', env: 'Environment' }
function Backends({ b }: { b: Record<string, unknown> }) {
  return (
    <div className="card card-pad mt-5" data-testid="active-backends">
      <div className="flex items-center gap-2 text-sm font-semibold"><Server className="h-4 w-4 text-primary" />Active backends on this server</div>
      <p className="mt-1 text-xs text-muted">Each is chosen by an environment variable. Amber marks a development fallback; ENV=production refuses to start with the unsafe ones.</p>
      <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        {Object.entries(b).map(([k, v]) => {
          const dev = (DEV_ONLY[k] || []).some((x) => String(v).startsWith(x))
          return <div key={k} className={clsx('rounded-xl border px-3 py-2', dev ? 'border-amber-300 bg-amber-50 dark:border-amber-500/40 dark:bg-amber-500/10' : 'border-line')}>
            <div className="text-[11px] font-semibold uppercase tracking-wide text-muted">{LABEL[k] || k}</div>
            <div className="mt-0.5 break-words font-mono text-sm">{String(v)}</div>{dev && <div className="text-[11px] text-amber-700 dark:text-amber-300">dev fallback</div>}</div>
        })}
      </div>
    </div>
  )
}
