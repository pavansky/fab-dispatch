// Renders the PNG brand assets in public/ (app icons and the link-preview card) from HTML,
// so they always match the CSS brand mark. Run after changing the logo: npm run brand
import { chromium } from '@playwright/test'

const INK = '#020202', SIGNAL = '#ef6f2e', PAGE = '#f5f5f5'

// The mark: a rounded ink tile with a signal-orange square (same proportions as .brand-mark).
const mark = (size, radius) => `<div style="width:${size}px;height:${size}px;border-radius:${radius}px;background:${INK};display:grid;place-items:center">
  <div style="width:${size * 0.375}px;height:${size * 0.375}px;border-radius:${size * 0.05}px;background:${SIGNAL}"></div></div>`

const icon = (size, { maskable = false } = {}) => `<body style="margin:0;background:${maskable ? INK : 'transparent'};display:grid;place-items:center;width:${size}px;height:${size}px">
  ${maskable ? `<div style="width:${size * 0.3}px;height:${size * 0.3}px;border-radius:${size * 0.03}px;background:${SIGNAL}"></div>` : mark(size, size * 0.16)}</body>`

// Link preview (Open Graph): what LinkedIn, Slack and email show when the URL is shared.
const og = `<html><head><link href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600&family=Geist+Mono:wght@500&display=swap" rel="stylesheet"></head>
<body style="margin:0;width:1200px;height:630px;background:${PAGE};font-family:Geist,system-ui,sans-serif;color:${INK};
  background-image:linear-gradient(rgba(2,2,2,.05) 1px,transparent 1px),linear-gradient(90deg,rgba(2,2,2,.05) 1px,transparent 1px);background-size:40px 40px">
  <div style="position:absolute;inset:56px 64px;display:flex;flex-direction:column">
    <div style="display:flex;align-items:center;gap:16px;font:500 22px 'Geist Mono',monospace;letter-spacing:.06em;text-transform:uppercase">${mark(44, 7)}Fab Dispatch</div>
    <div style="margin-top:56px;font-size:64px;font-weight:600;letter-spacing:-.035em;line-height:1.02;max-width:760px">The right engineer to every tool-down, in real time.</div>
    <div style="margin-top:26px;font-size:26px;color:#4d4947;max-width:720px;line-height:1.35">Five allocation strategies compared live, from greedy to PyVRP, with every decision explained.</div>
    <div style="margin-top:auto;display:flex;gap:12px;font:500 17px 'Geist Mono',monospace;text-transform:uppercase;letter-spacing:.04em">
      ${['Semiconductor fabs', 'Live dispatch', 'Grounded assistant'].map((t, i) => `<span style="padding:9px 14px;border:1px solid ${i === 0 ? SIGNAL : '#ccc9c7'};border-radius:3px;background:#fff;color:${i === 0 ? '#b8460c' : INK}">${t}</span>`).join('')}
    </div>
  </div>
  <svg style="position:absolute;right:64px;top:150px" width="300" height="300" viewBox="0 0 300 300">
    <g stroke="#ccc9c7" stroke-dasharray="3 5"><line x1="20" y1="20" x2="20" y2="280"/><line x1="20" y1="280" x2="290" y2="280"/></g>
    <polyline points="40,80 110,130 210,175 255,232" fill="none" stroke="${INK}" stroke-width="2.5"/>
    <circle cx="40" cy="80" r="7" fill="${INK}"/><circle cx="110" cy="130" r="7" fill="${INK}"/><circle cx="210" cy="175" r="7" fill="${INK}"/>
    <circle cx="160" cy="40" r="7" fill="none" stroke="${INK}" stroke-width="2.5"/>
    <circle cx="255" cy="232" r="16" fill="none" stroke="${SIGNAL}" stroke-width="2" stroke-dasharray="3 3"/><circle cx="255" cy="232" r="9" fill="${SIGNAL}"/>
  </svg>
</body></html>`

const browser = await chromium.launch()
const shots = [
  ['public/apple-touch-icon.png', icon(180), 180, 180],
  ['public/icon-192.png', icon(192), 192, 192],
  ['public/icon-512.png', icon(512), 512, 512],
  ['public/icon-512-maskable.png', icon(512, { maskable: true }), 512, 512],
  ['public/og.png', og, 1200, 630],
]
for (const [path, html, width, height] of shots) {
  const page = await browser.newPage({ viewport: { width, height } })
  await page.setContent(html, { waitUntil: 'networkidle' })
  await page.screenshot({ path, omitBackground: path.includes('icon') && !path.includes('maskable') })
  await page.close()
  console.log('wrote', path)
}
await browser.close()
