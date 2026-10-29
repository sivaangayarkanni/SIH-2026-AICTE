// Deterministic, locally generated illustrated avatars (DiceBear-style, no external calls).
const BG = ['#dbeafe', '#fde68a', '#bbf7d0', '#fbcfe8', '#ddd6fe', '#fed7aa', '#a5f3fc', '#e9d5ff']
const SKIN = ['#f1c27d', '#e0ac69', '#c68642', '#8d5524', '#ffdbac', '#d4a373']
const HAIR = ['#2d1b0e', '#4a2c17', '#111827', '#6b3e26', '#3f3f46', '#7c2d12']
const SHIRT = ['#0b4ea2', '#047857', '#4f46e5', '#dd600a', '#be123c', '#0f766e', '#7c3aed']

function h(s: string) { let x = 2166136261; for (const c of s) { x ^= c.charCodeAt(0); x = Math.imul(x, 16777619) } return Math.abs(x) }

export function Avatar({ seed, size = 36, ring = false, title }: { seed: string; size?: number; ring?: boolean; title?: string }) {
  const n = h(seed || 'x'), pick = <T,>(a: T[], k: number) => a[(n >> k) % a.length]
  const bg = pick(BG, 1), skin = pick(SKIN, 3), hair = pick(HAIR, 5), shirt = pick(SHIRT, 7)
  const style = (n >> 9) % 5, glasses = (n >> 12) % 3 === 0, smile = (n >> 14) % 3
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" role="img" aria-label={title || `Avatar for ${seed}`}
      className={`shrink-0 rounded-full ${ring ? 'ring-2 ring-white shadow' : ''}`}>
      <title>{title || seed}</title>
      <circle cx="32" cy="32" r="32" fill={bg} />
      {style === 1 && <path d="M14 30c0-14 8-20 18-20s18 6 18 20v20H14z" fill={hair} />}
      {style === 3 && <path d="M12 34c0-16 9-23 20-23s20 7 20 23c0 8-3 14-3 14H15s-3-6-3-14z" fill={hair} />}
      <path d="M10 64c2-12 11-18 22-18s20 6 22 18z" fill={shirt} />
      <path d="M27 42h10v7a5 5 0 0 1-10 0z" fill={skin} />
      <ellipse cx="32" cy="30" rx="13" ry="15" fill={skin} />
      {style === 0 && <path d="M19 27c0-10 6-15 13-15s13 5 13 15c-3-5-8-7-13-7s-10 2-13 7z" fill={hair} />}
      {style === 1 && <path d="M19 26c1-9 6-13 13-13s12 4 13 13c-4-3-9-6-13-6s-9 3-13 6z" fill={hair} />}
      {style === 2 && <><path d="M19 27c0-10 6-15 13-15s13 5 13 15c-5-6-21-6-26 0z" fill={hair} /><circle cx="32" cy="10" r="6" fill={hair} /></>}
      {style === 3 && <path d="M19 28c0-10 6-15 13-15s13 5 13 15c-2-4-6-8-13-8s-11 4-13 8z" fill={hair} />}
      {style === 4 && <path d="M20 24c2-7 7-10 12-10s10 3 12 10c-3-2-7-3-12-3s-9 1-12 3z" fill={hair} />}
      <circle cx="26.5" cy="31" r="1.8" fill="#1f2937" /><circle cx="37.5" cy="31" r="1.8" fill="#1f2937" />
      {glasses && <g fill="none" stroke="#1f2937" strokeWidth="1.3"><circle cx="26.5" cy="31" r="4.2" /><circle cx="37.5" cy="31" r="4.2" /><path d="M30.7 31h2.6" /></g>}
      {smile === 0 && <path d="M27 37.5c2.5 2.5 7.5 2.5 10 0" stroke="#7c2d12" strokeWidth="1.6" fill="none" strokeLinecap="round" />}
      {smile === 1 && <path d="M27.5 37c2 3 7 3 9 0z" fill="#9f1239" />}
      {smile === 2 && <path d="M28.5 38h7" stroke="#7c2d12" strokeWidth="1.6" strokeLinecap="round" />}
      <circle cx="23" cy="35" r="2" fill="#f87171" opacity=".25" /><circle cx="41" cy="35" r="2" fill="#f87171" opacity=".25" />
    </svg>
  )
}
