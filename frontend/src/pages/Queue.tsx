import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, Info, ListOrdered } from 'lucide-react'
import { api, fmtDay } from '../lib/api'
import { PageHeader, StatusChip, RiskBadge, DecisionChip, Skeleton, Empty } from '../components/ui'
import { Avatar } from '../components/Avatar'

export default function Queue() {
  const [q, setQ] = useState<any[] | null>(null); const [show, setShow] = useState<'open' | 'all'>('open')
  useEffect(() => { api('/api/officer/queue').then(setQ) }, [])
  const list = (q || []).filter((a) => show === 'all' || !a.decision)
  return (
    <>
      <PageHeader eyebrow="Scrutiny" title="Priority queue" desc="Sorted automatically so the riskiest, most urgent and longest-waiting applications are reviewed first."
        actions={<div className="flex rounded-xl bg-surface-2 p-1">{(['open', 'all'] as const).map((s) => <button key={s} onClick={() => setShow(s)} className={`rounded-lg px-3 py-1.5 text-sm font-semibold ${show === s ? 'bg-surface text-primary shadow-sm' : 'text-muted'}`}>{s === 'open' ? 'Awaiting decision' : 'All submitted'}</button>)}</div>} />
      <div className="mb-4 flex items-start gap-2 rounded-xl border border-line bg-surface p-3 text-sm"><Info className="mt-0.5 h-4 w-4 shrink-0 text-primary" /><span><b>Priority score</b> = 0.5 × risk (from the policy engine) + 0.3 × deadline urgency (100 when due today) + 0.2 × waiting time (100 after 72 h). Each part is shown below so the order is explainable.</span></div>
      {!q ? <div className="space-y-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-28" />)}</div> : list.length === 0 ? <Empty icon={ListOrdered} title="Queue is clear" body="No submitted applications are waiting for a decision." /> : (
        <div className="space-y-3" data-tour="queue">{list.map((a, i) => (
          <Link key={a.id} to={`/applications/${a.id}`} className="card group flex flex-wrap items-center gap-5 p-4 transition hover:-translate-y-0.5 hover:border-primary hover:shadow-pop animate-fadeUp" style={{ animationDelay: `${i * 60}ms` }}>
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-primary-soft font-display text-lg font-bold text-primary">{i + 1}</div>
            <Avatar seed={a.college} size={44} />
            <div className="min-w-[220px] flex-1"><div className="flex flex-wrap items-center gap-2"><b>{a.ref}</b><StatusChip status={a.status} /><DecisionChip d={a.decision} /></div><div className="text-sm text-muted">{a.college}, {a.college_city} · {a.category_label}</div></div>
            <div className="grid grid-cols-3 gap-5 text-center text-xs">
              <div><div className="text-muted">Risk</div><RiskBadge score={a.risk_score} /></div>
              <div><div className="text-muted">Deadline</div><b className={a.priority.days_to_deadline <= 2 ? 'text-red-600' : ''}>{fmtDay(a.deadline)}</b><div className="text-muted">{a.priority.deadline_urgency} urgency</div></div>
              <div><div className="text-muted">Waiting</div><b>{a.priority.waiting_hours} h</b><div className="text-muted">{a.priority.waiting} pts</div></div>
            </div>
            <div className="text-center"><div className="text-[11px] font-semibold uppercase text-muted">Priority</div><div className="font-display text-3xl font-bold tabular-nums text-primary">{a.priority.score}</div></div>
            <ArrowRight className="h-5 w-5 text-muted transition group-hover:translate-x-1 group-hover:text-primary" />
          </Link>
        ))}</div>
      )}
    </>
  )
}
