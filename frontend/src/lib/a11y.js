// Keyboard activation for elements that act like buttons (Enter and Space, as a native button).
export const onActivateKey = (fn) => (e) => {
  if (e.key !== 'Enter' && e.key !== ' ') return
  e.preventDefault()
  fn()
}
