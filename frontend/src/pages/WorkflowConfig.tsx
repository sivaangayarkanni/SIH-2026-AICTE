import { useEffect, useState } from 'react'
import { Play, Save, ShieldCheck } from 'lucide-react'
import { api, fmtDate } from '../lib/api'
import { PageHeader, Skeleton, Tabs } from '../components/ui'
import { useToast } from '../components/Toast'
import { Safeguard } from '../components/Safeguard'
import { useAuth } from '../lib/auth'

export default function WorkflowConfig() {
  const { user } = useAuth(); const toast = useToast(); const admin = user?.role === 'admin'
  const [c, setC] = useState<any>(null); const [txt, setTxt] = useState(''); const [note, setNote] = useState(''); const [tab, setTab] = useState('config')
  const [reg, setReg] = useState<any>(null); const [sch, setSch] = useState<any>(null); const [ig, setIg] = useState<any>(null)
  const load = () => { api('/api/wf/config').then((x) => { setC(x); setTxt(JSON.stringify(x.config, null, 2)) }); api('/api/wf/regions').then(setReg); api('/api/wf/scheduler').then(setSch); api('/api/wf/integrations').then(setIg) }
  useEffect(load, [])
  const save = async () => {
    let parsed: any; try { parsed = JSON.parse(txt) } catch (e: any) { toast('error', 'Not valid JSON', e.message); return }
    try { const r = await api('/api/wf/config', { method: 'PUT', json: { config: parsed, note } }); setC(r); setTxt(JSON.stringify(r.config, null, 2)); setNote(''); toast('success', `Saved as version ${r.version}`, 'Signed and active.') }
    catch (e: any) { toast('error', 'Rejected', e.message) }
  }
  const assign = async (user_id: number, region_code: string) => { try { setReg(await api('/api/wf/regions/assign', { method: 'PUT', json: { user_id, region_code: region_code || null } })); toast('success', 'Region updated') } catch (e: any) { toast('error', 'Could not assign', e.message) } }
  const run = async () => { try { const r = await api('/api/wf/evaluate', { method: 'POST', json: {} }); toast('success', 'Evaluation finished', `${r.created ?? 0} new alert(s), ${r.closed ?? 0} closed`); load() } catch (e: any) { toast('error', 'Failed', e.message) } }
  if (!c) return <Skeleton className="h-96" />
  return (
    <>
      <PageHeader eyebrow="Administration" title="Workflow configuration" desc={<span className="inline-flex items-center gap-1"><ShieldCheck className="h-4 w-4" />Version {c.version ?? 'default'} · {c.source}</span>}
        actions={(admin || user?.role === 'senior_officer') && <button className="btn-ghost" data-testid="wf-run" onClick={run}><Play className="h-4 w-4" />Run deadline check now</button>} />
      <Safeguard compact />
      <div className="my-3"><Tabs value={tab} onChange={setTab} tabs={[{ id: 'config', label: 'Routes, timelines & escalation' }, { id: 'regions', label: 'Regions' }, { id: 'scheduler', label: 'Scheduler' }, { id: 'integrations', label: 'Integration hooks' }]} /></div>
      {tab === 'config' && <div className="grid gap-4 lg:grid-cols-[1fr_300px]">
        <div className="card card-pad"><textarea data-testid="wf-json" className="input h-[520px] font-mono text-xs" value={txt} readOnly={!admin} onChange={(e) => setTxt(e.target.value)} spellCheck={false} />
          {admin ? <div className="mt-3 flex gap-2"><input className="input" placeholder="Change note (required)" value={note} onChange={(e) => setNote(e.target.value)} /><button className="btn-primary" disabled={note.trim().length < 3} onClick={save}><Save className="h-4 w-4" />Save new version</button></div>
            : <p className="mt-2 text-xs text-muted">Read-only. Only an administrator can change the configuration.</p>}</div>
        <div className="card card-pad text-sm"><div className="mb-2 font-semibold">Versions</div>
          <ul className="space-y-2">{c.versions.map((v: any) => <li key={v.version}><b>v{v.version}</b> · {fmtDate(v.created_at)}<div className="text-xs text-muted">{v.created_by} — {v.note}</div><div className="font-mono text-[10px] text-muted">{v.sha256.slice(0, 16)}…</div></li>)}
            {!c.versions.length && <li className="text-muted">Using the shipped default. Saving creates version 1.</li>}</ul></div></div>}
      {tab === 'regions' && reg && <div className="card card-pad text-sm"><p className="mb-3 text-xs text-muted">{reg.note}</p>
        <table className="w-full"><thead className="table-head"><tr><th className="py-2 text-left">Officer</th><th className="text-left">Role</th><th className="text-left">Region</th></tr></thead><tbody>{reg.officers.map((o: any) => <tr key={o.id} className="border-b border-line/60"><td className="py-2">{o.name}</td><td>{o.role_label}</td>
          <td>{o.role === 'officer' ? <select className="input w-56" disabled={!admin} value={o.region || ''} onChange={(e) => assign(o.id, e.target.value)}><option value="">— all (unassigned) —</option>{reg.regions.map((r: any) => <option key={r.code} value={r.code}>{r.name}</option>)}</select> : <span className="text-muted">all regions</span>}</td></tr>)}</tbody></table></div>}
      {tab === 'scheduler' && sch && <div className="card card-pad text-sm"><div>Cron: {sch.cron_configured ? 'configured (daily via Vercel Cron)' : 'CRON_SECRET not set — endpoint disabled'} · dev loop: {sch.dev_loop_s ? `${sch.dev_loop_s}s` : 'off'}</div>
        <table className="mt-3 w-full"><thead className="table-head"><tr><th className="py-2 text-left">Run</th><th className="text-left">Started</th><th className="text-left">Trigger</th><th className="text-left">New alerts</th><th className="text-left">Closed</th></tr></thead><tbody>{sch.runs.map((r: any) => <tr key={r.id} className="border-b border-line/60"><td className="py-1.5">#{r.id}</td><td>{fmtDate(r.started_at)}</td><td>{r.trigger}{r.skipped ? ' (skipped: lock held)' : ''}</td><td>{r.created}</td><td>{r.closed}</td></tr>)}</tbody></table></div>}
      {tab === 'integrations' && ig && <div className="card card-pad text-sm"><pre className="whitespace-pre-wrap font-mono text-xs">{JSON.stringify(ig, null, 2)}</pre></div>}
    </>
  )
}
