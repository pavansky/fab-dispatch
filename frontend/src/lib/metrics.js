// One definition per metric, used by every view so labels, units and "better" never drift.
export const METRICS = {
  coverage_pct: { label: 'Jobs covered', short: 'Jobs', unit: '%', better: 'max' },
  critical_coverage_pct: { label: 'Bottleneck downs covered', short: 'Bottleneck', unit: '%', better: 'max' },
  priority_weighted_coverage_pct: { label: 'Priority-weighted coverage', unit: '%', better: 'max' },
  mean_response_min: {
    label: 'Response to tool-downs', short: 'Response', unit: 'min', better: 'min',
    help: 'Mean wait from report to start, over the tool-downs this plan serves. Unserved ones are not counted, so read it with coverage.',
  },
  walk_m_per_job: { label: 'Walking per job', unit: 'm', better: 'min' },
  wait_min_total: { label: 'Idle wait, all engineers', unit: 'min', better: 'min' },
  overqualification_levels: { label: 'Over-qualification', unit: 'levels', better: 'min' },
  utilization_pct: { label: 'Engineer utilisation', unit: '%', better: 'max' },
  workload_std: { label: 'Workload spread (std)', unit: 'jobs', better: 'min' },
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

export function bestOf(results, key) {
  const vals = results.map((r) => r.metrics[key])
  return METRICS[key].better === 'max' ? Math.max(...vals) : Math.min(...vals)
}

/** Signed improvement of `value` over `base`: positive is always "better". */
export function improvement(key, value, base) {
  const d = value - base
  return METRICS[key].better === 'max' ? d : -d
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
