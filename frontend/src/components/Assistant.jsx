import { useEffect, useRef, useState } from 'react'
import { askAssistant, sendFeedback } from '../api.js'
import { parseHelpTarget, useHelp } from '../lib/help.js'
import { LINKS } from '../lib/links.js'
import Markdown from './Markdown.jsx'

let nextId = 1

/**
 * Ask Dispatch: a chat panel over the grounded assistant. Every answer shows its sources
 * (help articles) and offers actions (open a job, a strategy, a view). The conversation
 * lives in the workspace, so it survives closing the panel and switching views.
 */
export default function Assistant({ messages, setMessages, context, suggestions, draft = '', onAction, onClose }) {
  const { openHelp } = useHelp()
  const [text, setText] = useState(draft)
  const [busy, setBusy] = useState(false)
  const list = useRef(null)
  const input = useRef(null)

  useEffect(() => { input.current?.focus() }, [])
  useEffect(() => { list.current?.scrollTo?.(0, list.current.scrollHeight) }, [messages, busy])
  useEffect(() => {
    const esc = (e) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', esc)
    return () => document.removeEventListener('keydown', esc)
  }, [onClose])

  const send = async (question) => {
    const q = question.trim()
    if (!q || busy) return
    setText('')
    setMessages((m) => [...m, { id: nextId++, role: 'user', text: q }])
    setBusy(true)
    try {
      const a = await askAssistant(q, context())
      setMessages((m) => [...m, { id: nextId++, role: 'assistant', question: q, ...a }])
    } catch (e) {
      setMessages((m) => [...m, { id: nextId++, role: 'assistant', error: true, answer: e.message, citations: [], actions: [] }])
    } finally {
      setBusy(false)
      input.current?.focus()
    }
  }

  const patch = (id, change) => setMessages((all) => all.map((x) => (x.id === id ? { ...x, ...change } : x)))
  const rate = (m, helpful, comment = '') => {
    patch(m.id, { feedback: 'sent' })
    sendFeedback({
      question: m.question, intent: m.intent, helpful, comment,
      citations: (m.citations ?? []).map((c) => c.slug), provider: m.provider ?? 'local',
    }).catch(() => {}) // feedback is best-effort; never interrupt the conversation
  }

  const act = (a) => {
    if (a.kind === 'help') { const { slug, anchor } = parseHelpTarget(a.target); openHelp(slug, anchor) } else onAction(a)
  }
  const shown = messages.at(-1)?.suggestions?.length ? messages.at(-1).suggestions : suggestions

  return (
    <aside className="assistant" role="dialog" aria-label="Assistant">
      <div className="assistant-h">
        <div>
          <b>Ask Dispatch</b>
          <p className="help">Answers from help and the shift on your screen, with sources. <a href={LINKS.aiTransparency} target="_blank" rel="noopener noreferrer">How it works</a></p>
        </div>
        {messages.length > 0 && <button className="btn ghost" onClick={() => setMessages([])}>Clear</button>}
        <button className="btn ghost" onClick={onClose} aria-label="Close assistant">✕</button>
      </div>

      <ol className="assistant-log" ref={list} aria-live="polite" aria-label="Conversation">
        {messages.length === 0 && (
          <li className="msg assistant-msg intro">
            <p>Ask about this shift (<i>why is a job unassigned?</i>, <i>what is an engineer doing?</i>) or about the app.
              I only answer from the help articles and your plans, and I'll say when I don't know.</p>
          </li>
        )}
        {messages.map((m) => m.role === 'user' ? (
          <li key={m.id} className="msg user-msg"><span className="sr-only">You: </span>{m.text}</li>
        ) : (
          <li key={m.id} className={`msg assistant-msg ${m.error ? 'is-error' : ''}`}>
            <span className="sr-only">Assistant: </span>
            <Markdown onHelpLink={openHelp}>{m.answer}</Markdown>
            {m.actions?.length > 0 && (
              <div className="msg-actions">
                {m.actions.map((a) => <button key={`${a.kind}:${a.target}`} className="btn" onClick={() => act(a)}>{a.label}</button>)}
              </div>
            )}
            {m.citations?.length > 0 && (
              <div className="msg-sources">
                <span className="muted">Sources:</span>
                {m.citations.map((c) => (
                  <button key={`${c.slug}#${c.anchor}`} className="chip source" onClick={() => openHelp(c.slug, c.anchor)}>
                    {c.title}{c.anchor && c.heading !== c.title ? ` › ${c.heading}` : ''}
                  </button>
                ))}
              </div>
            )}
            {m.provider && m.provider !== 'local' && <p className="help" style={{ margin: '6px 0 0' }}>Worded by {m.provider}; facts from the sources above.</p>}
            {!m.error && m.question && (
              <div className="msg-feedback" aria-label="Rate this answer">
                {m.feedback === 'sent' ? <span className="muted">Thanks for the feedback.</span>
                  : m.feedback === 'down' ? (
                    <form onSubmit={(e) => { e.preventDefault(); rate(m, false, new FormData(e.currentTarget).get('comment') ?? '') }}>
                      <input className="input" name="comment" maxLength={500} placeholder="What was wrong? (optional)" aria-label="What was wrong with this answer?" />
                      <button className="btn">Send</button>
                    </form>
                  ) : (
                    <>
                      <span className="muted">Helpful?</span>
                      <button className="btn ghost" aria-label="Helpful" onClick={() => rate(m, true)}>👍</button>
                      <button className="btn ghost" aria-label="Not helpful" onClick={() => patch(m.id, { feedback: 'down' })}>👎</button>
                    </>
                  )}
              </div>
            )}
          </li>
        ))}
        {busy && <li className="msg assistant-msg"><span className="solving"><span className="spinner" />Looking it up…</span></li>}
      </ol>

      {shown.length > 0 && (
        <div className="assistant-suggest" aria-label="Suggested questions">
          {shown.map((s) => <button key={s} className="chip" disabled={busy} onClick={() => send(s)}>{s}</button>)}
        </div>
      )}
      <form className="assistant-input" onSubmit={(e) => { e.preventDefault(); send(text) }}>
        <input ref={input} className="input" value={text} onChange={(e) => setText(e.target.value)} maxLength={500}
          placeholder="Ask about this shift or the app" aria-label="Your question" />
        <button className="btn primary" disabled={busy || !text.trim()}>Ask</button>
      </form>
    </aside>
  )
}
