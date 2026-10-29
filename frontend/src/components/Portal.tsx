import { useAuth } from '../lib/auth'
import { ReactNode, useState } from 'react'
import { Link, NavLink, useLocation } from 'react-router-dom'
import { ChevronDown, ChevronRight, Contrast, Home, Moon, Sun } from 'lucide-react'
import clsx from 'clsx'
import { useTheme } from '../lib/theme'

/* Original generic shield mark. It is NOT the AICTE logo or the Government of India emblem. */
export function ShieldMark({ size = 44 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden>
      <path d="M32 3l24 9v18c0 16-10.5 27.5-24 32C18.5 57.5 8 46 8 30V12z" fill="#032761" />
      <path d="M32 9l18 6.8V30c0 12.4-7.8 21.6-18 25.6C21.8 51.6 14 42.4 14 30V15.8z" fill="none" stroke="#ffb703" strokeWidth="2.5" />
      <path d="M22 32l7 7 13-14" fill="none" stroke="#fff" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

export const PROTOTYPE_LABEL = 'Prototype - not an official AICTE system'

export function GovBar() {
  return (
    <div className="text-[12.5px] text-white" style={{ background: 'var(--gov-bar)' }}>
      <div className="mx-auto flex max-w-[1360px] flex-wrap items-center gap-x-3 gap-y-0.5 px-4 py-1.5 md:px-8">
        <span className="font-semibold">Government of India <span aria-hidden className="mx-1 text-white/50">|</span> All India Council for Technical Education</span>
        <span lang="hi" className="hindi text-white/85">अखिल भारतीय तकनीकी शिक्षा परिषद</span>
        <span className="ml-auto rounded-sm px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide text-[#111]" style={{ background: 'var(--amber)' }} data-testid="prototype-label">{PROTOTYPE_LABEL}</span>
      </div>
    </div>
  )
}

export function Tricolour() { return <div className="tricolour" aria-hidden /> }

export function UtilityBar() {
  const { scale, setScale, lang, setLang, contrast, setContrast, dark, setDark } = useTheme()
  const b = 'rounded-sm px-1.5 py-0.5 font-semibold hover:bg-surface-2 aria-pressed:bg-primary aria-pressed:text-primary-fg'
  return (
    <div className="border-b border-line bg-surface text-[12px] text-ink">
      <div className="mx-auto flex max-w-[1360px] flex-wrap items-center gap-x-4 gap-y-1 px-4 py-1 md:px-8">
        <a href="#main-content" className="font-semibold text-[color:var(--link)] underline-offset-2 hover:underline">Skip to main content</a>
        <span className="flex-1" />
        <span className="flex items-center gap-1" role="group" aria-label="Text size">
          <span className="mr-1 text-muted">Text size</span>
          <button className={b} onClick={() => setScale(scale - 1)} aria-label="Decrease text size" data-testid="font-dec">A-</button>
          <button className={b} onClick={() => setScale(1)} aria-label="Default text size" aria-pressed={scale === 1} data-testid="font-reset">A</button>
          <button className={b} onClick={() => setScale(scale + 1)} aria-label="Increase text size" data-testid="font-inc">A+</button>
        </span>
        <span className="flex items-center gap-1" role="group" aria-label="Menu language">
          <button className={b} aria-pressed={lang === 'en'} onClick={() => setLang('en')} data-testid="lang-en">English</button>
          <button className={clsx(b, 'hindi')} lang="hi" aria-pressed={lang === 'hi'} onClick={() => setLang('hi')} data-testid="lang-hi">हिन्दी</button>
        </span>
        <button className={clsx(b, 'flex items-center gap-1')} aria-pressed={contrast} onClick={() => setContrast(!contrast)} data-testid="high-contrast"><Contrast className="h-3.5 w-3.5" />High contrast</button>
        <button className={clsx(b, 'flex items-center gap-1')} aria-pressed={dark} onClick={() => setDark(!dark)} aria-label="Toggle dark mode">{dark ? <Sun className="h-3.5 w-3.5" /> : <Moon className="h-3.5 w-3.5" />}{dark ? 'Light' : 'Dark'}</button>
      </div>
    </div>
  )
}

export function Masthead({ right }: { right?: ReactNode }) {
  return (
    <div className="bg-surface">
      <div className="mx-auto flex max-w-[1360px] items-center gap-2 px-3 py-3 sm:gap-3 md:px-8">
        <Link to="/" className="flex min-w-0 items-center gap-2 sm:gap-3" aria-label="SealCheck home">
          <ShieldMark />
          <span className="leading-tight">
            <span className="block text-[20px] font-bold text-primary">SealCheck</span>
            <span className="hidden text-[12px] font-semibold text-muted sm:block">Approval workflow automation, compliance monitoring and alert management · SIH26262 prototype</span>
          </span>
        </Link>
        <span className="ml-2 hidden rounded border border-[#b34000] px-2 py-0.5 text-[11px] font-bold uppercase text-[#b34000] dark:border-amber-300 dark:text-amber-300 md:inline">Prototype</span>
        <span className="flex-1" />
        {right}
      </div>
    </div>
  )
}

export const HI: Record<string, string> = {
  Dashboard: 'डैशबोर्ड', 'How it works': 'यह कैसे काम करता है', 'My applications': 'मेरे आवेदन', 'New application': 'नया आवेदन',
  'Readiness assistant': 'तैयारी सहायक', 'Priority queue': 'प्राथमिकता कतार', 'All applications': 'सभी आवेदन', 'Security overrides': 'सुरक्षा ओवरराइड',
  'Collusion graph': 'मिलीभगत ग्राफ़', 'Security center': 'सुरक्षा केंद्र', 'Audit log': 'ऑडिट लॉग', 'Rule bundles': 'नियम संग्रह',
  'System health': 'सिस्टम स्थिति', 'Notification centre': 'सूचना केंद्र', 'Settings & themes': 'सेटिंग्स और थीम',
  Overview: 'अवलोकन', 'College workspace': 'संस्थान कार्यक्षेत्र', Scrutiny: 'जाँच', 'Trust & governance': 'विश्वास एवं शासन', Home: 'मुख्य पृष्ठ',
}
export function useLabel() { const { lang } = useTheme(); return (s: string) => (lang === 'hi' && HI[s]) || s }

type Item = { to: string; label: string; icon: any; roles: string[] }
export function PortalNav({ groups, role }: { groups: { group: string; items: Item[] }[]; role: string }) {
  const t = useLabel(); const { lang } = useTheme(); const [open, setOpen] = useState<string | null>(null)
  return (
    <nav aria-label="Main" className="bg-primary text-white dark:bg-side" lang={lang}>
      <ul className="mx-auto flex max-w-[1360px] flex-wrap items-stretch px-2 md:px-6" onMouseLeave={() => setOpen(null)}>
        {groups.map((g) => {
          const items = g.items.filter((i) => i.roles.includes(role)); if (!items.length) return null
          if (g.group === 'Overview') return items.map((i) => (
            <li key={i.to}><NavLink to={i.to} end className={({ isActive }) => clsx('flex h-11 items-center px-4 text-[14px] font-semibold hover:bg-white/10', isActive && 'bg-[color:var(--nav-active)] shadow-[inset_0_-3px_0_#ffb703]')}>{t(i.label)}</NavLink></li>
          ))
          const isOpen = open === g.group
          return (
            <li key={g.group} className="relative" onMouseEnter={() => setOpen(g.group)} onFocus={() => setOpen(g.group)} onBlur={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node)) setOpen(null) }}>
              <button className="flex h-11 items-center gap-1 px-4 text-[14px] font-semibold hover:bg-white/10" aria-expanded={isOpen} onClick={() => setOpen(isOpen ? null : g.group)}>{t(g.group)}<ChevronDown className="h-4 w-4" /></button>
              <ul className={clsx('absolute left-0 top-full z-50 min-w-[240px] overflow-hidden rounded-b-md border border-line bg-surface py-1 text-ink shadow-pop', isOpen ? 'block' : 'hidden')}>
                {items.map((i) => (
                  <li key={i.to + i.label}><NavLink to={i.to} end={i.to === '/applications'} onClick={() => setOpen(null)} className={({ isActive }) => clsx('flex items-center gap-2.5 px-4 py-2 text-[14px] hover:bg-primary-soft', isActive && 'border-l-4 border-[#ffb703] bg-primary-soft font-semibold text-primary dark:text-ink')}><i.icon className="h-4 w-4" />{t(i.label)}</NavLink></li>
                ))}
              </ul>
            </li>
          )
        })}
      </ul>
    </nav>
  )
}

export function Breadcrumbs({ groups }: { groups: { group: string; items: Item[] }[] }) {
  const loc = useLocation(); const t = useLabel()
  const all = groups.flatMap((g) => g.items.map((i) => ({ ...i, group: g.group })))
  const p = loc.pathname
  const hit = all.find((i) => i.to === p) || (p.startsWith('/applications/') ? { to: p, label: `Application ${p.split('/').pop()}`, group: 'Scrutiny' } : null)
  return (
    <div className="border-b border-line bg-surface-2">
      <ol className="mx-auto flex max-w-[1360px] flex-wrap items-center gap-1.5 px-4 py-2 text-[12.5px] md:px-8" aria-label="Breadcrumb">
        <li><Link to="/" className="flex items-center gap-1 font-semibold text-[color:var(--link)] hover:underline"><Home className="h-3.5 w-3.5" />{t('Home')}</Link></li>
        {p !== '/' && hit && <>
          {p.startsWith('/applications/') && p !== '/applications/new' && <><ChevronRight className="h-3.5 w-3.5 text-muted" aria-hidden /><li><Link to="/applications" className="font-semibold text-[color:var(--link)] hover:underline">{t('All applications')}</Link></li></>}
          <ChevronRight className="h-3.5 w-3.5 text-muted" aria-hidden /><li aria-current="page" className="font-semibold text-ink">{t(hit.label)}</li>
        </>}
      </ol>
    </div>
  )
}

export function PortalFooter() {
  return (
    <footer className="mt-10 bg-primary text-[13px] text-white dark:bg-side">
      <Tricolour />
      <div className="mx-auto grid max-w-[1360px] gap-6 px-4 py-7 md:grid-cols-3 md:px-8">
        <div className="flex items-start gap-3"><ShieldMark size={38} /><div><div className="font-bold">SealCheck</div><p className="mt-1 text-white/85">Approval workflow, compliance monitoring and alerts · SIH26262</p></div></div>
        <div><div className="font-bold">Accessibility</div><p className="mt-1 text-white/85">Text resize, high-contrast mode, keyboard navigation and a skip link are in the utility bar.</p></div>
        <div><div className="font-bold">Data</div><p className="mt-1 text-white/85"><FooterData /></p></div>
      </div>
      <div className="border-t border-white/15">
        <div className="mx-auto flex max-w-[1360px] flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3 text-[12px] md:px-8">
          <span className="font-semibold" data-testid="footer-disclaimer">Prototype built for Smart India Hackathon 2026 - not an official AICTE system.</span>
          <span className="text-white/80">Not affiliated with or endorsed by AICTE or the Government of India.</span>
        </div>
      </div>
    </footer>
  )
}

/** Shown when the server runs as a hosted public demo (e.g. Vercel): explains what is switched off. */
export function DemoNotice() {
  const { cfg } = useAuth()
  if (!cfg?.demo_notice) return null
  return (
    <div role="note" data-testid="demo-notice" className="bg-[#fff4d6] text-[#3d2c00] border-b border-[#e0c56e] text-xs sm:text-sm px-4 py-1.5 text-center">
      <strong>Demo mode:</strong> {cfg.demo_notice}
    </div>
  )
}

function FooterData() {
  const { cfg } = useAuth()
  return <>{cfg?.demo_accounts ? 'All colleges, people and documents shown are synthetic demo data.' : 'Data is entered by signed-in institutions and officers and stored in this deployment\'s database.'}</>
}
