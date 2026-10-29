import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowRight, CheckCircle2, FileText, Loader2 } from 'lucide-react'
import clsx from 'clsx'
import { api } from '../lib/api'
import { PageHeader, Skeleton } from '../components/ui'
import { useToast } from '../components/Toast'

export default function NewApplication() {
  const [meta, setMeta] = useState<any>(null); const [cat, setCat] = useState(''); const [title, setTitle] = useState(''); const [busy, setBusy] = useState(false)
  const nav = useNavigate(); const toast = useToast()
  useEffect(() => { api('/api/meta').then(setMeta) }, [])
  const sel = meta?.categories.find((c: any) => c.id === cat)
  const create = async () => {
    setBusy(true)
    try { const a = await api('/api/applications', { method: 'POST', json: { category: cat, title: title || undefined } }); toast('success', 'Application created', `${a.ref} — now upload the checklist documents.`); nav(`/applications/${a.id}`) }
    catch (e: any) { toast('error', 'Could not create application', e.message) } finally { setBusy(false) }
  }
  return (
    <>
      <PageHeader eyebrow="Step 1 of 3 · Choose category" title="Start a new approval application" desc="Pick what you are applying for. SealCheck builds the exact document checklist from the signed AICTE rule bundle." />
      {!meta ? <Skeleton className="h-96" /> : (
        <div className="grid gap-5 lg:grid-cols-[1fr_380px]">
          <div className="grid gap-2.5 sm:grid-cols-2 xl:grid-cols-3">
            {meta.categories.map((c: any) => (
              <button key={c.id} onClick={() => setCat(c.id)} aria-pressed={cat === c.id}
                className={clsx('card relative p-4 text-left transition hover:border-primary', cat === c.id && 'border-primary ring-4 ring-primary/15')}>
                {cat === c.id && <CheckCircle2 className="absolute right-3 top-3 h-5 w-5 text-primary" />}
                <div className="pr-6 text-sm font-semibold">{c.label}</div><div className="mt-1 text-xs text-muted">{c.docs.length} required documents</div>
              </button>
            ))}
          </div>
          <div className="card card-pad h-fit lg:sticky lg:top-24">
            <div className="text-sm font-semibold">Checklist preview</div>
            {!sel ? <p className="mt-2 text-sm text-muted">Select a category to see the documents you will need.</p> : (
              <>
                <ul className="mt-3 space-y-1.5">{sel.docs.map((d: string) => <li key={d} className="flex items-start gap-2 text-sm"><FileText className="mt-0.5 h-4 w-4 shrink-0 text-primary" /><span>{meta.doc_types[d].label}<span className="block text-[11px] text-muted">{meta.doc_types[d].clause}</span></span></li>)}</ul>
                <label className="label mt-4" htmlFor="t">Title (optional)</label>
                <input id="t" className="input" value={title} onChange={(e) => setTitle(e.target.value)} placeholder={sel.label} />
                <button className="btn-primary mt-4 w-full" disabled={busy} onClick={create}>{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}Create and continue<ArrowRight className="h-4 w-4" /></button>
              </>
            )}
          </div>
        </div>
      )}
    </>
  )
}
