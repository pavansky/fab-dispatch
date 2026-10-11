// One definition per metric, used by every view so labels, units and "better" never drift.
export const METRICS = {
  coverage_pct: { label: 'Jobs covered', short: 'Jobs', unit: '%', better: 'max' },
  critical_coverage_pct: {
    label: 'Bottleneck downs covered', short: 'Bottleneck', unit: '%', better: 'max',
    // null from the API when the shift has no bottleneck downs: nothing to cover, so no rate.
    absent: 'no bottleneck downs',
  },
  priority_weighted_coverage_pct: { label: 'Priority-weighted coverage', unit: '%', better: 'max' },
  mean_response_min: {
    label: 'Response to tool-downs', short: 'Response', unit: 'min', better: 'min',
    help: 'Mean wait from report to start, over the tool-downs this plan serves. Unserved ones are not counted, so read it with coverage.',
    absent: 'no tool-downs served',
  },
  response_p95_min: {
    label: 'Response to tool-downs, p95', short: 'Response p95', unit: 'min', better: 'min',
    help: '95th percentile of the wait from report to start, over the tool-downs this plan serves.',
    absent: 'no tool-downs served',
  },
  unserved_downs: { label: 'Tool-downs left unserved', short: 'Unserved downs', unit: '', better: 'min' },
  walk_m_per_job: { label: 'Walking per job', unit: 'm', better: 'min' },
  wait_min_total: { label: 'Idle wait, all engineers', unit: 'min', better: 'min' },
  overqualification_levels: { label: 'Over-qualification', unit: 'levels', better: 'min' },
  utilization_pct: { label: 'Engineer utilisation', unit: '%', better: 'max' },
  workload_std: { label: 'Workload spread (std)', unit: 'jobs', better: 'min' },
  workload_minutes_std: { label: 'Workload spread (min)', short: 'Workload', unit: 'min', better: 'min', help: 'Standard deviation of busy minutes across engineers.' },
  objective: {
    label: 'Total cost (objective)', short: 'Cost', unit: 'pts', better: 'min',
    help: 'What every strategy minimises: operating cost plus the workload-balance term.',
  },
  operating_cost: {
    label: 'Operating cost', short: 'Operating', unit: 'pts', better: 'min',
    help: 'Walking, idle wait, over-qualification and the penalty for unserved priority work.',
  },
  workload_cost: {
    label: 'Workload-balance cost', short: 'Balance', unit: 'pts', better: 'min',
    help: 'The workload-balance part of the total cost.',
  },
  runtime_ms: { label: 'Solve time', unit: 'ms', better: 'min' },
}

export const ALGO_ORDER = ['greedy', 'hungarian', 'regret', 'alns', 'pyvrp']
export const ALGO_SHORT = { greedy: 'Greedy', hungarian: 'Hungarian', regret: 'Regret-2', alns: 'ALNS', pyvrp: 'PyVRP' }
export const ALGO_BLURB = {
  greedy: 'Jobs in priority → deadline order; each takes the cheapest engineer. Never revisits a choice.',
  hungarian: 'Optimal engineer × job matching per round (Kuhn–Munkres), repeated until no feasible pair is left.',
  regret: 'Places the job with most to lose first (largest best-vs-second-best gap). Protects scarce certifications.',
  alns: 'Adaptive large neighbourhood search: destroy and repair the plan hundreds of times, keeping what works. Searches on the total cost directly, workload balance included.',
  pyvrp: 'State-of-the-art iterated local search (PyVRP, C++ core). Searches tens of thousands of route changes per second.',
}

export const ALGO_KIND = { greedy: 'Constructive', hungarian: 'Assignment', regret: 'Constructive', alns: 'Metaheuristic', pyvrp: 'Metaheuristic' }

/** A metric that is a number; null, undefined and NaN (not reported, or nothing to measure) are "absent". */
export const hasMetric = (m, key) => Number.isFinite(m?.[key])

/** What to show for a metric with no value: the metric's own reason, or "n/a". */
export const absentText = (key) => METRICS[key]?.absent ?? 'n/a'

/** The best value on `key` among results that have one; undefined when none does. */
export function bestOf(results, key) {
  const vals = results.map((r) => r.metrics[key]).filter(Number.isFinite)
  if (!vals.length) return undefined
  return METRICS[key].better === 'max' ? Math.max(...vals) : Math.min(...vals)
}

/** Signed improvement of `value` over `base`: positive is always "better"; NaN when either is absent. */
export function improvement(key, value, base) {
  if (!Number.isFinite(value) || !Number.isFinite(base)) return NaN
  const d = value - base
  return METRICS[key].better === 'max' ? d : -d
}

/**
 * The workload-spread metric to show: minutes (`workload_minutes_std`) when every result
 * reports it, else the older jobs-based `workload_std` (older API responses and fixtures).
 */
export function workloadKey(results) {
  return results.length > 0 && results.every((r) => hasMetric(r.metrics, 'workload_minutes_std')) ? 'workload_minutes_std' : 'workload_std'
}

/**
 * How the total cost splits, when the API reports it (older responses only carry the
 * total). `other` is whatever the named parts don't cover, e.g. live-dispatch stability.
 */
export function costSplit(m) {
  if (typeof m?.operating_cost !== 'number' || typeof m?.objective !== 'number') return null
  const workload = typeof m.workload_cost === 'number' ? m.workload_cost : null
  const rest = m.objective - m.operating_cost - (workload ?? 0)
  return { operating: m.operating_cost, workload, other: Math.abs(rest) >= 0.05 ? rest : 0 }
}

/** Metric keys every result reports (new keys are optional while older API responses exist). */
export function presentKeys(results, keys) {
  return keys.filter((k) => results.length > 0 && results.every((r) => typeof r.metrics[k] === 'number'))
}
