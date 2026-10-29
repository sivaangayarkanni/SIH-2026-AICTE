import { Upload, ShieldCheck, Box, Fingerprint, BookOpenCheck, Camera, Network, Scale, FileCheck2, Bot, UserCheck, ArrowDown } from 'lucide-react'
import { PageHeader, Term } from '../components/ui'

const STEPS = [
  { n: '1', i: Upload, t: 'Category & checklist', d: 'The college picks what it is applying for; the signed rule bundle produces the exact document checklist.', who: 'College' },
  { n: '2', i: ShieldCheck, t: 'Secure upload gateway', d: <>File type checked by magic bytes, size limit, malware scan, <Term t="SHA-256" /> fingerprint, then stored as a read-only <Term t="WORM" /> original.</>, who: 'Gateway' },
  { n: '3', i: Box, t: 'CDR + isolated sandbox', d: <><Term t="CDR" /> rebuilds the file without scripts or attachments. Analysis runs in a separate, resource-limited process with no network and a 60-second job token.</>, who: 'Sandbox' },
  { n: '4A', i: Fingerprint, t: 'PDF forensics', d: <>Hidden white text, white-box overlays, <Term t="DSC" /> signature validity, <Term t="ByteRange" /> coverage, incremental edits and editing-tool metadata.</>, who: 'Analysis' },
  { n: '4B', i: BookOpenCheck, t: 'AICTE rule engine', d: 'Required fields, issuer registry and validity dates, each tied to a clause and rule ID.', who: 'Analysis' },
  { n: '4C', i: Camera, t: 'Photo inspector', d: <>EXIF geotag, <Term t="pHash" /> and <Term t="ORB" /> matching against every other submission, plus room-structure cues.</>, who: 'Analysis' },
  { n: '4D', i: Network, t: 'Collusion graph', d: 'Blind-indexed PANs, identical file hashes and recycled photos link institutions for review.', who: 'Analysis' },
  { n: '5', i: Scale, t: 'Deterministic policy engine', d: 'An ordered rule table (P1–P6) turns findings into one of six statuses. Same input, same output, every time.', who: 'Policy' },
  { n: '6', i: Bot, t: 'Agents explain', d: 'Advocate, Critic and Head agents debate the evidence in plain language. They cannot change the status.', who: 'Explainability' },
  { n: '7', i: UserCheck, t: 'Officer decides', d: 'Priority queue, highlighted evidence, Q&A with citations. Forgery flags need a two-person override.', who: 'Human' },
  { n: '8', i: ArrowDown, t: 'Workflow, compliance & alerts', d: 'The application moves through configurable stages (scrutiny, EVC, review, decision) with SLA clocks. EVC visits are scheduled, undertakings and lease/document validity are tracked, reminders go out before deadlines and missed ones escalate to officers. Everything shows on the calendar, pendency dashboard and reports.', who: 'Workflow' },
  { n: '9', i: FileCheck2, t: 'Evidence packet & audit', d: 'Signed-off decisions, evidence PDFs and a hash-chained audit trail that anyone can re-verify.', who: 'Record' },
]
const STATUSES = [
  ['Verified', 'All checks passed.', 'bg-emerald-500'], ['Mismatch Detected', 'Forgery indicator found — hidden text, overlay, broken signature or reused photo.', 'bg-amber-500'],
  ['Expired', 'Document or signing certificate is out of date.', 'bg-red-500'], ['Source Unavailable', 'Issuer could not be confirmed.', 'bg-slate-400'],
  ['Manual Review Required', 'Needs a human: removed active content, unsigned edits, shared PAN or missing fields.', 'bg-purple-500'], ['Verification Pending', 'Analysis running or documents missing.', 'bg-blue-500'],
]

export default function HowItWorks() {
  return (
    <>
      <PageHeader eyebrow="Plain-language guide" title="How SealCheck works" desc="SealCheck runs the AICTE approval workflow end to end and verifies every document on the way. No file is trusted because of who uploaded it: each is proven genuine by evidence, or flagged with the exact reason." />
      <div className="grid gap-6 lg:grid-cols-[1fr_360px]">
        <ol className="space-y-2">{STEPS.map((s, i) => (
          <li key={s.n}>
            <div className="card flex gap-4 p-4 animate-fadeUp" style={{ animationDelay: `${i * 40}ms` }}>
              <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-primary text-sm font-bold text-primary-fg">{s.n}</div>
              <div className="flex-1"><div className="flex items-center gap-2"><s.i className="h-4 w-4 text-primary" /><b>{s.t}</b><span className="ml-auto chip bg-surface-2 text-muted">{s.who}</span></div><p className="mt-1 text-sm text-muted">{s.d}</p></div>
            </div>
            {i < STEPS.length - 1 && <ArrowDown className="mx-auto my-0.5 h-4 w-4 text-line" />}
          </li>
        ))}</ol>
        <div className="space-y-5">
          <div className="card card-pad lg:sticky lg:top-24"><div className="text-sm font-semibold">The six statuses</div>
            <ul className="mt-3 space-y-3">{STATUSES.map(([t, d, c]) => <li key={t} className="flex gap-3"><span className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${c}`} /><span><b className="text-sm">{t}</b><span className="block text-xs text-muted">{d}</span></span></li>)}</ul>
            <div className="mt-5 rounded-xl bg-primary-soft/70 p-3 text-xs"><b>AI never decides.</b> Detection and policy are deterministic code; AI agents only explain. Final approval is always a named, audited human.</div>
          </div>
        </div>
      </div>
    </>
  )
}
