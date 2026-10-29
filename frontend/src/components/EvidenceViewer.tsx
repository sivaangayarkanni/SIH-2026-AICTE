import { useEffect, useState } from 'react'
import { ChevronLeft, ChevronRight, ZoomIn, ZoomOut, ImageOff } from 'lucide-react'
import clsx from 'clsx'
import { authedUrl } from '../lib/api'
import { SEV } from './ui'

export type Finding = { rule_id: string; clause: string; outcome: string; severity: string; title: string; detail: string; page?: number; bbox?: number[]; module?: string }

export function EvidenceViewer({ doc, active, onSelect, extra }: { doc: any; active: number | null; onSelect: (i: number) => void; extra?: { page: number; bbox: number[]; text?: string } | null }) {
  const pages: any[] = doc.pages || []
  const findings: Finding[] = doc.findings || []
  const [page, setPage] = useState(1)
  const [zoom, setZoom] = useState(1)
  const [err, setErr] = useState(false)
  useEffect(() => { if (active != null && findings[active]?.page) setPage(findings[active].page!) }, [active])
  useEffect(() => { if (extra?.page) setPage(extra.page) }, [extra])
  const isPdf = doc.mime === 'application/pdf'
  const pinfo = pages.find((p) => p.page === page) || pages[0]
  const boxes = findings.map((f, i) => ({ f, i })).filter(({ f }) => f.page === page && f.bbox && f.outcome !== 'pass' || (f.page === page && active != null && findings[active] === f && f.bbox))
  const toPct = (b: number[]) => pinfo ? { left: `${(b[0] / pinfo.width) * 100}%`, top: `${((pinfo.height - b[3]) / pinfo.height) * 100}%`, width: `${((b[2] - b[0]) / pinfo.width) * 100}%`, height: `${((b[3] - b[1]) / pinfo.height) * 100}%` } : {}
  if (!doc.job || doc.job.status !== 'done') return <div className="skeleton h-[480px]" />
  return (
    <div className="overflow-hidden rounded-2xl border border-line bg-surface-2">
      <div className="flex items-center justify-between border-b border-line bg-surface px-3 py-2 text-sm">
        <div className="flex items-center gap-1">
          {isPdf && <><button className="btn-ghost btn-sm" disabled={page <= 1} onClick={() => setPage(page - 1)} aria-label="Previous page"><ChevronLeft className="h-4 w-4" /></button>
            <span className="px-2 tabular-nums text-muted">Page {page} / {pages.length || 1}</span>
            <button className="btn-ghost btn-sm" disabled={page >= pages.length} onClick={() => setPage(page + 1)} aria-label="Next page"><ChevronRight className="h-4 w-4" /></button></>}
          {!isPdf && <span className="px-2 text-muted">Sanitised photo (re-encoded by CDR)</span>}
        </div>
        <div className="flex items-center gap-1">
          <button className="btn-ghost btn-sm" onClick={() => setZoom(Math.max(0.6, zoom - 0.2))} aria-label="Zoom out"><ZoomOut className="h-4 w-4" /></button>
          <span className="w-12 text-center tabular-nums text-xs text-muted">{Math.round(zoom * 100)}%</span>
          <button className="btn-ghost btn-sm" onClick={() => setZoom(Math.min(2.2, zoom + 0.2))} aria-label="Zoom in"><ZoomIn className="h-4 w-4" /></button>
        </div>
      </div>
      <div className="max-h-[calc(100vh-190px)] min-h-[360px] overflow-auto p-3 scroll-thin">
        <div className="relative mx-auto shadow-card" style={{ width: `${zoom * 100}%`, maxWidth: zoom * 760 }}>
          {err ? <div className="flex h-80 flex-col items-center justify-center gap-2 bg-surface text-muted"><ImageOff className="h-8 w-8" />Preview not available</div> :
            <img src={authedUrl(`/api/documents/${doc.id}/page/${page}`)} alt={`Page ${page} of ${doc.filename}`} className="block w-full bg-white" onError={() => setErr(true)} />}
          {isPdf && boxes.map(({ f, i }) => (
            <button key={i} onClick={() => onSelect(i)} style={toPct(f.bbox!)} aria-label={`Finding: ${f.title}`}
              className={clsx('hl-box absolute rounded-[3px] border-2', active === i ? 'active border-red-600 bg-red-500/25' : f.severity === 'critical' ? 'border-red-500 bg-red-400/15' : 'border-amber-500 bg-amber-300/20')}>
              <span className={clsx('absolute -left-3 -top-3 flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-bold shadow', SEV[f.severity])}>{i + 1}</span>
            </button>
          ))}
          {isPdf && extra && extra.page === page && <div className="hl-box active absolute rounded-[3px] border-2 border-primary bg-primary/20" style={toPct(extra.bbox)} title={extra.text} />}
        </div>
      </div>
    </div>
  )
}
