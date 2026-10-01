import { ALGO_ORDER, ALGO_SHORT, METRICS, improvement } from './metrics.js'
import { fmt } from './format.js'
import { familyIds } from './fab.js'

export const GOALS = {
  value: {
    label: 'Best value: cost × latency',
    help: 'Never trades away bottleneck coverage. Among plans within the noise margin of the cheapest, takes the fastest to compute. A slower solver has to earn its latency.',
    rank: ['objective', 'runtime_ms'],
  },
  bottleneck: {
    label: 'Protect bottleneck tools',
    help: 'Most bottleneck tool-downs covered, then the fastest response. Use when lost wafer moves dominate.',
    rank: ['critical_coverage_pct', 'mean_response_min', 'priority_weighted_coverage_pct'],
  },
  coverage: {
    label: 'Maximise coverage',
    help: 'Serve the most priority-weighted work, then the lowest cost. Use when backlog is the problem.',
    rank: ['priority_weighted_coverage_pct', 'coverage_pct', 'objective'],
  },
  cost: {
    label: 'Lowest operating cost',
    help: 'Lowest total walking, waiting, over-qualification and unserved-priority cost.',
    rank: ['objective', 'priority_weighted_coverage_pct'],
  },
}

// Differences smaller than this are treated as a tie when ranking.
const TIE = { critical_coverage_pct: 0.05, priority_weighted_coverage_pct: 0.05, coverage_pct: 0.05, mean_response_min: 0.25, objective: 0.5 }

/**
 * Cost differences smaller than this are treated as noise, not a win. On one shift,
 * re-sequencing a single job moves the objective by a few points, so a 1% "win" is
 * not evidence. Calling it one would be a false positive.
 */
export function costMargin(cheapest) {
  return Math.max(0.02 * Math.abs(cheapest), 5)
}

/** Strategies not beaten on both cost and latency by another (the efficient frontier). */
export function paretoFront(results) {
  return results.filter((r) => !results.some((o) => o !== r
    && o.metrics.objective <= r.metrics.objective && o.metrics.runtime_ms <= r.metrics.runtime_ms
    && (o.metrics.objective < r.metrics.objective || o.metrics.runtime_ms < r.metrics.runtime_ms)))
}

function recommendValue(results) {
  // 1. Guard: never give up bottleneck coverage or priority-weighted coverage for speed or cost.
  const bestCrit = Math.max(...results.map((r) => r.metrics.critical_coverage_pct))
  const bestPri = Math.max(...results.map((r) => r.metrics.priority_weighted_coverage_pct))
  const safe = results.filter((r) => r.metrics.critical_coverage_pct >= bestCrit - 1e-9
    && r.metrics.priority_weighted_coverage_pct >= bestPri - 0.5)
  const pool = safe.length ? safe : results
  // 2. Cheapest plan, and everything within the noise margin of it.
  const cheapest = pool.reduce((a, b) => (b.metrics.objective < a.metrics.objective ? b : a))
  const margin = costMargin(cheapest.metrics.objective)
  const nearTie = pool.filter((r) => r.metrics.objective <= cheapest.metrics.objective + margin)
  // 3. Among statistically indistinguishable plans, the fastest wins.
  const winner = nearTie.reduce((a, b) => (b.metrics.runtime_ms < a.metrics.runtime_ms ? b : a))
  const ranked = [winner, ...results.filter((r) => r !== winner).sort((a, b) => a.metrics.objective - b.metrics.objective)]
  const m = winner.metrics
  const excluded = results.filter((r) => !pool.includes(r))
  let why
  if (winner === cheapest) {
    const next = pool.filter((r) => r !== winner).sort((a, b) => a.metrics.objective - b.metrics.objective)[0]
    why = next
      ? `Cheapest plan by a real margin: ${fmt(m.objective)} pts, ${fmt(next.metrics.objective - m.objective)} pts (${Math.round(100 * (next.metrics.objective - m.objective) / next.metrics.objective)}%) below ${ALGO_SHORT[next.algorithm]}. That's worth its ${fmt(m.runtime_ms, 0)} ms solve.`
      : `Only strategy that keeps full bottleneck coverage.`
  } else {
    why = `${ALGO_SHORT[cheapest.algorithm]} is cheaper by only ${fmt(m.objective - cheapest.metrics.objective)} pts, inside the ${fmt(margin, 0)}-pt noise margin, so it isn't a real win. ${ALGO_SHORT[winner.algorithm]} gets an equivalent plan ${Math.max(1, Math.round(cheapest.metrics.runtime_ms / Math.max(m.runtime_ms, 0.1)))}× faster (${fmt(m.runtime_ms, 0)} ms vs ${fmt(cheapest.metrics.runtime_ms, 0)} ms).`
  }
  why += ` Covers ${m.assigned} of ${m.jobs} jobs, ${fmt(m.critical_coverage_pct)}% of bottleneck downs.`
  const tradeoff = []
  if (excluded.length) tradeoff.push(`Not considered because they serve less bottleneck or priority work: ${excluded.map((r) => ALGO_SHORT[r.algorithm]).join(', ')}`)
  const faster = pool.filter((r) => r.metrics.runtime_ms < m.runtime_ms && !nearTie.includes(r))
    .sort((a, b) => a.metrics.objective - b.metrics.objective)[0]
  if (faster) tradeoff.push(`${ALGO_SHORT[faster.algorithm]} answers in ${fmt(faster.metrics.runtime_ms, 0)} ms but costs ${fmt(faster.metrics.objective - m.objective)} pts more`)
  return { winner, ranked, why, tradeoff, margin, nearTie: nearTie.map((r) => r.algorithm) }
}

export function recommend(results, goalKey) {
  if (goalKey === 'value') return recommendValue(results)
  const goal = GOALS[goalKey]
  const sorted = [...results].sort((a, b) => {
    for (const key of goal.rank) {
      const diff = improvement(key, b.metrics[key], a.metrics[key])
      if (Math.abs(diff) > (TIE[key] ?? 0)) return diff
    }
    return ALGO_ORDER.indexOf(a.algorithm) - ALGO_ORDER.indexOf(b.algorithm)
  })
  const winner = sorted[0]
  const lead = goal.rank[0]
  const runnerUp = sorted[1]
  const m = winner.metrics
  const def = METRICS[lead]

  let why
  const leadDiff = runnerUp ? improvement(lead, m[lead], runnerUp.metrics[lead]) : 0
  if (runnerUp && Math.abs(leadDiff) > (TIE[lead] ?? 0)) {
    why = `Best ${def.label.toLowerCase()}: ${fmt(m[lead])} ${def.unit}, ${fmt(Math.abs(leadDiff))} ${def.unit} ahead of ${ALGO_SHORT[runnerUp.algorithm]}.`
  } else {
    const tiebreak = goal.rank.find((k) => runnerUp && Math.abs(improvement(k, m[k], runnerUp.metrics[k])) > (TIE[k] ?? 0))
    why = tiebreak
      ? `Ties on ${def.label.toLowerCase()} (${fmt(m[lead])} ${def.unit}) and wins on ${METRICS[tiebreak].label.toLowerCase()}: ${fmt(m[tiebreak])} ${METRICS[tiebreak].unit}.`
      : `All three strategies tie on this goal.`
  }
  why += ` Covers ${m.assigned} of ${m.jobs} jobs.`

  // The honest part: what you give up versus the best alternative on other KPIs.
  const tradeoffs = []
  for (const key of ['coverage_pct', 'critical_coverage_pct', 'mean_response_min', 'wait_min_total', 'objective']) {
    if (goal.rank[0] === key) continue
    let best = null
    for (const r of results) {
      if (r === winner) continue
      const gain = improvement(key, r.metrics[key], m[key])
      if (gain > (TIE[key] ?? 0.5) && (!best || gain > best.gain)) best = { r, gain }
    }
    if (best) tradeoffs.push({ key, algo: best.r.algorithm, gain: best.gain, rel: Math.abs(best.gain) / (Math.abs(m[key]) || 1) })
  }
  tradeoffs.sort((a, b) => b.rel - a.rel)
  const tradeoff = tradeoffs.slice(0, 2).map((t) => {
    const def2 = METRICS[t.key]
    const verb = def2.better === 'max' ? 'higher' : 'lower'
    return `${ALGO_SHORT[t.algo]} is ${fmt(t.gain)} ${def2.unit} ${verb} on ${def2.label.toLowerCase()}`
  })
  return { winner, ranked: sorted, why, tradeoff }
}

export function assignmentMap(result) {
  return Object.fromEntries(result.assignments.map((a) => [a.job_id, a.tech_id]))
}

/** Jobs where at least two algorithms disagree on who (or whether anyone) does the work. */
export function disagreements(results, jobs) {
  const maps = Object.fromEntries(results.map((r) => [r.algorithm, assignmentMap(r)]))
  return jobs
    .map((j) => {
      const who = Object.fromEntries(results.map((r) => [r.algorithm, maps[r.algorithm][j.id] ?? null]))
      const vals = Object.values(who)
      const coverageDiffers = vals.some((v) => v === null) && vals.some((v) => v !== null)
      return { job: j, who, differs: new Set(vals).size > 1, coverageDiffers }
    })
    .filter((d) => d.differs)
    .sort((a, b) => (b.coverageDiffers - a.coverageDiffers) || (b.job.priority - a.job.priority) || a.job.id.localeCompare(b.job.id))
}

export function insights(results, scenario) {
  const by = Object.fromEntries(results.map((r) => [r.algorithm, r]))
  const out = []
  const served = Object.fromEntries(results.map((r) => [r.algorithm, new Set(r.assignments.map((a) => a.job_id))]))

  // 1. Jobs greedy strands that a batch method rescues.
  if (by.greedy) {
    const rescued = scenario.jobs.filter((j) => !served.greedy.has(j.id) && ALGO_ORDER.some((a) => a !== 'greedy' && served[a]?.has(j.id)))
    if (rescued.length) {
      out.push({
        icon: '↯',
        html: `<b>Greedy strands ${rescued.length} job${rescued.length > 1 ? 's' : ''} that a batch method serves</b> (${rescued.slice(0, 4).map((j) => j.id).join(', ')}${rescued.length > 4 ? '…' : ''}). Committing engineers one job at a time gave away someone those jobs needed later.`,
        jobs: rescued.map((j) => j.id),
      })
    }
  }

  // 2. Work nobody can do: a staffing gap, not an algorithm gap.
  const never = scenario.jobs.filter((j) => results.every((r) => !served[r.algorithm].has(j.id)))
  if (never.length) {
    const byFam = {}
    never.forEach((j) => { byFam[j.skill] = (byFam[j.skill] || 0) + 1 })
    const fams = Object.entries(byFam).sort((a, b) => b[1] - a[1]).map(([f, n]) => `${n} ${f}`).join(', ')
    out.push({
      icon: '!',
      html: `<b>${never.length} job${never.length > 1 ? 's' : ''} can't be served by any strategy</b> (${fams}). This is a certification or capacity gap; see the Workforce tab. A better algorithm won't fix it.`,
      jobs: never.map((j) => j.id),
    })
  }

  // 3. What search buys over one-pass construction.
  const constructive = results.filter((r) => ['greedy', 'hungarian', 'regret'].includes(r.algorithm))
  const search = results.filter((r) => ['alns', 'pyvrp'].includes(r.algorithm))
  if (constructive.length && search.length) {
    const bestC = constructive.reduce((x, y) => (y.metrics.objective < x.metrics.objective ? y : x))
    const bestS = search.reduce((x, y) => (y.metrics.objective < x.metrics.objective ? y : x))
    const saving = (bestC.metrics.objective - bestS.metrics.objective) / (bestC.metrics.objective || 1)
    if (bestC.metrics.objective - bestS.metrics.objective > costMargin(bestS.metrics.objective)) {
      out.push({
        icon: '↘',
        html: `<b>Search pays off: ${ALGO_SHORT[bestS.algorithm]} costs ${Math.round(saving * 100)}% less than the best one-pass method</b> (${ALGO_SHORT[bestC.algorithm]}), mostly by cutting idle wait (${fmt(bestS.metrics.wait_min_total, 0)} vs ${fmt(bestC.metrics.wait_min_total, 0)} min). It takes about a second instead of milliseconds.`,
      })
    }
  }

  // 4. Hungarian's round structure: balance and response vs idle time.
  if (by.hungarian && by.regret) {
    const h = by.hungarian.metrics, r = by.regret.metrics
    if (h.wait_min_total > r.wait_min_total * 1.1) {
      out.push({
        icon: '◷',
        html: `<b>Hungarian spreads work evenly</b> (workload std ${fmt(h.workload_std)} vs ${fmt(r.workload_std)}) <b>but adds ${fmt(h.wait_min_total - r.wait_min_total, 0)} min of idle wait</b>. Each round is optimal on its own, but later jobs land in routes where engineers wait for the window to open.`,
      })
    }
  }

  // 5. Response to bottleneck downs.
  const resp = results.map((r) => [r.algorithm, r.metrics.mean_response_min]).sort((a, b) => a[1] - b[1])
  if (resp.length > 1 && resp[resp.length - 1][1] - resp[0][1] >= 1) {
    out.push({
      icon: '⏱',
      html: `<b>${ALGO_SHORT[resp[0][0]]} reaches tool-downs fastest</b>: ${fmt(resp[0][1])} min average, against ${fmt(resp[resp.length - 1][1])} min for ${ALGO_SHORT[resp[resp.length - 1][0]]}.`,
    })
  }

  // 6. Agreement, so the reader knows how much the choice matters here.
  const dis = disagreements(results, scenario.jobs)
  const share = 1 - dis.length / (scenario.jobs.length || 1)
  out.push({
    icon: '≡',
    html: `<b>${dis.filter((d) => d.coverageDiffers).length} job${dis.filter((d) => d.coverageDiffers).length === 1 ? '' : 's'} are served by some strategies and not others.</b> The strategies send the same engineer to only ${Math.round(share * 100)}% of jobs: many routes cost about the same, so the choice of engineer is often a near-tie.`,
  })
  return out
}

/** Demand vs certified supply per tool family, for the selected allocation. */
export function workforce(scenario, result) {
  const served = new Set(result?.assignments.map((a) => a.job_id) ?? [])
  return familyIds().map((fam) => {
    const jobs = scenario.jobs.filter((j) => j.skill === fam)
    const engs = scenario.engineers.filter((e) => e.skills[fam])
    const maxLevel = Math.max(0, ...jobs.map((j) => j.min_level))
    const needTop = jobs.filter((j) => j.min_level === maxLevel).length
    return {
      family: fam,
      jobs: jobs.length,
      demandHours: jobs.reduce((s, j) => s + j.duration, 0) / 60,
      bottleneckJobs: jobs.filter((j) => j.priority === 3).length,
      certified: engs.length,
      byLevel: [1, 2, 3].map((l) => engs.filter((e) => e.skills[fam] === l).length),
      maxLevel,
      needTop,
      served: jobs.filter((j) => served.has(j.id)).length,
    }
  })
}
