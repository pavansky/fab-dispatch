// Mirrors the API's limits so a bad size is caught here with a plain message instead of coming
// back as a raw validation error. The ceiling is the deployment's (FAB_MAX_ENGINEERS and
// FAB_MAX_JOBS, read from /api/meta); the hosted demo keeps 60 x 200 so a request fits its 60 s
// function limit, a local run can raise both and plan 1000 x 1000 (ANALYSIS.md, Scale).
export const DEFAULT_LIMITS = { max_engineers: 60, max_jobs: 200 }

export function sizeFields(limits = DEFAULT_LIMITS) {
  const { max_engineers, max_jobs } = { ...DEFAULT_LIMITS, ...(limits ?? {}) }
  return [
    { key: 'seed', label: 'Seed', min: 0, max: 1_000_000 },
    { key: 'n_engineers', label: 'Engineers', min: 1, max: max_engineers },
    { key: 'n_jobs', label: 'Jobs', min: 1, max: max_jobs },
  ]
}

export function shiftSizeErrors(params, limits = DEFAULT_LIMITS) {
  const errors = {}
  for (const { key, label, min, max } of sizeFields(limits)) {
    const v = params[key]
    if (!Number.isInteger(v) || v < min || v > max) {
      errors[key] = `${label} must be a whole number from ${min.toLocaleString()} to ${max.toLocaleString()} in this deployment`
        + (key === 'seed' ? '.' : ' (FAB_MAX_ENGINEERS and FAB_MAX_JOBS raise it).')
    }
  }
  return errors
}
