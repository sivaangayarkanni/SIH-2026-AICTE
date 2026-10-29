import { createContext, useCallback, useContext, useState, ReactNode } from 'react'
import { CheckCircle2, AlertTriangle, Info, X } from 'lucide-react'

type T = { id: number; kind: 'success' | 'error' | 'info'; title: string; body?: string }
const Ctx = createContext<(kind: T['kind'], title: string, body?: string) => void>(() => {})

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, set] = useState<T[]>([])
  const push = useCallback((kind: T['kind'], title: string, body?: string) => {
    const id = Date.now() + Math.random()
    set((x) => [...x, { id, kind, title, body }])
    setTimeout(() => set((x) => x.filter((t) => t.id !== id)), 5200)
  }, [])
  const icon = { success: <CheckCircle2 className="h-5 w-5 text-emerald-500" />, error: <AlertTriangle className="h-5 w-5 text-red-500" />, info: <Info className="h-5 w-5 text-primary" /> }
  return (
    <Ctx.Provider value={push}>
      {children}
      <div className="fixed bottom-5 right-5 z-[100] flex w-[360px] flex-col gap-2" role="status" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className="card animate-fadeUp flex items-start gap-3 p-3.5 shadow-pop">
            {icon[t.kind]}
            <div className="min-w-0 flex-1"><div className="text-sm font-semibold">{t.title}</div>{t.body && <div className="mt-0.5 text-xs text-muted">{t.body}</div>}</div>
            <button aria-label="Dismiss" onClick={() => set((x) => x.filter((y) => y.id !== t.id))} className="text-muted hover:text-ink"><X className="h-4 w-4" /></button>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  )
}
export const useToast = () => useContext(Ctx)
