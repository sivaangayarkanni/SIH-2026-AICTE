/** @type {import('tailwindcss').Config} */
const v = (n) => `rgb(var(--${n}) / <alpha-value>)`
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: ['class'],
  theme: {
    extend: {
      fontFamily: { sans: ['Inter', 'system-ui', 'sans-serif'], serif: ['"Source Serif 4"', 'Georgia', 'serif'] },
      colors: {
        primary: { DEFAULT: v('primary'), fg: v('primary-fg'), soft: v('primary-soft') },
        accent: { DEFAULT: v('accent'), soft: v('accent-soft') },
        bg: v('bg'), surface: v('surface'), 'surface-2': v('surface-2'), line: v('line'), ink: v('ink'), muted: v('muted'),
        side: { DEFAULT: v('side'), ink: v('side-ink'), active: v('side-active') },
      },
      boxShadow: { card: '0 1px 2px rgb(15 23 42 / .04), 0 4px 16px -4px rgb(15 23 42 / .08)', pop: '0 12px 40px -8px rgb(15 23 42 / .25)' },
      keyframes: {
        fadeUp: { '0%': { opacity: 0, transform: 'translateY(8px)' }, '100%': { opacity: 1, transform: 'none' } },
        pulseRing: { '0%': { boxShadow: '0 0 0 0 rgb(var(--primary) / .5)' }, '100%': { boxShadow: '0 0 0 14px rgb(var(--primary) / 0)' } },
        shimmer: { '100%': { transform: 'translateX(100%)' } },
        flow: { '0%': { strokeDashoffset: 24 }, '100%': { strokeDashoffset: 0 } },
      },
      animation: { fadeUp: 'fadeUp .35s ease-out both', pulseRing: 'pulseRing 1.4s ease-out infinite', flow: 'flow 1s linear infinite' },
    },
  },
  plugins: [],
}
