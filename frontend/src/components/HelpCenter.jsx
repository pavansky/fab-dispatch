import { useEffect, useRef, useState } from 'react'
import { helpArticle, helpIndex, helpSearch } from '../api.js'
import { useHelp } from '../lib/help.js'
import Markdown from './Markdown.jsx'

/**
 * The help center: browse by section, search, read an article. Articles are the same
 * Markdown the assistant answers from, served by the API.
 */
export default function HelpCenter({ target, onNavigate, onClose, onTour }) {
  const { openAssistant } = useHelp()
  const [toc, setToc] = useState(null)
  const [article, setArticle] = useState(null)
  const [query, setQuery] = useState('')
  const [results, setResults] = useState(null)
  const [error, setError] = useState(null)
  const panel = useRef(null)
  const search = useRef(null)

  useEffect(() => { helpIndex().then((d) => setToc(d.sections)).catch((e) => setError(e.message)) }, [])

  // Open the requested article, then scroll to the section (if any).
  useEffect(() => {
    if (!target?.slug) { setArticle(null); return }
    let live = true
    setError(null)
    helpArticle(target.slug).then((a) => {
      if (!live) return
      setArticle(a)
      requestAnimationFrame(() => {
        const el = target.anchor && panel.current?.querySelector(`#${CSS.escape(target.anchor)}`)
        if (el) el.scrollIntoView?.({ block: 'start' })
        else panel.current?.querySelector('.help-body')?.scrollTo?.(0, 0)
      })
    }).catch((e) => live && setError(e.message))
    return () => { live = false }
  }, [target?.slug, target?.anchor])

  // Search as you type (debounced, cancellable).
  useEffect(() => {
    if (!query.trim()) { setResults(null); return }
    const c = new AbortController()
    const t = setTimeout(() => helpSearch(query.trim(), c.signal).then((d) => setResults(d.results)).catch(() => {}), 180)
    return () => { clearTimeout(t); c.abort() }
  }, [query])

  useEffect(() => {
    const esc = (e) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', esc)
    return () => document.removeEventListener('keydown', esc)
  }, [onClose])
  useEffect(() => { if (!target?.slug) search.current?.focus() }, [target?.slug])

  const open = (slug, anchor = '') => { setQuery(''); onNavigate(slug, anchor) }

  let body
  if (error) body = <div className="error-bar" role="alert">{error}</div>
  else if (results) {
    body = results.length === 0 ? (
      <div className="empty">No articles match “{query}”. Try other words, or <button className="link" onClick={() => openAssistant(query)}>ask the assistant</button>.</div>
    ) : (
      <ul className="help-list" aria-label="Search results">
        {results.map((r) => (
          <li key={`${r.slug}#${r.anchor}`}>
            <button onClick={() => open(r.slug, r.anchor)}>
              <b>{r.title}</b>{r.anchor && <span className="muted"> › {r.heading}</span>}
              <span className="help-snippet">{r.snippet}</span>
            </button>
          </li>
        ))}
      </ul>
    )
  } else if (target?.slug && article) {
    body = (
      <article aria-labelledby="help-title">
        <button className="btn ghost back" onClick={() => onNavigate(null)}>← All help</button>
        <p className="eyebrow">{article.section}</p>
        <h2 id="help-title">{article.title}</h2>
        <Markdown onHelpLink={open}>{article.body}</Markdown>
        <div className="help-cta">
          <span>Still stuck?</span>
          <button className="btn" onClick={() => openAssistant('')}>Ask the assistant</button>
        </div>
      </article>
    )
  } else if (toc) {
    body = (
      <>
        {toc.map((s) => (
          <section key={s.name} className="help-section">
            <p className="eyebrow">{s.name}</p>
            <ul className="help-list">
              {s.articles.map((a) => (
                <li key={a.slug}><button onClick={() => open(a.slug)}><b>{a.title}</b><span className="help-snippet">{a.summary}</span></button></li>
              ))}
            </ul>
          </section>
        ))}
        <div className="help-cta">
          <button className="btn" onClick={onTour}>Take the tour</button>
          <button className="btn" onClick={() => openAssistant('')}>Ask the assistant</button>
        </div>
      </>
    )
  } else body = <div className="empty"><span className="solving"><span className="spinner" />Loading help…</span></div>

  return (
    <>
      <div className="backdrop help-backdrop" onClick={onClose} aria-hidden />
      <aside className="help-panel" role="dialog" aria-modal="true" aria-label="Help" ref={panel}>
        <div className="help-h">
          <b>Help</b>
          <input ref={search} className="input" type="search" placeholder="Search help" aria-label="Search help"
            value={query} onChange={(e) => setQuery(e.target.value)} />
          <button className="btn ghost" onClick={onClose} aria-label="Close help">✕</button>
        </div>
        <div className="help-body">{body}</div>
      </aside>
    </>
  )
}
