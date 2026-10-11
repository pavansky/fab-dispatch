// Small, pure helpers over a scenario (shift), shared by the planning and live views.

const DEFAULT_TARGETS = { 3: 45, 2: 120, 1: 240 }
const positive = (v) => (typeof v === 'number' && v > 0 ? v : undefined)

/** The most common start window (latest - earliest) per priority among these jobs. */
function windowsOf(jobs) {
  const counts = {}
  for (const j of jobs) {
    const w = j.latest - j.earliest
    if (!(w > 0)) continue
    const c = (counts[j.priority] ??= {})
    c[w] = (c[w] ?? 0) + 1
  }
  return Object.fromEntries(Object.entries(counts).map(([p, c]) => [p, Number(Object.entries(c).sort((a, b) => b[1] - a[1] || a[0] - b[0])[0][0])]))
}

/**
 * Response targets in minutes (report to latest start) for a job reported by hand, per
 * priority: 3 bottleneck down, 2 tool down, 1 PM. They differ by fab and preset, so they
 * come from the profile's preset when the API includes them (sla_critical, sla_down,
 * sla_pm), else from the shift itself (generated jobs of one priority share a window),
 * else the generic defaults.
 */
export function responseTargets(profile, preset, scenario) {
  const p = profile?.presets?.[preset] ?? {}
  const fromProfile = { 3: positive(p.sla_critical), 2: positive(p.sla_down), 1: positive(p.sla_pm) }
  const fromShift = windowsOf(scenario?.jobs ?? [])
  return Object.fromEntries([3, 2, 1].map((k) => [k, fromProfile[k] ?? fromShift[k] ?? DEFAULT_TARGETS[k]]))
}

/** The start window each priority has in this shift: { 3: 45, ... } (only priorities present). */
export const shiftWindows = (scenario) => windowsOf(scenario?.jobs ?? [])

/** { jobId: duration } for every job in the scenario. */
export function durationsById(scenario) {
  return Object.fromEntries(scenario.jobs.map((j) => [j.id, j.duration]))
}

/**
 * The scenario with these durations applied by job id. Jobs not in the map (reported after
 * the map was taken) keep theirs, and no job is added or removed.
 */
export function withDurations(scenario, byId) {
  return { ...scenario, jobs: scenario.jobs.map((j) => (byId[j.id] !== undefined && byId[j.id] !== j.duration ? { ...j, duration: byId[j.id] } : j)) }
}

/**
 * A job id for a live report that two dispatchers won't realistically both pick: time-based with a random
 * suffix (the backend accepts any string id, and rejects one that already exists).
 */
export function liveJobId(now = Date.now(), rand = Math.random) {
  return `L${now.toString(36).slice(-5).toUpperCase()}${Math.floor(rand() * 36 ** 4).toString(36).padStart(4, '0').toUpperCase()}`
}
