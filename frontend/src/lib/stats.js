// Paired comparisons for "is A really costlier than B across these shifts?".
//
// The benchmark runs every strategy on the same seeded shifts, so the right test is on the
// per-shift differences (paired). Two interval methods:
//  - Student t on the differences: exact under normal differences and honest at the small n
//    the UI offers (5, 10, 20 shifts), where a percentile bootstrap under-covers (84% real
//    coverage at n = 5 for a nominal 95%).
//  - Percentile bootstrap, deterministic (seeded RNG): kept for n ≥ 30, where it needs no
//    distributional assumption and has enough resamples to be stable.
// Several comparisons in one run (every other strategy against the cheapest, per preset) are
// Holm-adjusted, so a benchmark of identical strategies calls one "costlier" at most 5% of
// the time, not 46% per preset.

function mulberry32(seed) {
  return () => {
    seed |= 0; seed = (seed + 0x6d2b79f5) | 0
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

export const mean = (xs) => xs.reduce((a, b) => a + b, 0) / (xs.length || 1)

/** Pairs where both sides are finite numbers: a run that failed for one strategy drops that shift. */
export function pairedDifferences(a, b) {
  const d = []
  for (let i = 0; i < Math.min(a.length, b.length); i++) {
    if (Number.isFinite(a[i]) && Number.isFinite(b[i])) d.push(a[i] - b[i])
  }
  return d
}

/** Percentile bootstrap interval of mean(a_i - b_i) over paired samples (same seed, two strategies). */
export function pairedBootstrapCI(a, b, { iterations = 2000, seed = 7, alpha = 0.05 } = {}) {
  const d = pairedDifferences(a, b)
  if (d.length === 0) return { mean: NaN, lo: NaN, hi: NaN, n: 0, p: NaN, method: 'bootstrap' }
  const rnd = mulberry32(seed)
  const means = []
  for (let k = 0; k < iterations; k++) {
    let s = 0
    for (let i = 0; i < d.length; i++) s += d[Math.floor(rnd() * d.length)]
    means.push(s / d.length)
  }
  means.sort((x, y) => x - y)
  const lo = means[Math.max(0, Math.floor((alpha / 2) * iterations))]
  const hi = means[Math.min(iterations - 1, Math.ceil((1 - alpha / 2) * iterations) - 1)]
  // Bootstrap p-value: twice the smaller tail mass on the other side of zero.
  const below = means.filter((m) => m < 0).length / iterations
  const p = Math.min(1, 2 * Math.min(below, 1 - below))
  return { mean: mean(d), lo, hi, n: d.length, p, method: 'bootstrap' }
}

/** Mean with a bootstrap 95% CI (unpaired: one sample's own mean). */
export function bootstrapMeanCI(xs, opts) {
  return pairedBootstrapCI(xs, xs.map(() => 0), opts)
}

// ------------------------------------------------------------------ Student t
// Regularised incomplete beta I_x(a, b) by continued fraction (Numerical Recipes, betacf).
function logGamma(x) {
  const c = [76.18009172947146, -86.50532032941678, 24.01409824083091, -1.231739572450155, 0.001208650973866179, -0.000005395239384953]
  let y = x, tmp = x + 5.5
  tmp -= (x + 0.5) * Math.log(tmp)
  let ser = 1.000000000190015
  for (const cj of c) ser += cj / ++y
  return -tmp + Math.log((2.5066282746310007 * ser) / x)
}
function betacf(a, b, x) {
  const MAXIT = 300, EPS = 3e-14, FPMIN = 1e-300
  const qab = a + b, qap = a + 1, qam = a - 1
  let c = 1, d = 1 - (qab * x) / qap
  if (Math.abs(d) < FPMIN) d = FPMIN
  d = 1 / d
  let h = d
  for (let m = 1; m <= MAXIT; m++) {
    const m2 = 2 * m
    let aa = (m * (b - m) * x) / ((qam + m2) * (a + m2))
    d = 1 + aa * d; if (Math.abs(d) < FPMIN) d = FPMIN
    c = 1 + aa / c; if (Math.abs(c) < FPMIN) c = FPMIN
    d = 1 / d; h *= d * c
    aa = (-(a + m) * (qab + m) * x) / ((a + m2) * (qap + m2))
    d = 1 + aa * d; if (Math.abs(d) < FPMIN) d = FPMIN
    c = 1 + aa / c; if (Math.abs(c) < FPMIN) c = FPMIN
    d = 1 / d
    const del = d * c
    h *= del
    if (Math.abs(del - 1) < EPS) break
  }
  return h
}
function incBeta(a, b, x) {
  if (x <= 0) return 0
  if (x >= 1) return 1
  const bt = Math.exp(logGamma(a + b) - logGamma(a) - logGamma(b) + a * Math.log(x) + b * Math.log(1 - x))
  return x < (a + 1) / (a + b + 2) ? (bt * betacf(a, b, x)) / a : 1 - (bt * betacf(b, a, 1 - x)) / b
}

/** P(T ≤ t) for Student's t with `df` degrees of freedom. */
export function tCDF(t, df) {
  if (!Number.isFinite(t)) return t > 0 ? 1 : 0
  const x = df / (df + t * t)
  const tail = 0.5 * incBeta(df / 2, 0.5, x)
  return t >= 0 ? 1 - tail : tail
}

/** t such that P(T ≤ t) = p (bisection; the CDF is monotone). */
export function tQuantile(p, df) {
  if (p <= 0) return -Infinity
  if (p >= 1) return Infinity
  if (p === 0.5) return 0
  let lo = -1, hi = 1
  while (tCDF(lo, df) > p) lo *= 2
  while (tCDF(hi, df) < p) hi *= 2
  for (let i = 0; i < 200 && hi - lo > 1e-12; i++) {
    const mid = (lo + hi) / 2
    if (tCDF(mid, df) < p) lo = mid; else hi = mid
  }
  return (lo + hi) / 2
}

/** Two-sided p-value of a t statistic. */
const tPValue = (t, df) => (Number.isNaN(t) ? NaN : Math.min(1, 2 * (1 - tCDF(Math.abs(t), df))))

/**
 * Student t interval of mean(a_i - b_i) over paired samples, with the two-sided p-value of
 * the paired t-test (H0: no mean difference). `alpha` sets the interval's level, so a
 * Holm-adjusted level gives an interval that excludes 0 exactly when Holm rejects.
 */
export function pairedTCI(a, b, { alpha = 0.05 } = {}) {
  const d = pairedDifferences(a, b)
  const n = d.length
  if (n < 2) return { mean: n ? d[0] : NaN, lo: NaN, hi: NaN, n, p: NaN, df: Math.max(0, n - 1), method: 't' }
  const m = mean(d)
  const sd = Math.sqrt(d.reduce((s, x) => s + (x - m) ** 2, 0) / (n - 1))
  const se = sd / Math.sqrt(n)
  const df = n - 1
  const t = se === 0 ? (m === 0 ? 0 : Infinity) : m / se
  const q = tQuantile(1 - alpha / 2, df)
  return { mean: m, lo: m - q * se, hi: m + q * se, n, p: se === 0 ? (m === 0 ? 1 : 0) : tPValue(t, df), df, method: 't' }
}

/**
 * Welch (unpaired) t interval of mean(a) - mean(b). Ignores the pairing, so with shifts that
 * vary more than the strategies do, it is far wider than the paired one: that spread is the
 * shifts', not the strategies'. Here for comparison; the verdicts never use it.
 */
export function unpairedTCI(a, b, { alpha = 0.05 } = {}) {
  const xs = a.filter(Number.isFinite), ys = b.filter(Number.isFinite)
  if (xs.length < 2 || ys.length < 2) return { mean: NaN, lo: NaN, hi: NaN, p: NaN, method: 'welch' }
  const mx = mean(xs), my = mean(ys)
  const vx = xs.reduce((s, x) => s + (x - mx) ** 2, 0) / (xs.length - 1)
  const vy = ys.reduce((s, y) => s + (y - my) ** 2, 0) / (ys.length - 1)
  const se = Math.sqrt(vx / xs.length + vy / ys.length)
  const df = se === 0 ? xs.length + ys.length - 2
    : (vx / xs.length + vy / ys.length) ** 2 / ((vx / xs.length) ** 2 / (xs.length - 1) + (vy / ys.length) ** 2 / (ys.length - 1))
  const m = mx - my
  const q = tQuantile(1 - alpha / 2, df)
  return { mean: m, lo: m - q * se, hi: m + q * se, p: se === 0 ? (m === 0 ? 1 : 0) : tPValue(m / se, df), df, method: 'welch' }
}

/**
 * Paired interval for the benchmark: Student t below `bootstrapFrom` pairs (better coverage at
 * small n), percentile bootstrap from there on.
 */
export function pairedCI(a, b, { alpha = 0.05, bootstrapFrom = 30, ...rest } = {}) {
  const n = pairedDifferences(a, b).length
  return n >= bootstrapFrom ? pairedBootstrapCI(a, b, { alpha, ...rest }) : pairedTCI(a, b, { alpha })
}

/**
 * Holm's step-down adjustment for `m` comparisons tested together. Returns, per comparison:
 * whether it is rejected at family-wise level `alpha`, the adjusted p-value, and the level
 * the comparison was tested at (alpha / (m - rank + 1) while rejecting, then the level of the
 * first non-rejection for the rest). An interval built at that level excludes 0 exactly when
 * Holm rejects, so the table's intervals and verdicts agree. NaN p-values (no data) are
 * never rejected and do not count towards m.
 */
export function holm(pValues, { alpha = 0.05 } = {}) {
  const idx = pValues.map((p, i) => i).filter((i) => Number.isFinite(pValues[i])).sort((i, j) => pValues[i] - pValues[j])
  const m = idx.length
  const reject = pValues.map(() => false)
  const adjusted = pValues.map(() => NaN)
  const level = pValues.map(() => alpha)
  let running = 0
  let stopped = null
  idx.forEach((i, k) => {
    const factor = m - k
    running = Math.max(running, Math.min(1, factor * pValues[i]))
    adjusted[i] = running
    if (stopped === null && pValues[i] <= alpha / factor) {
      reject[i] = true
      level[i] = alpha / factor
    } else {
      if (stopped === null) stopped = alpha / factor
      level[i] = stopped
    }
  })
  return { reject, adjusted, level, m }
}
