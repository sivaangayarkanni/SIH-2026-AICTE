import { useEffect, useState } from 'react'
import { Bell, Send, Mail, MessageSquare, Webhook, Radio, ShieldAlert } from 'lucide-react'
import clsx from 'clsx'
import { api, fmtDate } from '../lib/api'
import { useAuth } from '../lib/auth'
import { PageHeader, Skeleton, Empty } from '../components/ui'
import { useToast } from '../components/Toast'

const SEV: Record<string, string> = {
  critical: 'bg-red-100 text-red-800 dark:bg-red-500/15 dark:text-red-300', high: 'bg-orange-100 text-orange-800 dark:bg-orange-500/15 dark:text-orange-300',
  medium: 'bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300', info: 'bg-surface-2 text-muted',
}
const ICON: Record<string, any> = { email: Mail, sms: MessageSquare, webhook: Webhook, slack: MessageSquare, siem: Radio, inapp: Bell }

export default function Notifications() {
  const { user } = useAuth(); const toast = useToast()
  const [notes, setNotes] = useState<any[] | null>(null); const [box, setBox] = useState<any>(null)
  const admin = user!.role === 'admin'
  const load = () => { api('/api/notifications').then(setNotes); if (admin) api('/api/notifications/outbox').then(setBox) }
  useEffect(() => { load() }, [])
  if (!notes) return <Skeleton className="h-[500px]" />
  return (
    <>
      <PageHeader eyebrow="Alerts" title="Notification centre" desc="In-app alerts for your role. Security events also go to the configured external channels through a retry queue."
        actions={admin ? <button data-testid="send-test-alert" className="btn-primary" onClick={() => api('/api/notifications/test', { method: 'POST', json: { kind: 'sandbox_violation' } }).then(() => { toast('success', 'Test alert queued', 'Check the outbox below.'); setTimeout(load, 800) })}><Send className="h-4 w-4" />Send test alert</button> : undefined} />
      <div className={clsx('grid gap-5', admin && 'xl:grid-cols-[1.1fr_1fr]')}>
        <div className="card p-0" data-testid="notification-list">
          <div className="border-b border-line px-5 py-3 text-sm font-semibold">Inbox ({notes.length})</div>
          {notes.length === 0 ? <div className="p-4"><Empty title="You are all caught up." /></div> : <ul>{notes.map((n) => (
            <li key={n.id} className="flex items-start gap-3 border-b border-line/60 px-5 py-3 last:border-0">
              <span className={clsx('mt-1.5 h-2 w-2 shrink-0 rounded-full', n.read ? 'bg-line' : 'bg-accent')} />
              <span className="min-w-0 flex-1"><span className="block break-words text-sm">{n.message}</span><span className="text-xs text-muted">{fmtDate(n.created_at)}{n.kind && <> · <span className="font-mono">{n.kind}</span></>}</span></span>
              <span className={clsx('chip shrink-0', SEV[n.severity] || SEV.info)}>{n.severity || 'info'}</span>
            </li>))}</ul>}
        </div>
        {admin && box && <div className="card card-pad" data-testid="outbox">
          <div className="flex items-center gap-2 text-sm font-semibold"><ShieldAlert className="h-4 w-4 text-primary" />External channels</div>
          <div className="mt-3 flex flex-wrap gap-2">{Object.entries(box.configured).map(([c, on]: any) => { const I = ICON[c] || Bell; return <span key={c} className={clsx('chip gap-1', on ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-500/15 dark:text-emerald-300' : 'bg-surface-2 text-muted')}><I className="h-3.5 w-3.5" />{c}{on ? ' · on' : ' · not configured'}</span> })}</div>
          <div className="mt-4 text-xs font-semibold uppercase tracking-wide text-muted">Delivery outbox (retries with backoff, then dead-letter)</div>
          {box.items.length === 0 ? <p className="mt-2 text-sm text-muted">No external deliveries yet. Set NOTIFY_CHANNELS to turn on email, SMS, webhook, Slack or SIEM.</p> :
            <table className="mt-2 w-full text-sm"><thead><tr className="table-head"><th className="py-1.5">Channel</th><th>Event</th><th>Status</th><th>Tries</th></tr></thead>
              <tbody>{box.items.map((r: any) => <tr key={r.id} className="border-t border-line" title={r.last_error || ''}><td className="py-1.5">{r.channel}</td><td className="font-mono text-xs">{r.kind}</td>
                <td><span className={clsx('chip', r.status === 'sent' ? 'bg-emerald-100 text-emerald-800' : r.status === 'dead' ? 'bg-red-100 text-red-800' : 'bg-amber-100 text-amber-800')}>{r.status}</span></td><td className="tabular-nums">{r.attempts}</td></tr>)}</tbody></table>}
        </div>}
      </div>
    </>
  )
}
