import { useEffect, useLayoutEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { ArrowLeft, ArrowRight, Loader2, PlayCircle, X } from 'lucide-react'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'

/** Lightweight in-app guided tour for judges. Runs entirely in the browser; no external service.
 *  State is kept in localStorage so the tour survives page changes and the officer → senior officer switch. */
type Step = { title: string; body: string; route: (ctx: Ctx) => string; target?: string; before?: () => void; action?: { label: string; run: (ctx: Ctx & { login: any }) => Promise<void> } }
type Ctx = { gvce: number }
const KEY = 'sealcheck.tour'

const clickTab = (name: string) => () => {
  const t = Array.from(document.querySelectorAll<HTMLButtonElement>('[role=tab]')).find((b) => b.textContent?.includes(name))
  if (t && t.getAttribute('aria-selected') !== 'true') t.click()
}

export const STEPS: Step[] = [
  { title: '1 · The priority queue', route: () => '/queue', target: '[data-tour=queue]',
    body: 'Every submitted application is ranked by 0.5×risk + 0.3×deadline urgency + 0.2×waiting time, so officers see the riskiest and most urgent files first.' },
  { title: '2 · Open the forged application', route: (c) => `/applications/${c.gvce}`, target: '[data-tour=checklist]',
    body: 'Ganga Valley College (GVCE) has three flagged documents. The checklist shows each required document with its status from the deterministic policy engine.' },
  { title: '3 · Evidence on the page', route: (c) => `/applications/${c.gvce}`, target: '[data-tour=evidence]', before: clickTab('Evidence'),
    body: 'The forged land lease: hidden white text and a masking overlay are boxed in red, right on the rendered page. Click any issue to jump to it.' },
  { title: '4 · The agent debate', route: (c) => `/applications/${c.gvce}`, target: '[data-tour=agents]', before: clickTab('Agents'),
    body: 'An Advocate, a Critic and a Head agent explain the evidence in plain words. They cannot change the status; AI explains and humans decide.' },
  { title: '5 · Request a two-person override', route: (c) => `/applications/${c.gvce}`, target: '[data-tour=override]', before: clickTab('Evidence'),
    body: 'Approval is locked while a forgery flag is open. An officer can request an override with a written justification. Click the button, write at least 20 characters, and submit.' },
  { title: '6 · A different senior officer approves', route: () => '/overrides', target: '[data-tour=overrides]',
    body: 'The requester can never approve their own override. Switch to the Senior Officer persona to approve or reject pending requests.',
    action: { label: 'Switch to Senior Officer', run: async ({ login }) => { await login('senior@sealcheck.demo', 'Demo@2026') } } },
  { title: '7 · Verify the audit chain', route: () => '/audit', target: '[data-tour=verify]',
    body: 'Every login, upload, finding, override and decision is appended to a SHA-256 hash chain. "Verify chain" recomputes every link; any edit breaks it.' },
]

export function startTour() { localStorage.setItem(KEY, '0'); window.dispatchEvent(new Event('sealcheck:tour')) }

export function StartTourButton() {
  return <button className="btn-ghost" onClick={startTour} data-testid="start-tour"><PlayCircle className="h-4 w-4 text-primary" />Start 3-minute demo tour</button>
}

export function Tour() {
  const [step, setStep] = useState<number | null>(() => { const v = localStorage.getItem(KEY); return v == null ? null : +v })
  const [ctx, setCtx] = useState<Ctx | null>(null); const [rect, setRect] = useState<DOMRect | null>(null); const [busy, setBusy] = useState(false)
  const nav = useNavigate(); const loc = useLocation(); const { login } = useAuth()
  useEffect(() => { const h = () => setStep(+(localStorage.getItem(KEY) ?? 0)); window.addEventListener('sealcheck:tour', h); return () => window.removeEventListener('sealcheck:tour', h) }, [])
  useEffect(() => {
    if (step == null || ctx) return
    api<any>('/api/applications').then((r) => { const list = Array.isArray(r) ? r : r.items; setCtx({ gvce: (list.find((a: any) => a.ref.includes('GVCE')) || list[0])?.id }) }).catch(() => setCtx({ gvce: 2 }))
  }, [step, ctx])
  const s = step != null ? STEPS[step] : null
  useEffect(() => { if (s && ctx) { const r = s.route(ctx); if (loc.pathname !== r) nav(r) } }, [step, ctx])
  useLayoutEffect(() => {
    if (!s) return
    let ran = false
    const tick = () => {
      if (s.before && !ran && document.querySelector('[role=tab]')) { s.before(); ran = true }
      const el = s.target ? document.querySelector(s.target) : null
      if (el) { const r = el.getBoundingClientRect(); setRect((p) => (p && Math.abs(p.top - r.top) < 1 && Math.abs(p.height - r.height) < 1 && Math.abs(p.left - r.left) < 1 ? p : r)) } else setRect(null)
    }
    const el0 = () => s.target && document.querySelector(s.target)
    const scroll = setTimeout(() => { const e = el0(); if (e) (e as HTMLElement).scrollIntoView({ block: 'nearest', behavior: 'smooth' }) }, 600)
    tick(); const t = setInterval(tick, 250)
    return () => { clearInterval(t); clearTimeout(scroll) }
  }, [step, loc.pathname])
  if (step == null || !s) return null
  const go = (n: number) => { if (n < 0 || n >= STEPS.length) return close(); localStorage.setItem(KEY, String(n)); setRect(null); setStep(n) }
  const close = () => { localStorage.removeItem(KEY); setStep(null); setRect(null) }
  const pad = 8
  const vw = window.innerWidth, vh = window.innerHeight
  const cardW = Math.min(380, vw - 24)
  let top = vh - 240, left = vw - cardW - 24
  if (rect) {
    const below = rect.bottom + pad + 12, above = rect.top - pad - 12
    if (below + 220 < vh) top = below
    else if (above - 220 > 0) top = above - 220
    else top = Math.max(12, Math.min(vh - 240, rect.top + 12))
    left = Math.max(12, Math.min(vw - cardW - 12, rect.left))
    if (rect.height > vh * 0.45 || (rect.width > vw * 0.55 && rect.height > vh * 0.3)) { top = vh - 250; left = vw - cardW - 24 }
  }
  return (
    <div className="pointer-events-none fixed inset-0 z-[80]" aria-live="polite">
      {rect && <div className="tour-spot absolute rounded-2xl ring-2 ring-primary transition-all duration-300" style={{ top: rect.top - pad, left: rect.left - pad, width: rect.width + pad * 2, height: Math.min(rect.height + pad * 2, vh - rect.top + pad - 8) }} />}
      <div role="dialog" aria-label={`Demo tour: ${s.title}`} className="pointer-events-auto absolute animate-fadeUp rounded-2xl border border-line bg-surface p-4 shadow-pop" style={{ top, left, width: cardW }}>
        <div className="flex items-start gap-2">
          <div className="flex-1"><div className="text-[10.5px] font-bold uppercase tracking-wide text-primary">Demo tour · step {step + 1} of {STEPS.length}</div><div className="mt-0.5 font-display text-base font-bold">{s.title}</div></div>
          <button className="btn-ghost btn-sm" onClick={close} aria-label="End tour"><X className="h-4 w-4" /></button>
        </div>
        <p className="mt-1.5 text-sm leading-relaxed text-muted">{s.body}</p>
        <div className="mt-2 flex gap-1">{STEPS.map((_, i) => <span key={i} className={`h-1 flex-1 rounded-full ${i <= step ? 'bg-primary' : 'bg-line'}`} />)}</div>
        <div className="mt-3 flex items-center gap-2">
          <button className="btn-ghost btn-sm" disabled={step === 0} onClick={() => go(step - 1)}><ArrowLeft className="h-3.5 w-3.5" />Back</button>
          {s.action && <button className="btn-ghost btn-sm" disabled={busy} onClick={async () => { setBusy(true); try { await s.action!.run({ ...ctx!, login }) } finally { setBusy(false) } }}>{busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />}{s.action.label}</button>}
          <button className="btn-primary btn-sm ml-auto" onClick={() => go(step + 1)} data-testid="tour-next">{step === STEPS.length - 1 ? 'Finish' : 'Next'}<ArrowRight className="h-3.5 w-3.5" /></button>
        </div>
      </div>
    </div>
  )
}
