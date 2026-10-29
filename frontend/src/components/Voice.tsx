import { useEffect, useRef, useState } from 'react'
import { Mic, MicOff, Send, Volume2, Loader2, MessageSquareQuote } from 'lucide-react'
import { api } from '../lib/api'

// Document Q&A: answers are retrieved verbatim from the analysed text with a page citation (no free-text generation).
export function DocAssistant({ docId, onCite }: { docId: number; onCite: (c: any) => void }) {
  const [q, setQ] = useState(''); const [log, setLog] = useState<any[]>([]); const [busy, setBusy] = useState(false); const [listening, setListening] = useState(false)
  const rec = useRef<any>(null)
  const SR: any = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
  useEffect(() => { setLog([]) }, [docId])
  const ask = async (question: string) => {
    if (!question.trim()) return
    setBusy(true); setQ('')
    try { const r = await api(`/api/documents/${docId}/ask`, { method: 'POST', json: { question } }); setLog((l) => [...l, { q: question, ...r }]); if (r.citation) onCite(r.citation) }
    catch (e: any) { setLog((l) => [...l, { q: question, answer: e.message, confidence: 'error' }]) } finally { setBusy(false) }
  }
  const speak = (t: string) => { if ('speechSynthesis' in window) { speechSynthesis.cancel(); const u = new SpeechSynthesisUtterance(t); u.lang = 'en-IN'; speechSynthesis.speak(u) } }
  const listen = () => {
    if (!SR) return
    if (listening) { rec.current?.stop(); return }
    const r = new SR(); r.lang = 'en-IN'; r.interimResults = false
    r.onresult = (e: any) => { const t = e.results[0][0].transcript; setQ(t); ask(t) }
    r.onend = () => setListening(false); r.onerror = () => setListening(false)
    rec.current = r; r.start(); setListening(true)
  }
  const sugg = ['Why was this flagged?', 'Who issued this document?', 'What is the validity date?', 'What is the land area?', 'Is the signature valid?']
  return (
    <div className="flex flex-col gap-3">
      <div className="rounded-xl bg-primary-soft/60 p-3 text-xs text-muted"><b className="text-ink">Document assistant.</b> Ask by typing or voice. Answers are quoted from the document with a page citation, which is highlighted on the evidence viewer. Nothing is generated or guessed.</div>
      <div className="flex flex-wrap gap-1.5">{sugg.map((s) => <button key={s} className="chip border border-line bg-surface hover:border-primary" onClick={() => ask(s)}>{s}</button>)}</div>
      <div className="max-h-72 space-y-3 overflow-y-auto scroll-thin">
        {log.map((m, i) => (
          <div key={i} className="space-y-1.5 animate-fadeUp">
            <div className="ml-auto w-fit max-w-[85%] rounded-2xl rounded-br-sm bg-primary px-3 py-2 text-sm text-primary-fg">{m.q}</div>
            <div className="w-fit max-w-[92%] rounded-2xl rounded-bl-sm border border-line bg-surface px-3 py-2 text-sm">
              <div className="flex gap-2"><MessageSquareQuote className="mt-0.5 h-4 w-4 shrink-0 text-primary" /><span>{m.answer}</span></div>
              <div className="mt-1.5 flex items-center gap-2 text-[11px] text-muted">
                {m.citation && <button className="font-semibold text-primary hover:underline" onClick={() => onCite(m.citation)}>Show on page {m.citation.page}</button>}
                <span>confidence: {m.confidence}</span>{m.method && <span>· {m.method}</span>}
                <button aria-label="Read answer aloud" className="ml-auto hover:text-ink" onClick={() => speak(m.answer)}><Volume2 className="h-3.5 w-3.5" /></button>
              </div>
            </div>
          </div>
        ))}
      </div>
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); ask(q) }}>
        <button type="button" onClick={listen} disabled={!SR} title={SR ? 'Speak your question (Web Speech API)' : 'Voice input is not supported in this browser'} aria-label="Voice input"
          className={`btn-ghost px-3 ${listening ? 'border-red-400 text-red-600 animate-pulseRing' : ''}`}>{listening ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}</button>
        <input className="input" placeholder={listening ? 'Listening…' : 'Ask about this document'} value={q} onChange={(e) => setQ(e.target.value)} aria-label="Question" />
        <button className="btn-primary px-3" disabled={busy || !q.trim()} aria-label="Ask">{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}</button>
      </form>
    </div>
  )
}
