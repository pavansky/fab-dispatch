import { useHelp } from '../lib/help.js'

/** A small ⓘ that opens the help center at the article (and section) about this control. */
export default function InfoLink({ slug, anchor = '', label }) {
  const { openHelp } = useHelp()
  return (
    <button type="button" className="info-link" aria-label={`Help: ${label}`} title={`Help: ${label}`}
      onClick={(e) => { e.preventDefault(); e.stopPropagation(); openHelp(slug, anchor) }}>ⓘ</button>
  )
}
