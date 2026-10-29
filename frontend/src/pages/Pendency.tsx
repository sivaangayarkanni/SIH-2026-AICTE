import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { AlarmClock, BellRing, ClipboardCheck, FileClock, Hourglass, Layers, Undo2 } from 'lucide-react'
import clsx from 'clsx'
import { api, fmtDate, fmtDay } from '../lib/api'
import { PageHeader, Skeleton, Stat, Tabs, Empty } from '../components/ui'
import { Safeguard } from '../components/Safeguard'
import { useAuth } from '../lib/auth'

function Bars({ data, testid }: { data: Record<string, number>; testid?: string }) {
  const max = Math.max(1, ...Object.values(data))
  const e = Object.entries(data)
  if (!e.length) return <div className="text-sm text-muted">No items.</div>
  return <ul className="space-y-1.5" data-testid={testid}>{e.map(([k, v]) => <li key={k} className="text-sm"><div className="flex justify-between"><span className="truncate">{k}</span><b>{v}</b></div>
    <div className="h-1.5 rounded-full bg-surface-2"><div className="h-full rounded-full bg-primary" style={{ width: `${(v / max) * 100}%` }} /></div></li>)}</ul>
}

export default function Pendency() {
  const [d, setD] = useState<any>(null); const [tab, setTab] = useState('region'); const { user } = useAuth()
  useEffect(() => { api('/api/wf/dashboard').then(setD) }, [])
  if (!d) return <Skeleton className="h-[600px]" />
  const t = d.totals
  const dims: Record<string, any> = { region: d.by_region, stage: d.by_stage, officer: d.by_officer, institution: d.by_institution }
  return (
    <>
      <PageHeader eyebrow="Monitoring" title="Pendency & deadlines" desc={<>{d.scope?.label} · as of {fmtDate(d.as_of)}</>} />
      <Safeguard />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7" data-testid="pend-stats">
        <Stat icon={Layers} label="In workflow" value={t.in_workflow} />
        <Stat icon={Hourglass} label="Due in 3 days" value={t.approaching} tone="amber" />
        <Stat icon={AlarmClock} label="Overdue" value={t.overdue} tone="red" />
        <Stat icon={Undo2} label="With institution" value={t.returned} tone="purple" />
        <Stat icon={ClipboardCheck} label="Awaiting decision" value={t.awaiting_decision} tone="green" />
        <Stat icon={BellRing} label="Open alerts" value={t.open_alerts} />
        <Stat icon={FileClock} label="Escalations" value={t.escalations} tone="red" />
      </div>
      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <div className="card card-pad lg:col-span-2">
          <div className="mb-3 flex items-center justify-between"><div className="font-semibold">Pending applications by</div>
            <Tabs value={tab} onChange={setTab} tabs={[{ id: 'region', label: 'Region' }, { id: 'stage', label: 'Stage' }, { id: 'officer', label: 'Officer' }, ...(user?.role !== 'college' ? [{ id: 'institution', label: 'Institution' }] : [])]} /></div>
          <Bars data={dims[tab] || {}} testid="pend-bars" />
        </div>
        <div className="card card-pad"><div className="mb-3 font-semibold">Ageing (days in current stage)</div><Bars data={d.ageing} testid="pend-ageing" /></div>
      </div>
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <div className="card p-0"><div className="border-b border-line px-5 py-3 font-semibold text-red-700 dark:text-red-300">Overdue ({d.overdue.length})</div>
          {d.overdue.length ? <table className="w-full text-sm"><tbody>{d.overdue.map((r: any) => <tr key={r.id} className="border-b border-line/60 last:border-0"><td className="px-5 py-2"><Link className="font-mono text-xs text-primary" to={`/applications/${r.id}`}>{r.ref}</Link><div className="text-xs text-muted">{r.college}</div></td><td>{r.stage}<div className="text-xs text-muted">{r.region}</div></td><td className="pr-5 text-right font-semibold text-red-600">{r.days_overdue} d late</td></tr>)}</tbody></table> : <div className="p-4"><Empty title="Nothing overdue." /></div>}</div>
        <div className="card p-0"><div className="border-b border-line px-5 py-3 font-semibold text-amber-700 dark:text-amber-300">Approaching deadline ({d.approaching.length})</div>
          {d.approaching.length ? <table className="w-full text-sm"><tbody>{d.approaching.map((r: any) => <tr key={r.id} className="border-b border-line/60 last:border-0"><td className="px-5 py-2"><Link className="font-mono text-xs text-primary" to={`/applications/${r.id}`}>{r.ref}</Link><div className="text-xs text-muted">{r.college}</div></td><td>{r.stage}</td><td className="pr-5 text-right">due {fmtDay(r.due)}</td></tr>)}</tbody></table> : <div className="p-4"><Empty title="Nothing due in the next few days." /></div>}</div>
      </div>
      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <div className="card card-pad"><div className="mb-2 font-semibold">Bottlenecks (mean days per stage)</div>
          {d.bottlenecks.length ? <ul className="space-y-1 text-sm">{d.bottlenecks.map((b: any) => <li key={b.stage} className="flex justify-between"><span>{b.stage}</span><span className={clsx(b.sla_days && b.mean_days > b.sla_days && 'font-semibold text-red-600')}>{b.mean_days} d / SLA {b.sla_days ?? '—'} (n={b.n})</span></li>)}</ul> : <div className="text-sm text-muted">No stage history yet.</div>}</div>
        <div className="card card-pad text-sm"><div className="mb-2 font-semibold">EVC · Undertakings · Validity</div>
          <div>EVC: {d.evc.to_schedule} to schedule, {d.evc.scheduled} scheduled, {d.evc.completed} completed, <b className="text-red-600">{d.evc.overdue} overdue</b></div>
          <div className="mt-1">Undertakings: {d.undertakings.open} open, {d.undertakings.submitted} awaiting verification, {d.undertakings.verified} verified, <b className="text-red-600">{d.undertakings.overdue} overdue</b></div>
          <div className="mt-1">Validity: {d.validity.tracked} tracked, {d.validity.expiring_60d} expiring ≤60 d, <b className="text-red-600">{d.validity.expired} expired</b>, {d.validity.renewal_pending} renewals pending</div></div>
        <div className="card p-0" data-testid="pend-alerts"><div className="border-b border-line px-5 py-3 font-semibold">Alerts & escalations</div>
          <ul className="max-h-72 overflow-auto">{d.alerts.slice(0, 30).map((a: any) => <li key={a.id} className="border-b border-line/60 px-5 py-2 text-xs last:border-0">
            <span className={clsx('chip mr-1', a.level === 'escalation' ? 'bg-red-100 text-red-800' : 'bg-amber-100 text-amber-800')}>{a.level}</span>{a.message}</li>)}
            {!d.alerts.length && <li className="px-5 py-3 text-sm text-muted">No open alerts.</li>}</ul></div>
      </div>
    </>
  )
}
