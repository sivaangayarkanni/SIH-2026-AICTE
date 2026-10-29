import { useEffect, useState } from 'react'
import { FileDown, FileSpreadsheet } from 'lucide-react'
import clsx from 'clsx'
import { api, download, fmtDate } from '../lib/api'
import { PageHeader, Skeleton } from '../components/ui'
import { Safeguard } from '../components/Safeguard'

export default function Reports() {
  const [idx, setIdx] = useState<Record<string, string> | null>(null); const [kind, setKind] = useState('pendency'); const [r, setR] = useState<any>(null)
  useEffect(() => { api('/api/wf/reports').then((x) => setIdx(x.reports)) }, [])
  useEffect(() => { setR(null); api(`/api/wf/reports/${kind}`).then(setR) }, [kind])
  if (!idx) return <Skeleton className="h-96" />
  return (
    <>
      <PageHeader eyebrow="Reports" title="Workflow reports" desc="Generated from live data at the time you open them. Export as CSV or PDF."
        actions={<><button className="btn-ghost" data-testid="rep-csv" onClick={() => download(`/api/wf/reports/${kind}?format=csv`, `${kind}.csv`)}><FileSpreadsheet className="h-4 w-4" />CSV</button>
          <button className="btn-primary" data-testid="rep-pdf" onClick={() => download(`/api/wf/reports/${kind}?format=pdf`, `${kind}.pdf`)}><FileDown className="h-4 w-4" />PDF</button></>} />
      <Safeguard compact />
      <div className="mt-3 grid gap-4 lg:grid-cols-[240px_1fr]">
        <ul className="card p-2" data-testid="rep-list">{Object.entries(idx).map(([k, l]) => <li key={k}><button onClick={() => setKind(k)} className={clsx('w-full rounded-lg px-3 py-2 text-left text-sm', k === kind ? 'bg-primary-soft font-semibold text-primary' : 'hover:bg-surface-2')}>{l}</button></li>)}</ul>
        <div className="card overflow-auto p-0" data-testid="rep-table">{!r ? <Skeleton className="h-64" /> : <>
          <div className="border-b border-line px-5 py-3"><b>{r.title}</b> <span className="text-xs text-muted">· {r.rows.length} rows · as of {fmtDate(r.as_of)}</span></div>
          <table className="w-full text-sm"><thead className="table-head"><tr>{r.header.map((h: string) => <th key={h} className="whitespace-nowrap px-3 py-2 text-left">{h}</th>)}</tr></thead>
            <tbody>{r.rows.map((row: any[], i: number) => <tr key={i} className="border-b border-line/60 last:border-0">{row.map((c, j) => <td key={j} className="whitespace-nowrap px-3 py-1.5">{String(c ?? '')}</td>)}</tr>)}</tbody></table>
          {!r.rows.length && <div className="p-4 text-sm text-muted">No rows.</div>}</>}</div>
      </div>
    </>
  )
}
