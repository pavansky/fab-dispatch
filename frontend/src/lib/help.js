import { createContext, useContext } from 'react'

// Lets any control open the help center at an article (and section) without prop drilling.
export const HelpContext = createContext({ openHelp: () => {}, openAssistant: () => {} })
export const useHelp = () => useContext(HelpContext)

export const TOUR_KEY = 'fab-dispatch-tour'

/** "slug#anchor" -> { slug, anchor } */
export function parseHelpTarget(target = '') {
  const [slug, anchor = ''] = target.replace(/^help:/, '').split('#')
  return { slug, anchor }
}
