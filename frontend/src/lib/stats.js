// Paired bootstrap for "is A really better than B across these shifts?" Deterministic
// (seeded RNG), so the same benchmark always shows the same intervals.

function mulberry32(seed) {
  return () => {
    seed |= 0; seed = (seed + 0x6d2b79f5) | 0
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

export const mean = (xs) => xs.reduce((a, b) => a + b, 0) / (xs.length || 1)

/** 95% CI of mean(a_i - b_i) over paired samples (same seed, two strategies). */
export function pairedBootstrapCI(a, b, { iterations = 2000, seed = 7 } = {}) {
  const d = a.map((x, i) => x - b[i])
  const rnd = mulberry32(seed)
  const means = []
  for (let k = 0; k < iterations; k++) {
    let s = 0
    for (let i = 0; i < d.length; i++) s += d[Math.floor(rnd() * d.length)]
    means.push(s / d.length)
  }
  means.sort((x, y) => x - y)
  return { mean: mean(d), lo: means[Math.floor(0.025 * iterations)], hi: means[Math.ceil(0.975 * iterations) - 1] }
}

/** Mean with a bootstrap 95% CI. */
export function bootstrapMeanCI(xs, opts) {
  return pairedBootstrapCI(xs, xs.map(() => 0), opts)
}
