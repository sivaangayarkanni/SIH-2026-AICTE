import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip, BarChart, Bar, XAxis, YAxis, CartesianGrid } from 'recharts'
import { FileStack, AlertTriangle, ShieldCheck, Clock, ArrowRight, FilePlus2, ClipboardCheck, ShieldAlert, CheckCircle2, Link2, Sparkles } from 'lucide-react'
import { useAuth } from '../lib/auth'
import { api, fmtDay } from '../lib/api'
import { StartTourButton } from '../components/Tour'
import { PageHeader, Stat, Ring, StatusChip, RiskBadge, Skeleton, Empty, DecisionChip, Term } from '../components/ui'
import { Avatar } from '../components/Avatar'

export const STATUS_COLORS: Record<string, string> = {
  'Verified': '#10b981', 'Mismatch Detected': '#f59e0b', 'Expired': '#ef4444', 'Verification Pending': '#3b82f6', 'Source Unavailable': '#94a3b8', 'Manual Review Required': '#a855f7',
}

export default function Dashboard() {
  const { user } = useAuth()
  return user!.role === 'college' ? <CollegeDash /> : <StaffDash />
}

function greeting() { const h = new Date().getHours(); return h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening' }

function CollegeDash() {
  const { user } = useAuth()
  const [apps, setApps] = useState<any[] | null>(null); const [cur, setCur] = useState<any>(null)
  useEffect(() => { api('/api/applications').then((a) => { setApps(a); const p = a.find((x: any) => x.submitted_at) || a[0]; if (p) api(`/api/applications/${p.id}`).then(setCur) }) }, [])
  return (
    <>
      <PageHeader eyebrow={user!.college || ''} title={`${greeting()}, ${user!.name}`} desc="Here is where your AICTE approval stands. Fix the highlighted items before the deadline to avoid rejection."
        actions={<><Link to="/readiness" className="btn-ghost"><ClipboardCheck className="h-4 w-4" />Pre-check a file</Link><Link to="/applications/new" className="btn-primary"><FilePlus2 className="h-4 w-4" />New application</Link></>} />
      {!apps ? <div className="grid gap-5 lg:grid-cols-3"><Skeleton className="h-72" /><Skeleton className="h-72 lg:col-span-2" /></div> : apps.length === 0 ? (
        <Empty icon={FilePlus2} title="No applications yet" body="Start an application. We will show you the exact checklist of documents AICTE needs for your category." action={<Link to="/applications/new" className="btn-primary">Start an application</Link>} />
      ) : (
        <>
          <div className="grid gap-5 lg:grid-cols-3">
            <div className="card card-pad flex flex-col items-center text-center">
              <div className="self-start text-sm font-semibold">Approval readiness</div>
              {cur ? <><div className="my-4"><Ring value={cur.readiness.score} size={150} label="ready" /></div>
                <div className="text-sm font-semibold">{cur.ref}</div><div className="text-xs text-muted">{cur.category_label}</div>
                <p className="mt-3 text-xs leading-relaxed text-muted">{cur.readiness.explanation}</p>
                <Link to={`/applications/${cur.id}`} className="btn-primary mt-4 w-full">Open application<ArrowRight className="h-4 w-4" /></Link></> : <Skeleton className="mt-4 h-52 w-full" />}
            </div>
            <div className="card card-pad lg:col-span-2">
              <div className="mb-3 flex items-center justify-between"><div className="text-sm font-semibold">What needs your attention</div>{cur && <StatusChip status={cur.status} />}</div>
              {!cur ? <Skeleton className="h-52" /> : (
                <ul className="space-y-2">
                  {cur.readiness.items.filter((i: any) => i.state !== 'Verified').length === 0 && <li className="flex items-center gap-3 rounded-xl bg-emerald-50 p-3 text-sm text-emerald-800 dark:bg-emerald-500/10 dark:text-emerald-300"><CheckCircle2 className="h-5 w-5" />Every required document is verified. Nothing to fix.</li>}
                  {cur.readiness.items.filter((i: any) => i.state !== 'Verified').map((i: any) => (
                    <li key={i.doc_type} className="flex items-center gap-3 rounded-xl border border-line p-3">
                      <span className={`rounded-lg p-2 ${i.state === 'missing' ? 'bg-red-100 text-red-700 dark:bg-red-500/15' : 'bg-amber-100 text-amber-700 dark:bg-amber-500/15'}`}><AlertTriangle className="h-4 w-4" /></span>
                      <span className="min-w-0 flex-1"><span className="block text-sm font-semibold">{i.label}</span><span className="block text-xs text-muted">{i.message}</span></span>
                      {i.state === 'missing' ? <span className="chip bg-red-100 text-red-800 dark:bg-red-500/15 dark:text-red-300">Missing</span> : <StatusChip status={i.state} />}
                    </li>
                  ))}
                  {cur.readiness.items.filter((i: any) => i.state === 'Verified').length > 0 && <li className="pt-1 text-xs text-muted">{cur.readiness.items.filter((i: any) => i.state === 'Verified').length} document(s) verified — no action needed.</li>}
                </ul>
              )}
              {cur?.guidance && <div className="mt-4 rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm dark:border-amber-500/30 dark:bg-amber-500/10"><b>Officer feedback:</b> {cur.guidance.reason} <Link className="font-semibold text-primary" to={`/applications/${cur.id}`}>See step-by-step fixes →</Link></div>}
            </div>
          </div>
          <div className="card mt-5 overflow-hidden">
            <div className="border-b border-line px-5 py-3.5 text-sm font-semibold">Your applications</div>
            <AppTable apps={apps} />
          </div>
        </>
      )}
    </>
  )
}

function StaffDash() {
  const { user } = useAuth()
  const [st, setSt] = useState<any>(null); const [q, setQ] = useState<any[] | null>(null); const [sec, setSec] = useState<any>(null); const [meta, setMeta] = useState<any>(null)
  useEffect(() => { api('/api/stats').then(setSt); api('/api/officer/queue').then(setQ); api('/api/security/overview').then(setSec); api('/api/meta').then(setMeta) }, [])
  const pie = st ? Object.entries(st.by_status).map(([k, v]) => ({ name: k, value: v as number })) : []
  const catLabel = (id: string) => meta?.categories.find((c: any) => c.id === id)?.label.replace(/\(.*\)/, '').trim() || id
  const bars = st ? Object.entries(st.by_category).map(([k, v]) => ({ name: catLabel(k), value: v as number })) : []
  return (
    <>
      <PageHeader eyebrow={user!.role_label} title={`${greeting()}, ${user!.name}`}
        desc="Highest-risk, closest-deadline applications are at the top of your queue. Every finding links to on-page evidence."
        actions={<div className="flex flex-wrap gap-2"><StartTourButton /><Link to="/queue" className="btn-primary">Open priority queue<ArrowRight className="h-4 w-4" /></Link></div>} />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat icon={FileStack} label="Applications" value={st?.applications ?? '–'} hint={`${st?.documents ?? '–'} documents analysed`} />
        <Stat icon={Clock} label="Awaiting decision" value={st?.pending_review ?? '–'} hint="Submitted, no final decision" tone="amber" />
        <Stat icon={ShieldAlert} label="Overrides pending" value={st?.overrides_pending ?? '–'} hint="Need a Senior Officer" tone="purple" />
        <Stat icon={AlertTriangle} label="Average risk" value={st ? `${st.avg_risk}` : '–'} hint="0 = clean · 100 = forgery indicators" tone="red" />
      </div>
      <div className="mt-5 grid gap-5 xl:grid-cols-3">
        <div className="card card-pad">
          <div className="text-sm font-semibold">Documents by verification status</div>
          {!st ? <Skeleton className="mt-4 h-56" /> : <div className="h-56"><ResponsiveContainer><PieChart>
            <Pie data={pie} dataKey="value" nameKey="name" innerRadius={52} outerRadius={84} paddingAngle={3} stroke="none">{pie.map((p) => <Cell key={p.name} fill={STATUS_COLORS[p.name]} />)}</Pie>
            <Tooltip contentStyle={{ borderRadius: 12, border: '1px solid rgb(var(--line))', background: 'rgb(var(--surface))', color: 'rgb(var(--ink))' }} />
          </PieChart></ResponsiveContainer></div>}
          <div className="grid grid-cols-2 gap-1.5 text-xs">{pie.map((p) => <div key={p.name} className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full" style={{ background: STATUS_COLORS[p.name] }} />{p.name}<b className="ml-auto tabular-nums">{p.value}</b></div>)}</div>
        </div>
        <div className="card card-pad">
          <div className="text-sm font-semibold">Applications by category</div>
          {!st ? <Skeleton className="mt-4 h-64" /> : <div className="mt-2 h-64"><ResponsiveContainer><BarChart data={bars} layout="vertical" margin={{ left: 10, right: 16 }}>
            <CartesianGrid horizontal={false} stroke="rgb(var(--line))" /><XAxis type="number" allowDecimals={false} tick={{ fontSize: 11, fill: 'rgb(var(--muted))' }} />
            <YAxis type="category" dataKey="name" width={130} tick={{ fontSize: 11, fill: 'rgb(var(--muted))' }} />
            <Tooltip cursor={{ fill: 'rgb(var(--primary-soft))' }} contentStyle={{ borderRadius: 12, background: 'rgb(var(--surface))', border: '1px solid rgb(var(--line))' }} />
            <Bar dataKey="value" fill="rgb(var(--primary))" radius={[0, 6, 6, 0]} barSize={22} />
          </BarChart></ResponsiveContainer></div>}
        </div>
        <div className="card card-pad">
          <div className="text-sm font-semibold">Trust posture</div>
          {!sec ? <Skeleton className="mt-4 h-60" /> : <ul className="mt-3 space-y-2.5 text-sm">
            <Posture ok={sec.audit_chain.valid} t="Audit hash chain" d={`${sec.audit_chain.entries} entries, ${sec.audit_chain.valid ? 'unbroken' : 'BROKEN at #' + sec.audit_chain.broken_at}`} icon={Link2} />
            <Posture ok={sec.rules_bundle.valid} t="Rule bundle signature" d={`Ed25519 · ${sec.rules_bundle.sha256.slice(0, 12)}…`} icon={ShieldCheck} />
            <Posture ok={sec.worm.read_only === sec.worm.originals} t={<><Term t="WORM" /> originals</>} d={`${sec.worm.read_only}/${sec.worm.originals} stored read-only`} icon={FileStack} />
            <Posture ok t="Sandbox isolation" d={`CPU ${sec.sandbox.cpu_limit_s}s · ${sec.sandbox.memory_limit_mb} MB · egress blocked`} icon={Sparkles} />
            <Link to="/security" className="btn-ghost btn-sm mt-1 w-full">Open security center</Link>
          </ul>}
        </div>
      </div>
      <div className="card mt-5 overflow-hidden">
        <div className="flex items-center justify-between border-b border-line px-5 py-3.5"><span className="text-sm font-semibold">Top of the priority queue</span><span className="text-xs text-muted">Priority = 0.5×risk + 0.3×deadline urgency + 0.2×waiting time</span></div>
        {!q ? <div className="p-5"><Skeleton className="h-40" /></div> : <AppTable apps={q.slice(0, 5)} staff />}
      </div>
    </>
  )
}

function Posture({ ok, t, d, icon: I }: any) {
  return <li className="flex items-center gap-3 rounded-xl bg-surface-2 p-2.5"><span className={`rounded-lg p-1.5 ${ok ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15' : 'bg-red-100 text-red-700'}`}><I className="h-4 w-4" /></span><span className="min-w-0 flex-1"><span className="block text-[13px] font-semibold">{t}</span><span className="block truncate text-xs text-muted">{d}</span></span>{ok ? <CheckCircle2 className="h-4 w-4 text-emerald-500" /> : <AlertTriangle className="h-4 w-4 text-red-500" />}</li>
}

export function AppTable({ apps, staff }: { apps: any[]; staff?: boolean }) {
  if (!apps.length) return <div className="p-5"><Empty title="Nothing here yet" body="Applications appear here once created." /></div>
  return (
    <div className="overflow-x-auto"><table className="w-full text-sm">
      <thead className="bg-surface-2"><tr className="table-head">{['Reference', staff ? 'Institution' : 'Category', 'Status', 'Risk', staff ? 'Priority' : 'Docs', 'Deadline', ''].map((h) => <th key={h} className="px-5 py-2.5">{h}</th>)}</tr></thead>
      <tbody>{apps.map((a) => (
        <tr key={a.id} className="border-t border-line transition hover:bg-surface-2">
          <td className="px-5 py-3"><Link to={`/applications/${a.id}`} className="font-semibold text-primary hover:underline">{a.ref}</Link><div className="text-xs text-muted">{staff ? a.category_label : a.academic_year}</div></td>
          <td className="px-5 py-3">{staff ? <div className="flex items-center gap-2.5"><Avatar seed={a.college} size={28} /><div><div className="font-medium">{a.college}</div><div className="text-xs text-muted">{a.college_city}</div></div></div> : a.category_label}</td>
          <td className="px-5 py-3"><div className="flex flex-wrap gap-1"><StatusChip status={a.submitted_at ? a.status : 'Draft'} /><DecisionChip d={a.decision} /></div></td>
          <td className="px-5 py-3"><RiskBadge score={a.risk_score} /></td>
          <td className="px-5 py-3 tabular-nums">{staff ? <b>{a.priority.score}</b> : a.documents_count}</td>
          <td className="px-5 py-3"><div>{fmtDay(a.deadline)}</div><div className={`text-xs ${a.priority.days_to_deadline <= 2 ? 'font-semibold text-red-600' : 'text-muted'}`}>{a.priority.days_to_deadline <= 0 ? 'Overdue' : `${a.priority.days_to_deadline} day(s) left`}</div></td>
          <td className="px-5 py-3 text-right"><Link to={`/applications/${a.id}`} className="btn-ghost btn-sm">Open<ArrowRight className="h-3.5 w-3.5" /></Link></td>
        </tr>
      ))}</tbody>
    </table></div>
  )
}
