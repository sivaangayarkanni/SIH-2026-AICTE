import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { CalendarDays, ChevronLeft, ChevronRight, Copy, Download, List } from 'lucide-react'
import clsx from 'clsx'
import { api, getToken } from '../lib/api'
import { PageHeader, Skeleton, Tabs, Empty } from '../components/ui'
import { useToast } from '../components/Toast'
import { Safeguard } from '../components/Safeguard'

const LABEL: Record<string, string> = { submission_deadline: 'Submission deadline', stage_sla: 'Stage timeline', evc_visit: 'EVC visit', undertaking: 'Undertaking', document_validity: 'Document expiry' }
const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

export default function Calendar() {
  const [month, setMonth] = useState(() => { const d = new Date(); return new Date(d.getFullYear(), d.getMonth(), 1) })
  const [view, setView] = useState('month'); const [data, setData] = useState<any>(null); const [sub, setSub] = useState<any>(null); const toast = useToast()
  const start = useMemo(() => { const d = new Date(month); d.setDate(1 - ((d.getDay() + 6) % 7)); return d }, [month])
  useEffect(() => {
    const end = new Date(start); end.setDate(end.getDate() + (view === 'month' ? 41 : 120))
    setData(null); api(`/api/wf/calendar?start=${iso(start)}&end=${iso(end)}`).then(setData)
  }, [start, view])
  const byDay = useMemo(() => { const m: Record<string, any[]> = {}; (data?.events || []).forEach((e: any) => { (m[e.date] ||= []).push(e) }); return m }, [data])
  const today = iso(new Date())
  const ics = async () => {
    const r = await fetch('/api/wf/calendar/subscription', { headers: { Authorization: `Bearer ${getToken()}` } }).then((x) => x.json()); setSub(r)
  }
  return (
    <>
      <PageHeader eyebrow="Timelines" title="Deadline calendar" desc="Submission deadlines, stage timelines, EVC visits, undertakings and document expiry dates in one place."
        actions={<button className="btn-ghost" data-testid="ics-subscribe" onClick={ics}><CalendarDays className="h-4 w-4" />Subscribe (ICS)</button>} />
      <Safeguard />
      {sub && <div className="card card-pad mb-4 text-sm" data-testid="ics-box"><div className="font-semibold">Calendar subscription link</div><p className="text-xs text-muted">{sub.note}</p>
        <div className="mt-2 flex flex-wrap gap-2"><code className="max-w-full truncate rounded bg-surface-2 px-2 py-1 text-xs">{sub.url}</code>
          <button className="btn-ghost btn-sm" onClick={() => { navigator.clipboard?.writeText(sub.url); toast('success', 'Link copied') }}><Copy className="h-3.5 w-3.5" />Copy</button>
          <a className="btn-ghost btn-sm" href={sub.url}><Download className="h-3.5 w-3.5" />Download .ics</a></div></div>}
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <button className="btn-ghost btn-sm" aria-label="Previous month" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() - 1, 1))}><ChevronLeft className="h-4 w-4" /></button>
        <div className="min-w-[150px] text-center font-display text-lg font-bold">{month.toLocaleDateString('en-IN', { month: 'long', year: 'numeric' })}</div>
        <button className="btn-ghost btn-sm" aria-label="Next month" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() + 1, 1))}><ChevronRight className="h-4 w-4" /></button>
        <button className="btn-ghost btn-sm" onClick={() => { const d = new Date(); setMonth(new Date(d.getFullYear(), d.getMonth(), 1)) }}>Today</button>
        <span className="flex-1" />
        <div className="flex flex-wrap gap-2 text-xs" data-testid="cal-legend">{Object.entries(LABEL).map(([k, l]) => <span key={k} className="inline-flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-full" style={{ background: data?.colors?.[k] || '#999' }} />{l}</span>)}</div>
        <Tabs value={view} onChange={setView} tabs={[{ id: 'month', label: <span className="inline-flex items-center gap-1"><CalendarDays className="h-3.5 w-3.5" />Month</span> }, { id: 'agenda', label: <span className="inline-flex items-center gap-1"><List className="h-3.5 w-3.5" />Agenda</span> }]} />
      </div>
      {!data ? <Skeleton className="h-[560px]" /> : view === 'month' ? (
        <div className="card overflow-hidden p-0" data-testid="cal-month">
          <div className="grid grid-cols-7 border-b border-line bg-surface-2 text-center text-xs font-semibold text-muted">{['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map((d) => <div key={d} className="py-2">{d}</div>)}</div>
          <div className="grid grid-cols-7">{Array.from({ length: 42 }).map((_, i) => {
            const d = new Date(start); d.setDate(d.getDate() + i); const k = iso(d); const ev = byDay[k] || []; const out = d.getMonth() !== month.getMonth()
            return <div key={k} className={clsx('min-h-[96px] border-b border-r border-line p-1.5 text-xs', out && 'bg-surface-2/50 text-muted')}>
              <div className={clsx('mb-1 inline-flex h-5 w-5 items-center justify-center rounded-full font-semibold', k === today && 'bg-primary text-primary-fg')}>{d.getDate()}</div>
              {ev.slice(0, 3).map((e: any) => <Link key={e.id} to={e.link} title={e.title} className={clsx('mb-0.5 block truncate rounded px-1 py-0.5 text-white', e.overdue && 'ring-2 ring-red-500')} style={{ background: e.color }}>{e.overdue ? '⚠ ' : ''}{e.title}</Link>)}
              {ev.length > 3 && <div className="text-muted">+{ev.length - 3} more</div>}
            </div>
          })}</div>
        </div>
      ) : (
        <div className="card p-0" data-testid="cal-agenda">{data.events.length === 0 ? <div className="p-4"><Empty title="Nothing scheduled in this range." /></div> :
          <ul>{data.events.map((e: any) => <li key={e.id} className="flex items-center gap-3 border-b border-line/60 px-5 py-2.5 last:border-0">
            <span className="w-28 shrink-0 font-mono text-xs">{new Date(e.date).toLocaleDateString('en-IN', { dateStyle: 'medium' })}</span>
            <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: e.color }} />
            <Link to={e.link} className="min-w-0 flex-1 truncate text-sm hover:text-primary">{e.title}</Link>
            <span className="chip bg-surface-2 text-muted">{LABEL[e.kind]}</span>{e.overdue && <span className="chip bg-red-100 text-red-800">overdue</span>}</li>)}</ul>}</div>
      )}
    </>
  )
}
