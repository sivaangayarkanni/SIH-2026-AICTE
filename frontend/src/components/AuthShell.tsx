import { ReactNode, useEffect, useState } from 'react'
import clsx from 'clsx'
import { DemoNotice, GovBar, Tricolour, UtilityBar, Masthead, PortalFooter } from './Portal'
import { api } from '../lib/api'

export function AuthShell({ title, children, wide }: { title: string; children: ReactNode; wide?: boolean }) {
  return (
    <div className="flex min-h-full flex-col bg-bg" data-layout="portal">
      <GovBar /><Tricolour /><DemoNotice /><UtilityBar />
      <header className="border-b border-line bg-surface"><Masthead /></header>
      <main id="main-content" tabIndex={-1} className={clsx('mx-auto w-full flex-1 px-4 py-8 md:px-8', wide ? 'max-w-[960px]' : 'max-w-[560px]')}>
        <section className="card overflow-hidden p-0">
          <div className="card-head px-5 py-3 text-[15px] font-bold uppercase tracking-wide">{title}</div>
          <div className="p-6">
            <p role="note" className="mb-4 rounded border-l-4 border-[#b34000] bg-accent-soft px-3 py-2 text-[13px] text-ink">Prototype - not an official AICTE system. Do not reuse an AICTE or government portal password here.</p>
            {children}
          </div>
        </section>
      </main>
      <PortalFooter />
    </div>
  )
}

export function Field({ id, label, err, hint, children }: { id: string; label: string; err?: string; hint?: string; children: ReactNode }) {
  return <div><label className="label" htmlFor={id}>{label}</label>{children}
    {err ? <div id={`${id}-err`} role="alert" className="mt-1 text-xs text-red-600">{err}</div> : hint ? <div className="mt-1 text-xs text-muted">{hint}</div> : null}</div>
}

export function score(pw: string) {
  let s = 0
  if (pw.length >= 10) s++
  if (pw.length >= 14) s++
  const cls = [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((r) => r.test(pw)).length
  if (cls >= 3) s++
  if (cls === 4 || pw.length >= 18) s++
  return Math.min(4, s)
}

export function PasswordMeter({ pw, username = '', email = '' }: { pw: string; username?: string; email?: string }) {
  const [probs, setProbs] = useState<string[] | null>(null)
  useEffect(() => {
    if (!pw) { setProbs(null); return }
    const t = setTimeout(() => api('/api/auth/password/check', { method: 'POST', json: { password: pw, username, email } }).then((r) => setProbs(r.problems)).catch(() => {}), 350)
    return () => clearTimeout(t)
  }, [pw, username, email])
  const s = probs && probs.length ? Math.min(1, score(pw)) : score(pw)
  const lbl = ['Very weak', 'Weak', 'Fair', 'Good', 'Strong'][s]
  return <div data-testid="pw-meter" className="mt-1.5">
    <div className="flex gap-1" aria-hidden>{[0, 1, 2, 3].map((i) => <span key={i} className={clsx('h-1.5 flex-1 rounded-full', i < s ? ['bg-red-500', 'bg-orange-500', 'bg-amber-500', 'bg-emerald-600'][Math.max(0, s - 1)] : 'bg-surface-2')} />)}</div>
    <div className="mt-1 text-xs" aria-live="polite"><b>{pw ? lbl : 'At least 10 characters, mixing 3 of: lower-case, upper-case, digits, symbols.'}</b>{probs && probs.length > 0 && <ul className="list-disc pl-4 text-red-600">{probs.map((p) => <li key={p}>{p}</li>)}</ul>}</div>
  </div>
}
