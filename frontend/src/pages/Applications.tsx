import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Search, FilePlus2 } from 'lucide-react'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { PageHeader, Skeleton } from '../components/ui'
import { AppTable } from './Dashboard'

export default function Applications() {
  const { user } = useAuth(); const staff = user!.role !== 'college'
  const [apps, setApps] = useState<any[] | null>(null); const [q, setQ] = useState(''); const [st, setSt] = useState('')
  useEffect(() => { api('/api/applications').then(setApps) }, [])
  const list = useMemo(() => (apps || []).filter((a) => (!st || (a.submitted_at ? a.status : 'Draft') === st) && (!q || `${a.ref} ${a.college} ${a.category_label}`.toLowerCase().includes(q.toLowerCase()))), [apps, q, st])
  return (
    <>
      <PageHeader eyebrow={staff ? 'Scrutiny' : 'College workspace'} title={staff ? 'All applications' : 'My applications'} desc={staff ? 'Every submission across institutions. Use the priority queue for triage order.' : 'Draft, submitted and decided applications for your institution.'}
        actions={!staff && <Link to="/applications/new" className="btn-primary"><FilePlus2 className="h-4 w-4" />New application</Link>} />
      <div className="card overflow-hidden">
        <div className="flex flex-wrap gap-3 border-b border-line p-4">
          <div className="relative min-w-[240px] flex-1"><Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" /><input aria-label="Search applications" className="input pl-9" placeholder="Search by reference, institution or category" value={q} onChange={(e) => setQ(e.target.value)} /></div>
          <select aria-label="Filter by status" className="input w-auto" value={st} onChange={(e) => setSt(e.target.value)}>
            <option value="">All statuses</option>{['Draft', 'Verified', 'Mismatch Detected', 'Expired', 'Verification Pending', 'Source Unavailable', 'Manual Review Required'].map((s) => <option key={s}>{s}</option>)}
          </select>
        </div>
        {!apps ? <div className="p-5"><Skeleton className="h-48" /></div> : <AppTable apps={list} staff={staff} />}
      </div>
    </>
  )
}
