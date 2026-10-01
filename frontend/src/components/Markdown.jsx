import ReactMarkdown, { defaultUrlTransform } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { parseHelpTarget } from '../lib/help.js'

const slugify = (text) => String(text).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
const textOf = (children) => [children].flat().map((c) => (typeof c === 'string' ? c : c?.props ? textOf(c.props.children) : '')).join('')

/**
 * Help and assistant text. React elements only (no raw HTML), so it's safe under the
 * strict CSP. `help:slug#anchor` links open inside the help center.
 */
export default function Markdown({ children, onHelpLink }) {
  return (
    <div className="md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        urlTransform={(url) => (url.startsWith('help:') ? url : defaultUrlTransform(url))}
        components={{
          h1: () => null, // the panel shows the title
          h2: ({ children: c }) => <h3 id={slugify(textOf(c))}>{c}</h3>,
          h3: ({ children: c }) => <h4>{c}</h4>,
          table: ({ children: c }) => <div className="table-wrap" tabIndex={0}><table className="data">{c}</table></div>,
          a: ({ href = '', children: c }) => {
            if (href.startsWith('help:')) {
              const { slug, anchor } = parseHelpTarget(href)
              return <a href={`?help=${slug}${anchor ? `#${anchor}` : ''}`} onClick={(e) => { e.preventDefault(); onHelpLink?.(slug, anchor) }}>{c}</a>
            }
            return <a href={href} target="_blank" rel="noopener noreferrer">{c}</a>
          },
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  )
}
