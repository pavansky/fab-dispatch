// Mirrors the API's limits (routes/planning.py), so a bad size is caught here with a plain message
// instead of coming back as a raw validation error. Bigger runs are offline studies (ANALYSIS.md, Scale).
export const SIZE_FIELDS = [
  { key: 'seed', label: 'Seed', min: 0, max: 1_000_000 },
  { key: 'n_engineers', label: 'Engineers', min: 1, max: 60 },
  { key: 'n_jobs', label: 'Jobs', min: 1, max: 200 },
]

export function shiftSizeErrors(params) {
  const errors = {}
  for (const { key, label, min, max } of SIZE_FIELDS) {
    const v = params[key]
    if (!Number.isInteger(v) || v < min || v > max) {
      errors[key] = `${label} must be a whole number from ${min.toLocaleString()} to ${max.toLocaleString()} in the live demo.`
    }
  }
  return errors
}
