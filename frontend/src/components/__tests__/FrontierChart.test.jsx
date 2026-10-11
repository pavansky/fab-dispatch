import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import FrontierChart from '../FrontierChart.jsx'

const pt = (key, cost, latency, extra = {}) => ({ key, cost, latency, front: false, reco: false, ...extra })
const circleOf = (container, label) => {
  const g = [...container.querySelectorAll('svg.frontier g')].find((el) => el.querySelector('text.lbl')?.textContent === label)
  return g.querySelector('circle.pt')
}

describe('FrontierChart', () => {
  it('anchors the one-sided noise band on the plan it was measured from', () => {
    // Greedy is cheaper but was excluded by the coverage guard; the band starts at Regret-2.
    const points = [pt('greedy', 400, 2, { front: true }), pt('regret', 500, 6), pt('pyvrp', 505, 400)]
    const { container } = render(<FrontierChart points={points} band={{ from: 500, margin: 10 }} />)
    const band = container.querySelector('rect.band')
    const bottom = Number(band.getAttribute('y')) + Number(band.getAttribute('height'))
    expect(bottom).toBeCloseTo(Number(circleOf(container, 'Regret-2').getAttribute('cy')), 5)
    expect(bottom).not.toBeCloseTo(Number(circleOf(container, 'Greedy').getAttribute('cy')), 0)
  })

  it('draws no band unless one is given', () => {
    const { container } = render(<FrontierChart points={[pt('greedy', 400, 2, { front: true })]} />)
    expect(container.querySelector('rect.band')).toBeNull()
  })

  it('says "same cost, but slower" rather than "beaten on cost" when costs are equal', () => {
    const { container } = render(<FrontierChart points={[pt('regret', 500, 6, { front: true }), pt('pyvrp', 500, 400)]} />)
    expect(container.querySelector('text.lbl-note')).toHaveTextContent('same cost as Regret-2, but slower')
    expect(screen.queryByText(/beaten by/)).not.toBeInTheDocument()
  })

  it('gives screen readers the plotted data as a table', () => {
    render(<FrontierChart points={[pt('regret', 500, 6, { front: true, reco: true }), pt('pyvrp', 500, 400)]} band={{ from: 500, margin: 10 }} />)
    const table = screen.getByRole('table', { name: 'Total cost and solve time per strategy' })
    const rows = within(table).getAllByRole('row').slice(1)
    expect(rows.map((r) => r.textContent)).toEqual([
      'Regret-2 (recommended)5006on the frontier',
      'PyVRP500400same cost as Regret-2, but slower',
      'Noise margin: up to 10 pts above 500 pts counts as equally cheap.',
    ])
  })

  it('never draws the recommended point hollow or as "beaten"', () => {
    const points = [pt('greedy', 400, 2, { front: true }), pt('pyvrp', 500, 400, { reco: true, note: 'recommended: Greedy is cheaper or faster but covers less bottleneck or priority work' })]
    const { container } = render(<FrontierChart points={points} />)
    expect(screen.queryByText(/beaten by/)).not.toBeInTheDocument()
    expect(container.querySelector('line.beaten-link')).toBeNull()
    expect(circleOf(container, 'PyVRP')).toHaveClass('front', 'is-reco')
  })
})
