import { describe, expect, it } from 'vitest'
import { durationsById, liveJobId, responseTargets, withDurations } from '../scenario.js'
import { fixtures } from '../../test/api.js'

const { fab1, scenario } = fixtures

describe('responseTargets', () => {
  it("prefers the preset's own targets from the profile", () => {
    const profile = { presets: { excursion: { sla_critical: 25, sla_down: 60 } } }
    expect(responseTargets(profile, 'excursion', scenario)).toEqual({ 3: 25, 2: 60, 1: 240 })
  })
  it('falls back to the windows the shift was generated with', () => {
    const jobs = [
      { priority: 3, earliest: 10, latest: 50 }, { priority: 3, earliest: 0, latest: 40 }, { priority: 3, earliest: 5, latest: 50 },
      { priority: 2, earliest: 0, latest: 150 },
    ]
    expect(responseTargets(fab1, 'normal', { jobs })).toEqual({ 3: 40, 2: 150, 1: 240 })
  })
  it('uses the generic defaults when neither says', () => {
    expect(responseTargets(null, undefined, { jobs: [] })).toEqual({ 3: 45, 2: 120, 1: 240 })
  })
})

describe('durations', () => {
  it('applies durations by job id, leaving other jobs and the job list alone', () => {
    const standard = durationsById(scenario)
    const predicted = withDurations(scenario, { [scenario.jobs[0].id]: 999 })
    const reported = { ...predicted, jobs: [...predicted.jobs, { ...scenario.jobs[1], id: 'J900', duration: 75 }] }
    const restored = withDurations(reported, standard)
    expect(restored.jobs).toHaveLength(scenario.jobs.length + 1)
    expect(restored.jobs[0].duration).toBe(scenario.jobs[0].duration)
    expect(restored.jobs.at(-1)).toMatchObject({ id: 'J900', duration: 75 })
    expect(restored.jobs.slice(1, -1)).toEqual(scenario.jobs.slice(1))
  })
})

describe('liveJobId', () => {
  it('differs between two dispatchers reporting in the same millisecond', () => {
    const now = 1_760_000_000_000
    let i = 0
    const rand = () => (i++ % 50) / 50
    const ids = new Set(Array.from({ length: 50 }, () => liveJobId(now, rand)))
    expect(ids.size).toBe(50)
    expect([...ids].every((id) => /^L[0-9A-Z]{9}$/.test(id))).toBe(true)
    expect(liveJobId(now, rand)).not.toBe(liveJobId(now + 1, rand))
  })
})
