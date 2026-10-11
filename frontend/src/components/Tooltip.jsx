import { useCallback, useEffect, useId, useState } from 'react'

/**
 * One tooltip per chart. `show(event, content, key)` opens it next to the pointer, or under
 * the element on focus; `describedBy(key)` gives the trigger whose tip is open the tooltip's
 * id for aria-describedby, so what a mouse user reads on hover is what a keyboard user
 * hears on focus. Escape closes it (WCAG 1.4.13). It is never a live region: hover moves
 * would otherwise re-announce it on every pixel.
 */
export function useTooltip() {
  const id = useId()
  const [tip, setTip] = useState(null)
  const show = useCallback((evt, content, key = null) => {
    let x, y
    if (evt.type === 'focus' || typeof evt.clientX !== 'number') {
      const r = evt.currentTarget?.getBoundingClientRect?.() ?? { left: 0, bottom: 0 }
      x = r.left; y = r.bottom + 8
    } else {
      x = evt.clientX + 14; y = evt.clientY + 14
    }
    setTip({ x: Math.max(0, Math.min(x, window.innerWidth - 300)), y: Math.max(0, Math.min(y, window.innerHeight - 140)), content, key })
  }, [])
  const hide = useCallback(() => setTip(null), [])
  useEffect(() => {
    if (!tip) return
    const esc = (e) => { if (e.key === 'Escape') hide() }
    document.addEventListener('keydown', esc)
    return () => document.removeEventListener('keydown', esc)
  }, [tip, hide])
  const describedBy = useCallback((key) => (tip && key !== null && tip.key === key ? id : undefined), [tip, id])
  return { tip, show, hide, id, describedBy }
}

export function Tooltip({ tip, id }) {
  // Always in the DOM (hidden when empty), so an aria-describedby set a moment earlier never
  // points at nothing.
  return <div id={id} className="tooltip" role="tooltip" hidden={!tip} style={tip ? { left: tip.x, top: tip.y } : undefined}>{tip?.content}</div>
}
