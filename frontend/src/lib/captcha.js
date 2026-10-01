// Cloudflare Turnstile, loaded only when the API reports a site key (CAPTCHA on in Supabase).
const SCRIPT = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit'
let loading = null

export function loadTurnstile() {
  if (window.turnstile) return Promise.resolve(window.turnstile)
  loading ??= new Promise((resolve, reject) => {
    const s = document.createElement('script')
    s.src = SCRIPT
    s.async = true
    s.onload = () => (window.turnstile ? resolve(window.turnstile) : reject(new Error('CAPTCHA failed to load')))
    s.onerror = () => { loading = null; reject(new Error("Couldn't load the CAPTCHA. Check your connection and retry.")) }
    document.head.appendChild(s)
  })
  return loading
}
