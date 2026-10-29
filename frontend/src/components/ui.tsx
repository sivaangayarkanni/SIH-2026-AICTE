import { createPortal } from 'react-dom'
import { ReactNode, useEffect, useState } from 'react'
import { CheckCircle2, AlertTriangle, CalendarX, Clock, CloudOff, Eye, HelpCircle, X, Inbox } from 'lucide-react'
import clsx from 'clsx'

export const STATUS: Record<string, { cls: string; icon: any; plain: string }> = {
  'Verified': { cls: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-500/15 dark:text-emerald-300', icon: CheckCircle2, plain: 'All checks passed.' },
  'Mismatch Detected': { cls: 'bg-amber-100 text-amber-900 dark:bg-amber-500/15 dark:text-amber-300', icon: AlertTriangle, plain: 'Something does not match — possible forgery or reuse.' },
  'Expired': { cls: 'bg-red-100 text-red-800 dark:bg-red-500/15 dark:text-red-300', icon: CalendarX, plain: 'The document or its signing certificate is out of date.' },
  'Verification Pending': { cls: 'bg-blue-100 text-blue-800 dark:bg-blue-500/15 dark:text-blue-300', icon: Clock, plain: 'Still being checked, or documents are missing.' },
  'Source Unavailable': { cls: 'bg-slate-200 text-slate-700 dark:bg-slate-500/20 dark:text-slate-300', icon: CloudOff, plain: 'The issuer could not be confirmed at its source.' },
  'Manual Review Required': { cls: 'bg-purple-100 text-purple-800 dark:bg-purple-500/15 dark:text-purple-300', icon: Eye, plain: 'A human officer needs to look at this.' },
  'Draft': { cls: 'bg-slate-100 text-slate-600 dark:bg-slate-500/15 dark:text-slate-300', icon: Clock, plain: 'Not submitted yet.' },
}

export function StatusChip({ status, size = 'sm' }: { status: string; size?: 'sm' | 'lg' }) {
  const s = STATUS[status] || STATUS['Draft']; const I = s.icon
  return <span title={s.plain} className={clsx('chip', s.cls, size === 'lg' && 'px-3 py-1 text-sm')}><I className={size === 'lg' ? 'h-4 w-4' : 'h-3.5 w-3.5'} />{status}</span>
}

export function DecisionChip({ d }: { d?: string | null }) {
  if (!d) return null
  const c = d === 'Approved' ? 'bg-emerald-600 text-white' : d === 'Rejected' ? 'bg-red-600 text-white' : 'bg-amber-500 text-white'
  return <span className={clsx('chip', c)}>{d}</span>
}

export function RiskBadge({ score }: { score: number }) {
  const [c, l] = score >= 70 ? ['bg-red-500', 'High'] : score >= 35 ? ['bg-amber-500', 'Medium'] : ['bg-emerald-500', 'Low']
  return (
    <span className="inline-flex items-center gap-2 text-xs font-semibold" title="Risk score 0–100 from the policy engine">
      <span className="relative h-1.5 w-14 overflow-hidden rounded-full bg-line"><span className={clsx('absolute inset-y-0 left-0 rounded-full', c)} style={{ width: `${Math.max(4, score)}%` }} /></span>
      <span className="tabular-nums">{score}</span><span className="text-muted font-medium">{l}</span>
    </span>
  )
}

export function Ring({ value, size = 120, stroke = 11, label }: { value: number; size?: number; stroke?: number; label?: string }) {
  const [v, setV] = useState(0)
  useEffect(() => { const t = setTimeout(() => setV(value), 60); return () => clearTimeout(t) }, [value])
  const r = (size - stroke) / 2, c = 2 * Math.PI * r
  const col = value >= 80 ? '#10b981' : value >= 50 ? '#f59e0b' : '#ef4444'
  return (
    <div className="relative inline-flex items-center justify-center" style={{ width: size, height: size }} role="img" aria-label={`${label || 'Score'} ${value} out of 100`}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} stroke="rgb(var(--line))" strokeWidth={stroke} fill="none" />
        <circle cx={size / 2} cy={size / 2} r={r} stroke={col} strokeWidth={stroke} fill="none" strokeLinecap="round"
          strokeDasharray={c} strokeDashoffset={c * (1 - v / 100)} style={{ transition: 'stroke-dashoffset 1s cubic-bezier(.2,.8,.2,1)' }} />
      </svg>
      <div className="absolute text-center"><div className="font-display text-3xl font-bold tabular-nums">{value}</div>{label && <div className="text-[10px] font-semibold uppercase tracking-wider text-muted">{label}</div>}</div>
    </div>
  )
}

export const Skeleton = ({ className }: { className?: string }) => <div className={clsx('skeleton', className)} />

export function Empty({ icon: I = Inbox, title, body, action }: { icon?: any; title: string; body?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-line px-6 py-12 text-center">
      <div className="mb-3 rounded-2xl bg-primary-soft p-3 text-primary"><I className="h-6 w-6" /></div>
      <div className="font-semibold">{title}</div>{body && <p className="mt-1 max-w-sm text-sm text-muted">{body}</p>}{action && <div className="mt-4">{action}</div>}
    </div>
  )
}

export const GLOSSARY: Record<string, string> = {
  DSC: 'Digital Signature Certificate — an electronic signature that proves who issued a PDF and that it was not changed afterwards.',
  CDR: 'Content Disarm & Reconstruction — strips anything executable (scripts, attachments, auto-actions) and rebuilds a clean copy of the file.',
  WORM: 'Write Once, Read Many — the original upload is stored read-only and can never be overwritten.',
  RBAC: 'Role-Based Access Control — what you can do depends on your role (College, Officer, Senior Officer, Admin).',
  ABAC: 'Attribute-Based Access Control — extra rules on attributes, e.g. a college only sees rows with its own college ID.',
  'SHA-256': 'A digital fingerprint of the file. If one byte changes, the fingerprint changes completely.',
  KMS: 'Key Management Service — guards the master key. Each record gets its own data key, which the master key encrypts (envelope encryption).',
  pHash: 'Perceptual hash — a fingerprint of how an image looks, so resized or cropped copies still match.',
  ORB: 'Oriented FAST and Rotated BRIEF — finds distinctive corners in photos and matches them between images.',
  ByteRange: 'The exact byte ranges of a PDF covered by its digital signature. Bytes outside it were added later.',
  PII: 'Personally Identifiable Information — e.g. PAN or Aadhaar numbers. Stored encrypted and shown masked.',
}

export function Term({ t, children }: { t: string; children?: ReactNode }) {
  return (
    <span className="group relative inline-flex cursor-help items-center gap-0.5 border-b border-dotted border-muted/60" tabIndex={0}>
      {children || t}<HelpCircle className="h-3 w-3 text-muted" />
      <span role="tooltip" className="pointer-events-none absolute bottom-full left-1/2 z-50 mb-2 w-64 -translate-x-1/2 rounded-xl bg-slate-900 px-3 py-2 text-xs font-normal normal-case leading-relaxed tracking-normal text-white opacity-0 shadow-pop transition group-hover:opacity-100 group-focus:opacity-100">
        <b>{t}</b>: {GLOSSARY[t]}
      </span>
    </span>
  )
}

export function Modal({ open, onClose, title, children, wide }: { open: boolean; onClose: () => void; title: string; children: ReactNode; wide?: boolean }) {
  useEffect(() => { const k = (e: KeyboardEvent) => e.key === 'Escape' && onClose(); window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k) }, [onClose])
  if (!open) return null
  return createPortal(
    <div className="fixed inset-0 z-[90] flex items-center justify-center bg-slate-950/50 p-4 backdrop-blur-sm" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-label={title} className={clsx('card animate-fadeUp max-h-[90vh] w-full overflow-auto p-6 shadow-pop', wide ? 'max-w-3xl' : 'max-w-lg')} onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between"><h3 className="font-display text-xl font-bold">{title}</h3><button aria-label="Close" onClick={onClose} className="rounded-lg p-1 text-muted hover:bg-surface-2"><X className="h-5 w-5" /></button></div>
        {children}
      </div>
    </div>,
    document.body,
  )
}

export function Tabs({ tabs, value, onChange }: { tabs: { id: string; label: ReactNode }[]; value: string; onChange: (v: string) => void }) {
  return (
    <div role="tablist" className="flex flex-wrap gap-1 rounded-xl bg-surface-2 p-1">
      {tabs.map((t) => (
        <button key={t.id} role="tab" aria-selected={value === t.id} onClick={() => onChange(t.id)}
          className={clsx('whitespace-nowrap rounded-lg px-3.5 py-1.5 text-sm font-semibold transition', value === t.id ? 'bg-surface text-primary shadow-sm' : 'text-muted hover:text-ink')}>{t.label}</button>
      ))}
    </div>
  )
}

export function PageHeader({ eyebrow, title, desc, actions }: { eyebrow?: string; title: string; desc?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4 animate-fadeUp">
      <div>
        {eyebrow && <div className="mb-1 text-xs font-bold uppercase tracking-[.14em] text-primary">{eyebrow}</div>}
        <h1 className="font-display text-[28px] font-bold leading-tight">{title}</h1>
        {desc && <p className="mt-1 max-w-2xl text-sm text-muted">{desc}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  )
}

export function Stat({ icon: I, label, value, hint, tone = 'primary' }: { icon: any; label: string; value: ReactNode; hint?: string; tone?: 'primary' | 'green' | 'amber' | 'red' | 'purple' }) {
  const t = { primary: 'bg-primary-soft text-primary', green: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300', amber: 'bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300', red: 'bg-red-100 text-red-700 dark:bg-red-500/15 dark:text-red-300', purple: 'bg-purple-100 text-purple-700 dark:bg-purple-500/15 dark:text-purple-300' }[tone]
  return (
    <div className="card card-pad animate-fadeUp">
      <div className="flex items-center justify-between"><span className="text-sm font-medium text-muted">{label}</span><span className={clsx('rounded-xl p-2', t)}><I className="h-4 w-4" /></span></div>
      <div className="mt-2 font-display text-3xl font-bold tabular-nums">{value}</div>
      {hint && <div className="mt-1 text-xs text-muted">{hint}</div>}
    </div>
  )
}

export const SEV: Record<string, string> = {
  critical: 'bg-red-600 text-white', high: 'bg-orange-500 text-white', medium: 'bg-amber-400 text-amber-950', low: 'bg-blue-500 text-white', info: 'bg-emerald-500 text-white',
}
