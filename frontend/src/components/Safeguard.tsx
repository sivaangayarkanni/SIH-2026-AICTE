import { Scale } from 'lucide-react'

export const SAFEGUARD = 'Automated alerts, recommendations and workflow actions support the approval process; they do not replace statutory scrutiny, verification, inspections or decisions taken by the competent authority.'

export function Safeguard({ compact }: { compact?: boolean }) {
  return (
    <div data-testid="safeguard" role="note" className={compact ? 'flex items-start gap-2 text-xs text-muted' : 'mb-4 flex items-start gap-2.5 rounded-xl border border-amber-300/60 bg-amber-50 px-4 py-2.5 text-sm text-amber-900 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200'}>
      <Scale className="mt-0.5 h-4 w-4 shrink-0" /><span><b>Regulatory safeguard.</b> {SAFEGUARD}</span>
    </div>
  )
}
