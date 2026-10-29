import { createContext, useContext, useEffect, useState, ReactNode } from 'react'

export const THEMES = [
  { id: 'portal', name: 'AICTE Portal', desc: 'Government-portal look: navy, amber and tricolour, Open Sans (palette sampled from aicte.gov.in)', swatch: ['#032761', '#ffb703', '#0079c0'] },
  { id: 'aicte', name: 'AICTE Blue', desc: 'Calm institutional blue with saffron highlights', swatch: ['#0b4ea2', '#f58220', '#092248'] },
  { id: 'emerald', name: 'Emerald Trust', desc: 'Fresh green that signals safety and approval', swatch: ['#047857', '#ca8a04', '#052e25'] },
  { id: 'indigo', name: 'Royal Indigo', desc: 'Rich indigo with a magenta accent', swatch: ['#4f46e5', '#db2777', '#1e1b4b'] },
  { id: 'saffron', name: 'Sunset Saffron', desc: 'Tricolour-inspired: saffron, India green and chakra navy', swatch: ['#dd600a', '#138808', '#0a1460'] },
] as const
export type ThemeId = (typeof THEMES)[number]['id']
export type Lang = 'en' | 'hi'

type Ctx = {
  theme: ThemeId; setTheme: (t: ThemeId) => void; dark: boolean; setDark: (d: boolean) => void
  scale: number; setScale: (n: number) => void; lang: Lang; setLang: (l: Lang) => void; contrast: boolean; setContrast: (c: boolean) => void
}
const Ctx = createContext<Ctx>(null!)
const SCALES = [87.5, 100, 112.5, 125]

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<ThemeId>(() => {
    const t = localStorage.getItem('sealcheck.theme') as ThemeId
    return THEMES.some((x) => x.id === t) ? t : 'portal'
  })
  const [dark, setDark] = useState(() => localStorage.getItem('sealcheck.mode') === 'dark')
  const [scale, setScaleRaw] = useState(() => { const n = +(localStorage.getItem('sealcheck.scale') ?? 1); return Number.isFinite(n) ? n : 1 })
  const [lang, setLang] = useState<Lang>(() => (localStorage.getItem('sealcheck.lang') === 'hi' ? 'hi' : 'en'))
  const [contrast, setContrast] = useState(() => localStorage.getItem('sealcheck.contrast') === '1')
  const setScale = (n: number) => setScaleRaw(Math.max(0, Math.min(SCALES.length - 1, n)))
  useEffect(() => {
    const el = document.documentElement
    el.dataset.theme = theme
    el.classList.toggle('dark', dark)
    el.classList.toggle('hc', contrast)
    el.style.fontSize = `${SCALES[scale] ?? 100}%`
    el.dataset.scale = String(scale)
    localStorage.setItem('sealcheck.theme', theme)
    localStorage.setItem('sealcheck.mode', dark ? 'dark' : 'light')
    localStorage.setItem('sealcheck.scale', String(scale))
    localStorage.setItem('sealcheck.lang', lang)
    localStorage.setItem('sealcheck.contrast', contrast ? '1' : '0')
  }, [theme, dark, scale, lang, contrast])
  return <Ctx.Provider value={{ theme, setTheme, dark, setDark, scale, setScale, lang, setLang, contrast, setContrast }}>{children}</Ctx.Provider>
}
export const useTheme = () => useContext(Ctx)
