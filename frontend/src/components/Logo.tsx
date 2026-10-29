export function Logo({ size = 34, light = false }: { size?: number; light?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden>
        <defs><linearGradient id="lg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="rgb(var(--side-active))" /><stop offset="1" stopColor="rgb(var(--primary))" /></linearGradient></defs>
        <path d="M32 4l22 8v17c0 15-9.5 26-22 31C19.5 55 10 44 10 29V12z" fill="url(#lg)" />
        <path d="M21 32l8 8 15-16" fill="none" stroke="#fff" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="47" cy="14" r="5" fill="rgb(var(--accent))" />
      </svg>
      <div className="leading-none">
        <div className={`font-display text-[19px] font-bold ${light ? 'text-white' : 'text-ink'}`}>Seal<span className="text-accent">Check</span></div>
        <div className={`mt-1 text-[9.5px] font-semibold uppercase tracking-[.16em] ${light ? 'text-white/60' : 'text-muted'}`}>Zero-Trust · AICTE</div>
      </div>
    </div>
  )
}
