// One definition per metric, used by every view so labels, units and "better" never drift.
export const METRICS = {
  coverage_pct: { label: 'Jobs covered', short: 'Jobs', unit: '%', better: 'max' },
  critical_coverage_pct: { label: 'Bottleneck downs covered', short: 'Bottleneck', unit: '%', better: 'max' },
  priority_weighted_coverage_pct: { label: 'Priority-weighted coverage', unit: '%', better: 'max' },
  mean_response_min: { label: 'Response to tool-downs', short: 'Response', unit: 'min', better: 'min' },
  walk_m_per_job: { label: 'Walking per job', unit: 'm', better: 'min' },
  wait_min_total: { label: 'Idle wait, all engineers', unit: 'min', better: 'min' },
  overqualification_levels: { label: 'Over-qualification', unit: 'levels', better: 'min' },
  utilization_pct: { label: 'Engineer utilisation', unit: '%', better: 'max' },
  workload_std: { label: 'Workload spread (std)', unit: 'jobs', better: 'min' },
  objective: { label: 'Operating cost (objective)', short: 'Cost', unit: 'pts', better: 'min' },
  runtime_ms: { label: 'Solve time', unit: 'ms', better: 'min' },
}

export const ALGO_ORDER = ['greedy', 'hungarian', 'regret', 'alns', 'pyvrp']
export const ALGO_SHORT = { greedy: 'Greedy', hungarian: 'Hungarian', regret: 'Regret-2', alns: 'ALNS', pyvrp: 'PyVRP' }
export const ALGO_BLURB = {
  greedy: 'Jobs in priority → deadline order; each takes the cheapest engineer. Never revisits a choice.',
  hungarian: 'Optimal engineer × job matching per round (Kuhn–Munkres), repeated until no feasible pair is left.',
  regret: 'Places the job with most to lose first (largest best-vs-second-best gap). Protects scarce certifications.',
  alns: 'Adaptive large neighbourhood search: destroy and repair the plan hundreds of times, keeping what works. Optimises the exact objective, incl. balance.',
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
