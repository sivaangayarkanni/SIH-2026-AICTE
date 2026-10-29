import { useEffect, useState } from 'react'
import { Download, RefreshCw, FileSearch, Fingerprint, BookOpenCheck, Camera, Network, Bot, MessageCircle, History, CheckCircle2, XCircle, AlertTriangle, Info, ShieldCheck, ChevronDown } from 'lucide-react'
import clsx from 'clsx'
import { api, download, fmtDate, fmtSize } from '../lib/api'
import { EvidenceViewer } from './EvidenceViewer'
import { PipelineProgress } from './Pipeline'
import { DocAssistant } from './Voice'
import { StatusChip, Tabs, Term, SEV, Skeleton, Empty } from './ui'
import { Avatar } from './Avatar'
import { useToast } from './Toast'

const OUT: Record<string, any> = { pass: [CheckCircle2, 'text-emerald-600'], fail: [XCircle, 'text-red-600'], warn: [AlertTriangle, 'text-amber-600'], info: [Info, 'text-blue-600'] }

export function FindingRow({ f, i, active, onClick }: { f: any; i: number; active?: boolean; onClick?: () => void }) {
  const [I, c] = OUT[f.outcome] || OUT.info
  return (
    <button onClick={onClick} className={clsx('flex w-full gap-3 rounded-xl border p-3 text-left transition', active ? 'border-primary bg-primary-soft/60' : 'border-line hover:bg-surface-2')}>
      <I className={clsx('mt-0.5 h-4 w-4 shrink-0', c)} />
      <span className="min-w-0 flex-1">
        <span className="flex flex-wrap items-center gap-1.5"><span className="text-sm font-semibold">{f.title}</span></span>
        <span className="mt-0.5 block text-xs leading-relaxed text-muted">{f.detail}</span>
        <span className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[10.5px]">
          <span className="kbd">{f.rule_id}</span><span className="text-muted">{f.clause}</span>
          {f.page && <span className="text-muted">· page {f.page}</span>}
          {f.outcome !== 'pass' && <span className={clsx('chip px-1.5 py-0 text-[10px] uppercase', SEV[f.severity])}>{f.severity}</span>}
        </span>
      </span>
      {f.bbox && f.outcome !== 'pass' && <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-surface-2 text-[10px] font-bold">{i + 1}</span>}
    </button>
  )
}

export function DocPanel({ docId, staff, onChanged }: { docId: number; staff: boolean; onChanged: () => void }) {
  const [d, setD] = useState<any>(null); const [tab, setTab] = useState('evidence'); const [active, setActive] = useState<number | null>(null); const [cite, setCite] = useState<any>(null); const [showPipe, setShowPipe] = useState(false)
  const toast = useToast()
  const load = () => api(`/api/documents/${docId}`).then(setD)
  useEffect(() => { setD(null); setActive(null); setCite(null); load() }, [docId])
  useEffect(() => {
    if (!d || d.job?.status === 'done' || d.job?.status === 'failed') return
    const t = setTimeout(() => load().then(() => onChanged()), 700); return () => clearTimeout(t)
  }, [d])
  if (!d) return <Skeleton className="h-[600px]" />
  const done = d.job?.status === 'done'
  const by = (m: string) => (d.findings || []).filter((f: any) => f.module === m)
  const m = d.modules || {}
  const tabs = [
    { id: 'evidence', label: <span className="flex items-center gap-1.5"><FileSearch className="h-4 w-4" />Evidence</span> },
    { id: '4A', label: <span className="flex items-center gap-1.5"><Fingerprint className="h-4 w-4" />4A Forensics</span> },
    { id: '4B', label: <span className="flex items-center gap-1.5"><BookOpenCheck className="h-4 w-4" />4B Rules</span> },
    { id: '4C', label: <span className="flex items-center gap-1.5"><Camera className="h-4 w-4" />4C Photo</span> },
    { id: '4D', label: <span className="flex items-center gap-1.5"><Network className="h-4 w-4" />4D Collusion</span> },
    { id: 'agents', label: <span className="flex items-center gap-1.5"><Bot className="h-4 w-4" />Agents</span> },
    ...(staff ? [{ id: 'ask', label: <span className="flex items-center gap-1.5"><MessageCircle className="h-4 w-4" />Ask</span> }] : []),
    { id: 'custody', label: <span className="flex items-center gap-1.5"><History className="h-4 w-4" />Custody</span> },
  ]
  const fl = d.findings || []
  return (
    <div className="card animate-fadeUp">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line p-5">
        <div className="min-w-0">
          <div className="text-xs font-semibold uppercase tracking-wide text-muted">{d.label}</div>
          <div className="mt-0.5 truncate font-display text-xl font-bold">{d.filename}</div>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted"><span>{fmtSize(d.size)}</span>·<span className="font-mono" title={d.sha256}><Term t="SHA-256" /> {d.sha256.slice(0, 16)}…</span>{d.job?.duration_ms && <>·<span>analysed in {(d.job.duration_ms / 1000).toFixed(2)} s</span></>}</div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <StatusChip status={d.status} size="lg" />
          {done && <button className="btn-ghost btn-sm" onClick={() => download(`/api/documents/${d.id}/evidence-packet.pdf`, `evidence_packet_doc${d.id}.pdf`).then(() => toast('success', 'Evidence packet downloaded', 'Includes findings, hashes, highlighted pages and the audit trail.'))}><Download className="h-3.5 w-3.5" />Evidence packet</button>}
          {staff && done && <button className="btn-ghost btn-sm" onClick={() => api(`/api/documents/${d.id}/reanalyze`, { method: 'POST' }).then(() => { toast('info', 'Re-analysis started', 'A new sandbox job with a fresh 60-second token was issued.'); load() }).catch((e) => toast('error', 'Could not re-analyse', e.message))}><RefreshCw className="h-3.5 w-3.5" />Re-analyse</button>}
        </div>
      </div>
      {(!done || showPipe) && <div className="border-b border-line p-4" data-tour="pipeline"><PipelineProgress job={d.job} />{d.job?.status === 'failed' && <div className="mt-3 rounded-xl bg-red-50 p-3 text-sm text-red-700">Analysis failed: {d.job.error}</div>}</div>}
      {done && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-line bg-surface-2/60 px-5 py-2.5 text-sm">
          <button className="flex items-center gap-1.5 rounded-lg px-1.5 py-0.5 text-xs font-semibold text-emerald-700 hover:bg-surface dark:text-emerald-300" onClick={() => setShowPipe(!showPipe)} aria-expanded={showPipe} title="Show the 9 pipeline stages">
            <ShieldCheck className="h-4 w-4" />{(d.job?.progress || []).filter((p: any) => p.status === 'done').length} stages done{(d.job?.progress || []).some((p: any) => p.status === 'skipped') && ` · ${(d.job?.progress || []).filter((p: any) => p.status === 'skipped').length} n/a`}<ChevronDown className={clsx('h-3.5 w-3.5 transition', showPipe && 'rotate-180')} />
          </button>
          {d.decision && <><span className="hidden h-4 w-px bg-line sm:block" /><span className="min-w-[14rem] flex-1 basis-[14rem] text-xs"><b>Policy {d.decision.policy_rule}</b>: {d.decision.policy_text}</span>
          <span className="text-xs text-muted">Risk <b className="text-ink">{d.decision.risk_score}</b>/100 · {d.decision.basis.length ? d.decision.basis.join(', ') : 'all checks passed'}</span></>}
        </div>
      )}
      <div className="p-4" data-tour="tabs">
        <Tabs tabs={tabs} value={tab} onChange={setTab} />
        <div className="mt-4">
          {!done ? <div className="space-y-3"><Skeleton className="h-8 w-1/2" /><Skeleton className="h-80" /></div> : <>
            {tab === 'evidence' && (
              <div className="grid gap-4 2xl:grid-cols-[1.2fr_1fr] xl:grid-cols-[1.1fr_1fr]" data-tour="evidence">
                <EvidenceViewer doc={d} active={active} onSelect={setActive} extra={cite} />
                <div className="max-h-[calc(100vh-140px)] min-h-[300px] space-y-2 overflow-y-auto pr-1 scroll-thin">
                  <div className="text-xs text-muted">{fl.filter((f: any) => f.outcome !== 'pass').length} issue(s) · {fl.filter((f: any) => f.outcome === 'pass').length} check(s) passed. Click an issue to jump to it on the page.</div>
                  {[...fl.map((f: any, i: number) => ({ f, i }))].sort((a, b) => (a.f.outcome === 'pass' ? 1 : 0) - (b.f.outcome === 'pass' ? 1 : 0)).map(({ f, i }) => <FindingRow key={i} f={f} i={i} active={active === i} onClick={() => { setActive(i); setCite(null) }} />)}
                </div>
              </div>
            )}
            {tab === '4A' && <Forensics m={m['4A']} f={by('3').concat(by('4A'))} cdr={m.cdr} />}
            {tab === '4B' && <RulesTab m={m['4B']} f={by('4B')} bundle={m.bundle} pii={d.pii_masked} />}
            {tab === '4C' && <PhotoTab m={m['4C']} f={by('4C')} />}
            {tab === '4D' && <List f={by('4D')} empty="No cross-college links found for this document (blind-indexed PANs, file hashes and photo fingerprints were compared)." />}
            {tab === 'agents' && <div data-tour="agents"><Agents agents={d.agents} /></div>}
            {tab === 'ask' && <div className="grid gap-4 xl:grid-cols-[1.15fr_1fr]"><EvidenceViewer doc={d} active={null} onSelect={setActive} extra={cite} /><DocAssistant docId={d.id} onCite={setCite} /></div>}
            {tab === 'custody' && <Custody d={d} />}
          </>}
        </div>
      </div>
    </div>
  )
}

const KV = ({ k, v, mono }: { k: any; v: any; mono?: boolean }) => <div className="flex justify-between gap-4 border-b border-line/60 py-1.5 text-sm last:border-0"><span className="text-muted">{k}</span><span className={clsx('text-right font-medium', mono && 'font-mono text-xs')}>{v ?? '—'}</span></div>
const List = ({ f, empty }: { f: any[]; empty: string }) => f.length ? <div className="space-y-2">{f.map((x, i) => <FindingRow key={i} f={x} i={i} />)}</div> : <Empty icon={CheckCircle2} title="Nothing flagged" body={empty} />

function Forensics({ m, f, cdr }: any) {
  if (!m || m.reason) return <Empty icon={Info} title="Not applicable" body={m?.reason || 'No PDF forensics for this file type.'} />
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <div className="space-y-4">
        <div className="rounded-xl border border-line p-4"><div className="mb-2 text-sm font-semibold"><Term t="DSC" /> signatures</div>
          {m.signatures.length === 0 ? <p className="text-sm text-muted">No digital signature present in this PDF.</p> : m.signatures.map((s: any, i: number) => (
            <div key={i} className="text-sm">
              <KV k="Signer" v={s.signer?.split(';')[0].replace('Common Name: ', '')} /><KV k="Issuing CA" v={s.issuer?.split(',')[0].replace('Common Name: ', '')} />
              <KV k="Certificate validity" v={`${s.not_before} → ${s.not_after}`} /><KV k="Certificate expired" v={s.cert_expired ? 'Yes' : 'No'} />
              <KV k="Cryptographically intact" v={s.intact ? 'Yes' : 'No'} /><KV k="Trusted root" v={s.trusted ? 'Yes (demo CA)' : 'No'} />
              <KV k={<Term t="ByteRange">ByteRange covers whole file</Term>} v={s.covers_whole_file ? 'Yes' : 'No — bytes were added after signing'} /><KV k="Coverage" v={s.coverage} mono />
            </div>))}
        </div>
        <div className="rounded-xl border border-line p-4"><div className="mb-2 text-sm font-semibold">Edit history</div>
          <KV k="%%EOF markers" v={m.edit_history.eof_markers} /><KV k="/Prev pointers (incremental updates)" v={m.edit_history.prev_pointers} /><KV k="Edited after creation" v={m.edit_history.edited_after_creation ? 'Yes' : 'No'} />
        </div>
        <div className="rounded-xl border border-line p-4"><div className="mb-2 text-sm font-semibold"><Term t="CDR" /> result</div>
          <KV k="Method" v={cdr?.method} /><KV k="Active content found" v={cdr?.active_content_found ? 'Yes' : 'No'} /><KV k="Removed" v={cdr?.removed?.length ? cdr.removed.join(', ') : 'nothing'} />
        </div>
      </div>
      <div className="space-y-4">
        <div className="rounded-xl border border-line p-4"><div className="mb-2 text-sm font-semibold">Metadata & object tree</div>
          <KV k="Producer" v={m.metadata_check.producer} /><KV k="Creator" v={m.metadata_check.creator} /><KV k="Editing tool detected" v={m.metadata_check.editing_tool || 'none'} />
          <KV k="PDF version" v={m.object_tree.pdf_version} /><KV k="Objects / pages" v={`${m.object_tree.objects} / ${m.object_tree.pages}`} /><KV k="Fonts" v={m.object_tree.fonts.join(', ').replace(/\//g, '')} /><KV k="OCR fallback" v={m.ocr?.engine || 'not needed (text layer present)'} />
        </div>
        <div className="text-sm font-semibold">Forensic findings</div><List f={f} empty="No hidden text, overlays or signature problems." />
      </div>
    </div>
  )
}

function RulesTab({ m, f, bundle, pii }: any) {
  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
      <List f={f} empty="No rule checks apply." />
      <div className="space-y-4">
        <div className="rounded-xl border border-line p-4"><div className="mb-2 text-sm font-semibold">Extracted facts</div>{Object.entries(m?.facts || {}).filter(([k]) => k !== 'label').map(([k, v]: any) => <KV key={k} k={k.replace(/_/g, ' ')} v={String(v)} />)}{!Object.keys(m?.facts || {}).length && <p className="text-sm text-muted">No structured facts for this file type.</p>}</div>
        <div className="rounded-xl border border-line p-4"><div className="mb-2 text-sm font-semibold">Signed rule bundle</div><KV k="Bundle" v={m?.bundle?.id} mono /><KV k="Version" v={m?.bundle?.version} /><KV k="Signature" v={bundle?.valid ? 'Ed25519 ✓ valid' : 'INVALID'} /></div>
        {pii?.length > 0 && <div className="rounded-xl border border-line p-4"><div className="mb-2 text-sm font-semibold"><Term t="PII" /> found (masked)</div><div className="flex flex-wrap gap-1.5">{pii.map((p: string) => <span key={p} className="kbd">{p}</span>)}</div><p className="mt-2 text-xs text-muted">Full values are envelope-encrypted in the PII vault.</p></div>}
      </div>
    </div>
  )
}

function PhotoTab({ m, f }: any) {
  if (!m || m.reason) return <Empty icon={Info} title="Not applicable" body={m?.reason || 'Photo checks run on lab and infrastructure photos only.'} />
  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_340px]">
      <List f={f} empty="No issues." />
      <div className="space-y-4">
        <div className="rounded-xl border border-line p-4"><div className="mb-2 text-sm font-semibold">EXIF</div><KV k="Camera" v={`${m.exif.make || '—'} ${m.exif.model || ''}`} /><KV k="Taken" v={m.exif.datetime} /><KV k="GPS" v={m.exif.gps ? `${m.exif.gps.lat}, ${m.exif.gps.lon}` : 'none'} /><KV k="Size" v={`${m.exif.width}×${m.exif.height}`} /></div>
        <div className="rounded-xl border border-line p-4"><div className="mb-2 text-sm font-semibold"><Term t="pHash" /> & <Term t="ORB" /> matching</div><KV k="pHash" v={m.phash} mono />
          {m.matches.length === 0 ? <p className="mt-1 text-sm text-muted">No similar photo in any other submission.</p> : m.matches.map((x: any, i: number) => <div key={i} className="mt-2 rounded-lg bg-amber-50 p-2.5 text-xs dark:bg-amber-500/10"><b>Matches document #{x.document_id}</b> (college #{x.college_id})<br />pHash distance {x.phash_distance} · ORB {x.orb?.inliers} RANSAC inliers ({Math.round((x.orb?.inlier_ratio || 0) * 100)}%)</div>)}
        </div>
        <div className="rounded-xl border border-line p-4" data-testid="vision-models"><div className="mb-2 flex items-center justify-between text-sm font-semibold">Model vision <span className="kbd">{m.vision_backend || 'classic'}</span></div>
          {m.models ? <>
            <KV k="Global" v="DINOv2-small (384-d)" /><KV k="Layout hash" v={m.models.layout_hash?.slice(0, 18) + '…'} mono />
            {m.models.matches.length === 0 ? <p className="mt-1 text-sm text-muted">No pgvector neighbour above the candidate threshold.</p> : m.models.matches.filter((x: any) => !x.error).map((x: any, i: number) => <div key={i} className={`mt-2 rounded-lg p-2.5 text-xs ${x.cosine >= m.models.thresholds.dup_cosine && x.local.inliers >= m.models.thresholds.dup_inliers ? 'bg-red-50 dark:bg-red-500/10' : 'bg-amber-50 dark:bg-amber-500/10'}`}><b>Document #{x.document_id}</b> (college #{x.college_id})<br />DINOv2 cosine {x.cosine.toFixed(3)} · LightGlue {x.local.inliers}/{x.local.matches} inliers{x.layout_distance != null && <> · layout Δ{x.layout_distance}</>}</div>)}
            <div className="mt-3 text-xs font-medium">RT-DETR detections (COCO classes)</div>
            <div className="mt-1 flex flex-wrap gap-1">{m.models.detections.length ? m.models.detections.slice(0, 12).map((d: any, i: number) => <span key={i} className="kbd">{d.label} {Math.round(d.score * 100)}%</span>) : <span className="text-xs text-muted">none</span>}</div>
            <p className="mt-2 text-[11px] text-muted">Thresholds: duplicate if cosine ≥ {m.models.thresholds.dup_cosine} and ≥ {m.models.thresholds.dup_inliers} inliers. COCO has no lab-specific classes.</p>
          </> : <p className="text-xs text-muted">{m.vision_error ? `Models failed: ${m.vision_error}` : 'VISION_BACKEND=classic — pHash + ORB only.'}</p>}
        </div>
        <div className="rounded-xl border border-line p-4"><div className="mb-2 text-sm font-semibold">Room structure cues</div><KV k="Straight lines" v={m.room.straight_lines} /><KV k="Indoor structure likely" v={m.room.indoor_structure_likely ? 'Yes' : 'No'} /><p className="mt-2 text-[11px] text-muted">{m.room.method}</p></div>
      </div>
    </div>
  )
}

function Agents({ agents }: { agents: any[] }) {
  const meta: Record<string, [string, string]> = { Advocate: ['bg-emerald-500', 'Argues for authenticity'], Critic: ['bg-red-500', 'Argues against'], Head: ['bg-primary', 'Summarises and recommends'] }
  return (
    <div className="space-y-3">
      <div className="rounded-xl bg-surface-2 p-3 text-xs text-muted">Three agents debate the evidence. They <b>cannot change</b> the status — that comes from the deterministic policy engine. Engine: {agents[0]?.engine || 'rule-based'}{agents[0]?.engine === 'rule-based' && ' (set OPENAI_API_KEY to let an LLM rephrase the same facts).'}</div>
      {agents.map((a, i) => (
        <div key={i} className={clsx('flex gap-3 animate-fadeUp', a.agent === 'Critic' && 'flex-row-reverse')} style={{ animationDelay: `${i * 120}ms` }}>
          <div className="relative"><Avatar seed={`agent-${a.agent}-7`} size={40} /><span className={clsx('absolute -bottom-1 -right-1 h-4 w-4 rounded-full border-2 border-surface', meta[a.agent]?.[0])} /></div>
          <div className={clsx('max-w-[80%] rounded-2xl border border-line p-3.5', a.agent === 'Head' ? 'bg-primary-soft/60' : 'bg-surface')}>
            <div className="text-xs font-bold">{a.agent} <span className="font-normal text-muted">· {meta[a.agent]?.[1]}</span></div>
            <p className="mt-1 text-sm leading-relaxed">{a.message}</p>
          </div>
        </div>
      ))}
    </div>
  )
}

function Custody({ d }: any) {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <div className="rounded-xl border border-line p-4"><div className="mb-2 text-sm font-semibold">Immutable versions (<Term t="WORM" />)</div>
        {d.versions.map((v: any) => <div key={v.version} className="border-b border-line/60 py-2 text-sm last:border-0"><div className="flex justify-between"><b>v{v.version}</b><span className={v.worm ? 'text-emerald-600' : 'text-red-600'}>{v.worm ? 'read-only ✓' : 'writable!'}</span></div><div className="break-all font-mono text-[11px] text-muted">{v.sha256}</div><div className="text-xs text-muted">{fmtDate(v.created_at)} · {fmtSize(v.size)}</div></div>)}
      </div>
      <div className="rounded-xl border border-line p-4"><div className="mb-2 text-sm font-semibold">Sandbox job</div>
        <KV k="Job" v={`#${d.job.id}`} /><KV k="Job token id" v={d.job.token_jti} mono /><KV k="Token lifetime" v={`${d.modules.sandbox?.token_expires_in_s ?? 60} s`} /><KV k="Network egress" v={d.modules.sandbox?.egress} /><KV k="Isolated process" v={d.modules.sandbox?.pid_isolated ? 'Yes' : 'No'} /><KV k="Duration (measured)" v={`${d.job.duration_ms} ms`} />
      </div>
    </div>
  )
}
