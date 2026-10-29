import { useEffect, useMemo, useState } from 'react'
import { ReactFlow, Background, Controls, MarkerType, Handle, Position } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { Building2, UserRound, Network, AlertTriangle } from 'lucide-react'
import { api } from '../lib/api'
import { PageHeader, Skeleton, Stat, Term } from '../components/ui'
import { Avatar } from '../components/Avatar'

function CollegeNode({ data }: any) {
  return (
    <div className={`w-[210px] rounded-2xl border-2 bg-surface p-3 shadow-card ${data.flag ? 'border-amber-500' : 'border-line'}`}>
      <Handle type="target" position={Position.Top} className="!opacity-0" /><Handle type="source" position={Position.Bottom} className="!opacity-0" />
      <div className="flex items-center gap-2"><Avatar seed={data.label} size={34} /><div className="min-w-0"><div className="truncate text-xs font-bold text-ink">{data.label}</div><div className="text-[10px] text-muted">{data.city} · centrality {data.centrality}</div></div></div>
    </div>
  )
}
function PanNode({ data }: any) {
  return (
    <div className="rounded-full border-2 border-purple-500 bg-purple-50 px-3 py-2 text-xs font-bold text-purple-800 shadow-card dark:bg-purple-500/15 dark:text-purple-200">
      <Handle type="target" position={Position.Top} className="!opacity-0" /><Handle type="source" position={Position.Bottom} className="!opacity-0" />
      <span className="flex items-center gap-1.5"><UserRound className="h-3.5 w-3.5" />{data.label}</span>
    </div>
  )
}
const nodeTypes = { college: CollegeNode, pan: PanNode }

export default function Collusion() {
  const [g, setG] = useState<any>(null); const [sel, setSel] = useState<any>(null)
  useEffect(() => { api('/api/collusion/graph').then(setG) }, [])
  const { nodes, edges } = useMemo(() => {
    if (!g) return { nodes: [], edges: [] }
    const flagged = new Set(g.edges.flatMap((e: any) => [e.source, e.target]))
    const cols = g.nodes.filter((n: any) => n.kind === 'college'), others = g.nodes.filter((n: any) => n.kind !== 'college')
    const pos: Record<string, any> = {}
    cols.forEach((n: any, i: number) => { const ang = (i / cols.length) * 2 * Math.PI - Math.PI / 2; pos[n.id] = { x: 380 + 330 * Math.cos(ang), y: 230 + 190 * Math.sin(ang) } })
    others.forEach((n: any, i: number) => { pos[n.id] = { x: 400 + i * 160, y: 230 } })
    return {
      nodes: g.nodes.map((n: any) => ({ id: n.id, type: n.kind === 'college' ? 'college' : 'pan', position: pos[n.id], data: { ...n, flag: flagged.has(n.id) } })),
      edges: g.edges.map((e: any, i: number) => ({ id: `e${i}`, source: e.source, target: e.target, label: e.label, animated: true, data: e,
        style: { stroke: e.kind === 'photo' ? '#f59e0b' : e.kind === 'pan' ? '#a855f7' : '#ef4444', strokeWidth: 2.5 },
        labelStyle: { fontSize: 11, fontWeight: 600, fill: 'rgb(var(--ink))' }, labelBgStyle: { fill: 'rgb(var(--surface))' }, labelBgPadding: [6, 3] as [number, number], labelBgBorderRadius: 6,
        markerEnd: { type: MarkerType.ArrowClosed, color: e.kind === 'photo' ? '#f59e0b' : '#a855f7' } })),
    }
  }, [g])
  return (
    <>
      <PageHeader eyebrow="Module 4D" title="Cross-college collusion graph" desc={<>Institutions are linked when they share a faculty <Term t="PII">PAN</Term> (matched by blind index, never in plain text), an identical file hash, or a recycled lab photo (<Term t="pHash" /> + <Term t="ORB" />).</>} />
      <div className="mb-5 grid gap-4 sm:grid-cols-3">
        <Stat icon={Building2} label="Institutions" value={g?.summary.colleges ?? '–'} />
        <Stat icon={Network} label="Suspicious links" value={g?.summary.links ?? '–'} tone="amber" />
        <Stat icon={AlertTriangle} label="Linked clusters" value={g?.summary.suspicious_clusters ?? '–'} tone="red" hint="Connected groups of 2+ institutions" />
      </div>
      <div className="grid gap-5 xl:grid-cols-[1fr_320px]">
        <div className="card h-[560px] overflow-hidden">{!g ? <Skeleton className="h-full" /> :
          <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView onEdgeClick={(_, e) => setSel(e.data)} onNodeClick={(_, n) => setSel(n.data)} proOptions={{ hideAttribution: true }}>
            <Background color="rgb(var(--line))" gap={22} /><Controls showInteractive={false} />
          </ReactFlow>}
        </div>
        <div className="space-y-4">
          <div className="card card-pad"><div className="text-sm font-semibold">Legend</div>
            <ul className="mt-2 space-y-1.5 text-sm"><li className="flex items-center gap-2"><span className="h-1 w-6 rounded bg-purple-500" />Shared faculty PAN</li><li className="flex items-center gap-2"><span className="h-1 w-6 rounded bg-amber-500" />Same lab photo</li><li className="flex items-center gap-2"><span className="h-1 w-6 rounded bg-red-500" />Identical document hash</li><li className="flex items-center gap-2"><span className="h-3 w-6 rounded border-2 border-amber-500" />Institution involved in a link</li></ul>
          </div>
          <div className="card card-pad"><div className="text-sm font-semibold">Selection</div>
            {!sel ? <p className="mt-1 text-sm text-muted">Click a node or a link to see why it is flagged.</p> : <div className="mt-2 space-y-1 text-sm animate-fadeUp">
              {sel.source ? <><b>{sel.label}</b><div className="text-muted">Kind: {sel.kind}</div>{sel.docs && <div className="text-muted">Documents #{sel.docs.join(', #')}</div>}</> : <><b>{sel.label}</b><div className="text-muted">{sel.kind}{sel.city && ` · ${sel.city}`}</div><div className="text-muted">Degree centrality {sel.centrality}</div></>}
            </div>}
          </div>
          <div className="card card-pad text-xs text-muted">Links are <b className="text-ink">signals for review</b>, not proof. A faculty member may legitimately move between institutions; the officer decides.</div>
        </div>
      </div>
    </>
  )
}
