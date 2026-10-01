import { useCallback, useState } from 'react'

export function useTooltip() {
  const [tip, setTip] = useState(null)
  const show = useCallback((evt, content) => {
    const x = Math.min(evt.clientX + 14, window.innerWidth - 300)
    const y = Math.min(evt.clientY + 14, window.innerHeight - 140)
    setTip({ x, y, content })
  }, [])
  const hide = useCallback(() => setTip(null), [])
  return { tip, show, hide }
}

export function Tooltip({ tip }) {
  if (!tip) return null
  return <div className="tooltip" style={{ left: tip.x, top: tip.y }} role="status">{tip.content}</div>
}
