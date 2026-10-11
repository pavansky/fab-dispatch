import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import Sidebar from '../Sidebar.jsx'
import { shiftSizeErrors } from '../../shiftLimits.js'
import { fixtures } from '../../test/api.js'

const { fab1, fab2, meta } = fixtures
const params = { preset: 'normal', seed: 7, n_engineers: 14, n_jobs: 45 }

function renderSidebar(props = {}) {
  const handlers = {
    onClose: vi.fn(), setParams: vi.fn(), onGenerate: vi.fn(), setWeights: vi.fn(), setAddMode: vi.fn(),
    setNewJob: vi.fn(), onTogglePredicted: vi.fn(), onRestoreAll: vi.fn(),
  }
  render(<Sidebar open={false} profile={fab1} params={params} weights={meta.default_weights} defaultWeights={meta.default_weights}
    addMode={false} newJob={{ priority: 3, at: 120 }} predicted={null} offShiftCount={0} {...handlers} {...props} />)
  return handlers
}

describe('Sidebar', () => {
  it("lists the fab's own presets and describes the chosen one", () => {
    renderSidebar()
    const options = within(screen.getByRole('combobox', { name: 'Preset' })).getAllByRole('option')
    expect(options.map((o) => o.textContent)).toEqual(Object.values(fab1.presets).map((p) => p.label))
    expect(screen.getByText(fab1.presets.normal.description)).toBeInTheDocument()
  })

  it('shows a different fab’s presets from its profile', () => {
    renderSidebar({ profile: fab2 })
    expect(within(screen.getByRole('combobox', { name: 'Preset' })).getByRole('option', { name: 'Photo crunch' })).toBeInTheDocument()
  })

  it('generates a new shift as soon as a preset is picked, so results always match the preset shown', async () => {
    const { setParams, onGenerate } = renderSidebar()
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Preset' }), 'litho_crunch')
    expect(setParams).toHaveBeenCalledWith({ ...params, preset: 'litho_crunch' })
    expect(onGenerate).toHaveBeenCalledWith({ ...params, preset: 'litho_crunch' })
  })

  it('applies typed sizes only on Generate shift', async () => {
    const { setParams, onGenerate, onClose } = renderSidebar()
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Engineers' }), { target: { value: '20' } })
    expect(setParams).toHaveBeenLastCalledWith({ ...params, n_engineers: 20 })
    expect(onGenerate).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'Generate shift' }))
    expect(onGenerate).toHaveBeenCalledOnce()
    expect(onClose).toHaveBeenCalled() // closes the drawer on phones
  })

  it('has one slider per soft constraint, and a reset', async () => {
    const { setWeights } = renderSidebar()
    for (const name of ['Priority reward', 'Walking', 'Idle wait', 'Over-qualification', 'Workload balance']) {
      expect(screen.getByRole('slider', { name })).toBeInTheDocument()
    }
    fireEvent.change(screen.getByRole('slider', { name: 'Idle wait' }), { target: { value: '0.5' } })
    expect(setWeights).toHaveBeenLastCalledWith({ ...meta.default_weights, wait_min: 0.5 })
    await userEvent.click(screen.getByRole('button', { name: 'Reset to defaults' }))
    expect(setWeights).toHaveBeenLastCalledWith(meta.default_weights)
  })

  it('follows the thumb while dragging but commits the weight only when the drag ends', () => {
    const { setWeights } = renderSidebar()
    const slider = screen.getByRole('slider', { name: 'Walking' })
    fireEvent.input(slider, { target: { value: '4' } }) // mid-drag: what React's onChange sees per pixel
    fireEvent.input(slider, { target: { value: '6' } })
    expect(slider.closest('label')).toHaveTextContent('6')
    expect(setWeights).not.toHaveBeenCalled()
    fireEvent.pointerUp(slider)
    expect(setWeights).toHaveBeenCalledTimes(1)
    expect(setWeights).toHaveBeenLastCalledWith({ ...meta.default_weights, travel_100m: 6 })
    fireEvent.blur(slider) // the same value again is not a second commit
    expect(setWeights).toHaveBeenCalledTimes(1)
  })

  it('commits a keyboard step on key-up', () => {
    const { setWeights } = renderSidebar()
    const slider = screen.getByRole('slider', { name: 'Idle wait' })
    fireEvent.input(slider, { target: { value: '0.3' } })
    fireEvent.keyUp(slider, { key: 'ArrowRight' })
    expect(setWeights).toHaveBeenCalledWith({ ...meta.default_weights, wait_min: 0.3 })
  })

  it('offers to restore engineers taken off shift', async () => {
    const { onRestoreAll } = renderSidebar({ offShiftCount: 2 })
    await userEvent.click(screen.getByRole('button', { name: 'Restore all 2 engineers' }))
    expect(onRestoreAll).toHaveBeenCalledOnce()
  })

  it('closes as a drawer with Escape or the close button', async () => {
    const { onClose } = renderSidebar({ open: true })
    await userEvent.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalledTimes(1)
    await userEvent.click(screen.getByRole('button', { name: 'Close controls' }))
    expect(onClose).toHaveBeenCalledTimes(2)
  })
})
describe('shift size limits', () => {
  it('flags sizes outside the API limits', () => {
    expect(shiftSizeErrors({ seed: 100, n_engineers: 100, n_jobs: 1000 })).toEqual({
      n_engineers: 'Engineers must be a whole number from 1 to 60 in this deployment (FAB_MAX_ENGINEERS and FAB_MAX_JOBS raise it).',
      n_jobs: 'Jobs must be a whole number from 1 to 200 in this deployment (FAB_MAX_ENGINEERS and FAB_MAX_JOBS raise it).',
    })
    expect(shiftSizeErrors({ seed: 7, n_engineers: 14, n_jobs: 45 })).toEqual({})
    // The ceiling comes from the deployment (/api/meta limits): a local run can raise it to 1000 x 1000.
    expect(shiftSizeErrors({ seed: 7, n_engineers: 1000, n_jobs: 1000 }, { max_engineers: 1000, max_jobs: 1000 })).toEqual({})
    expect(shiftSizeErrors({ seed: 7, n_engineers: 1001, n_jobs: 1000 }, { max_engineers: 1000, max_jobs: 1000 })).toHaveProperty('n_engineers')
    expect(shiftSizeErrors({ seed: 7, n_engineers: 0, n_jobs: 4.5 })).toHaveProperty('n_jobs')
  })
})
