import { CheckCircle2, Loader2, Circle, MinusCircle, XCircle } from 'lucide-react'
import clsx from 'clsx'

export const STAGES = [
  { id: '1 Category & checklist', short: 'Checklist', n: '1' },
  { id: '2 Secure upload + SHA-256', short: 'Secure upload', n: '2' },
  { id: '3 CDR + sandbox', short: 'CDR + sandbox', n: '3' },
  { id: '4A PDF forensics', short: 'PDF forensics', n: '4A' },
  { id: '4B AICTE rules', short: 'Rule engine', n: '4B' },
  { id: '4C Photo inspector', short: 'Photo inspector', n: '4C' },
  { id: '4D Collusion graph', short: 'Collusion graph', n: '4D' },
  { id: '5 Policy engine', short: 'Policy engine', n: '5' },
  { id: '6 Evidence packet', short: 'Evidence packet', n: '6' },
]

export function PipelineProgress({ job, compact }: { job: any; compact?: boolean }) {
  const prog: any[] = job?.progress || []
  const get = (id: string) => prog.find((p) => p.stage === id)
  const failed = job?.status === 'failed'
  return (
    <ol className={clsx('grid gap-2', compact ? 'grid-cols-9' : 'grid-cols-3 sm:grid-cols-5 xl:grid-cols-9')} aria-label="Verification pipeline progress">
      {STAGES.map((s, i) => {
        const p = get(s.id)
        const st = p?.status || (failed ? 'failed' : 'waiting')
        const Icon = st === 'done' ? CheckCircle2 : st === 'running' ? Loader2 : st === 'skipped' ? MinusCircle : st === 'failed' ? XCircle : Circle
        return (
          <li key={s.id} title={`${s.id}: ${st}`} className={clsx('relative rounded-xl border px-2.5 py-2 transition-all duration-300', compact && 'px-1 py-1',
            st === 'done' && 'border-emerald-300/70 bg-emerald-50 dark:border-emerald-500/30 dark:bg-emerald-500/10',
            st === 'running' && 'border-primary bg-primary-soft animate-pulseRing', st === 'skipped' && 'border-line bg-surface-2 opacity-70',
            st === 'failed' && 'border-red-300 bg-red-50', st === 'waiting' && 'border-line bg-surface')}>
            <div className="flex items-center gap-1.5">
              <Icon className={clsx('h-4 w-4 shrink-0', st === 'done' && 'text-emerald-600', st === 'running' && 'animate-spin text-primary', st === 'failed' && 'text-red-600', (st === 'waiting' || st === 'skipped') && 'text-muted')} />
              {!compact && <span className="text-[11px] font-bold text-muted">{s.n}</span>}
            </div>
            {!compact && <div className="mt-1 text-[12px] font-semibold leading-tight">{s.short}</div>}
            {!compact && p?.detail?.status && <div className="mt-0.5 truncate text-[10.5px] text-muted">{p.detail.status}</div>}
            {!compact && p?.detail?.findings !== undefined && <div className="mt-0.5 text-[10.5px] text-muted">{p.detail.findings} finding(s)</div>}
            {i < STAGES.length - 1 && !compact && <span className="absolute -right-2 top-1/2 hidden h-px w-2 bg-line xl:block" />}
          </li>
        )
      })}
    </ol>
  )
}
