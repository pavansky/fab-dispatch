// One definition per metric, used by every view so labels, units and "better" never drift.
export const METRICS = {
  coverage_pct: { label: 'Jobs covered', unit: '%', better: 'max' },
  critical_coverage_pct: { label: 'Bottleneck downs covered', unit: '%', better: 'max' },
  priority_weighted_coverage_pct: { label: 'Priority-weighted coverage', unit: '%', better: 'max' },
  mean_response_min: { label: 'Response to tool-downs', unit: 'min', better: 'min' },
  walk_m_per_job: { label: 'Walking per job', unit: 'm', better: 'min' },
  wait_min_total: { label: 'Idle wait, all engineers', unit: 'min', better: 'min' },
  overqualification_levels: { label: 'Over-qualification', unit: 'levels', better: 'min' },
  utilization_pct: { label: 'Engineer utilisation', unit: '%', better: 'max' },
  workload_std: { label: 'Workload spread (std)', unit: 'jobs', better: 'min' },
  objective: { label: 'Operating cost (objective)', unit: 'pts', better: 'min' },
  runtime_ms: { label: 'Solve time', unit: 'ms', better: 'min' },
}

export const ALGO_ORDER = ['greedy', 'hungarian', 'regret']
export const ALGO_SHORT = { greedy: 'Greedy', hungarian: 'Hungarian', regret: 'Regret-2' }
export const ALGO_BLURB = {
  greedy: 'Jobs in priority → deadline order; each takes the cheapest engineer. Never revisits a choice.',
  hungarian: 'Optimal engineer × job matching per round (Kuhn–Munkres), repeated until no feasible pair is left.',
  regret: 'Places the job with most to lose first (largest best-vs-second-best gap). Protects scarce certifications.',
}

export function bestOf(results, key) {
  const vals = results.map((r) => r.metrics[key])
  return METRICS[key].better === 'max' ? Math.max(...vals) : Math.min(...vals)
}

/** Signed improvement of `value` over `base`: positive is always "better". */
export function improvement(key, value, base) {
  const d = value - base
  return METRICS[key].better === 'max' ? d : -d
}
