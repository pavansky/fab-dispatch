import { ALGO_ORDER, ALGO_SHORT, METRICS, costSplit, improvement } from './metrics.js'
import { fmt, listOf, ms, plural } from './format.js'
import { familyIds, familyLabel } from './fab.js'

export const GOALS = {
  value: {
    label: 'Best value: cost × latency',
    help: 'Never trades away bottleneck coverage. Among plans whose total cost is within the noise margin of the cheapest, takes the fastest to compute. A slower solver has to earn its latency.',
    rank: ['objective', 'runtime_ms'],
  },
  bottleneck: {
    label: 'Protect bottleneck tools',
    help: 'Most bottleneck tool-downs covered, then the fastest response. Use when lost wafer moves dominate.',
    rank: ['critical_coverage_pct', 'mean_response_min', 'priority_weighted_coverage_pct'],
  },
  coverage: {
    label: 'Maximise coverage',
    help: 'Serve the most priority-weighted work, then the lowest total cost. Use when backlog is the problem.',
    rank: ['priority_weighted_coverage_pct', 'coverage_pct', 'objective'],
  },
  cost: {
    label: 'Lowest total cost',
    help: 'Lowest total cost, the objective every strategy minimises: walking, idle wait, over-qualification, unserved priority work and workload balance. Solve time is ignored.',
    rank: ['objective', 'priority_weighted_coverage_pct'],
  },
}

// Differences smaller than this are treated as a tie when ranking.
const TIE = { critical_coverage_pct: 0.05, priority_weighted_coverage_pct: 0.05, coverage_pct: 0.05, mean_response_min: 0.25, objective: 0.5 }
const tol = (key) => TIE[key] ?? 0

const short = (r) => ALGO_SHORT[r.algorithm] ?? r.algorithm
const names = (rs) => listOf(rs.map(short))
const order = (r) => ALGO_ORDER.indexOf(r.algorithm)
const value = (key, v) => (METRICS[key].unit === '%' ? `${fmt(v)}%` : `${fmt(v)} ${METRICS[key].unit}`)
const pctOf = (part, whole) => `${Math.round((100 * part) / (whole || 1))}%`

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

/**
 * How much faster `fastMs` is than `slowMs`, in words that survive rounding: null when the
 * difference is too small to mean anything (a few ms, or under 25%).
 */
export function speedup(fastMs, slowMs) {
  const ratio = slowMs / Math.max(fastMs, 0.1)
  if (slowMs - fastMs < 5 || ratio < 1.25) return null
  if (ratio >= 2) return `${fmt(ratio >= 10 ? Math.round(ratio) : Math.round(ratio * 10) / 10)}× faster`
  return `${fmt(Math.round(slowMs - fastMs))} ms faster`
}

/** "operating 512.0 + workload balance 43.4", when the API reports the split. */
export function costSplitText(m) {
  const s = costSplit(m)
  if (!s) return null
  const parts = [`operating ${fmt(s.operating)}`]
  if (s.workload !== null) parts.push(`workload balance ${fmt(s.workload)}`)
  if (s.other) parts.push(`${s.workload !== null ? 'stability' : 'other'} ${fmt(s.other)}`)
  return parts.join(' + ')
}

function recommendValue(results) {
  const crit = (r) => r.metrics.critical_coverage_pct
  const pri = (r) => r.metrics.priority_weighted_coverage_pct
  const cost = (r) => r.metrics.objective
  const time = (r) => r.metrics.runtime_ms
  const byCostThenOrder = (a, b) => cost(a) - cost(b) || order(a) - order(b)

  // 1. Guard: never give up bottleneck coverage, nor (when some plan leads on both)
  //    priority-weighted coverage, for speed or cost. If no plan is best on both, the
  //    bottleneck guard still holds on its own.
  const bestCrit = Math.max(...results.map(crit))
  const bestPri = Math.max(...results.map(pri))
  const critSafe = results.filter((r) => crit(r) >= bestCrit - 1e-9)
  const both = critSafe.filter((r) => pri(r) >= bestPri - 0.5)
  const bottleneckOnly = both.length === 0
  const pool = bottleneckOnly ? critSafe : both
  // 2. Cheapest plan, and everything within the noise margin of it.
  const byCost = [...pool].sort(byCostThenOrder)
  const cheapest = byCost[0]
  const margin = costMargin(cost(cheapest))
  const nearTie = pool.filter((r) => cost(r) <= cost(cheapest) + margin)
  // 3. Among statistically indistinguishable plans, the fastest wins.
  const byTime = [...nearTie].sort((a, b) => time(a) - time(b) || byCostThenOrder(a, b))
  const winner = byTime[0]
  const ranked = [winner, ...results.filter((r) => r !== winner).sort(byCostThenOrder)]
  const m = winner.metrics
  const excluded = results.filter((r) => !pool.includes(r))

  let why
  if (pool.length === 1) {
    why = results.length === 1
      ? 'Only strategy with a plan.'
      : `Only strategy that keeps the best bottleneck coverage (${fmt(bestCrit)}% of bottleneck downs)${bottleneckOnly ? '' : ' and priority-weighted coverage'}.`
  } else if (winner === cheapest && nearTie.length === 1) {
    const next = byCost[1]
    const gap = cost(next) - cost(winner)
    const fastest = [...pool].sort((a, b) => time(a) - time(b) || byCostThenOrder(a, b))[0]
    why = `Cheapest plan by a real margin: ${fmt(cost(winner))} pts, ${fmt(gap)} pts (${pctOf(gap, cost(next))}) below ${short(next)}, more than the ${fmt(margin, 0)}-pt noise margin.`
    why += fastest === winner
      ? ` It's also the fastest to compute (${ms(time(winner))}).`
      : ` That saving is worth its ${ms(time(winner))} solve.`
  } else if (winner === cheapest) {
    const next = byTime[1]
    const sp = speedup(time(winner), time(next))
    why = `Cheapest plan (${fmt(cost(winner))} pts), and the fastest of ${nearTie.length} equivalent plans within the ${fmt(margin, 0)}-pt noise margin: `
      + (sp ? `${sp} than ${short(next)} (${ms(time(winner))} vs ${ms(time(next))}).` : `${ms(time(winner))}, about as fast as ${short(next)} (${ms(time(next))}).`)
  } else {
    const diff = cost(winner) - cost(cheapest)
    const costPart = diff < 0.05
      ? `${short(winner)} and ${short(cheapest)} cost the same (${fmt(cost(winner))} pts).`
      : `${short(cheapest)} is cheaper by only ${fmt(diff)} pts, inside the ${fmt(margin, 0)}-pt noise margin, so it isn't a real win.`
    const sp = speedup(time(winner), time(cheapest))
    const speedPart = sp
      ? `${short(winner)} gets an equivalent plan ${sp} (${ms(time(winner))} vs ${ms(time(cheapest))}).`
      : `${short(winner)} is the fastest of ${nearTie.length} equivalent plans, though only just (${ms(time(winner))} vs ${ms(time(cheapest))}).`
    why = `${costPart} ${speedPart}`
  }
  why += ` Covers ${fmt(m.assigned)} of ${plural(m.jobs, 'job')}, ${fmt(m.critical_coverage_pct)}% of bottleneck downs.`
  if (bottleneckOnly) why += ' No plan leads on both bottleneck and priority-weighted coverage, so bottleneck coverage alone set the shortlist.'

  const tradeoff = []
  if (excluded.length) {
    tradeoff.push(`Not considered, less ${bottleneckOnly ? 'bottleneck' : 'bottleneck or priority-weighted'} coverage: ${names(excluded)}`)
  }
  const faster = pool.filter((r) => time(r) < time(winner) && !nearTie.includes(r)).sort(byCostThenOrder)[0]
  if (faster) tradeoff.push(`${short(faster)} answers in ${ms(time(faster))} but costs ${fmt(cost(faster) - cost(winner))} pts more`)
  return {
    winner, ranked, why, tradeoff, margin,
    // The noise band starts at the cheapest plan that passed the coverage guard.
    bandFrom: cost(cheapest),
    nearTie: nearTie.map((r) => r.algorithm),
    pool: pool.map((r) => r.algorithm),
  }
}

const bestOn = (items, key) => items.reduce((a, b) => (improvement(key, b.metrics[key], a.metrics[key]) > 0 ? b : a))
/** Items within the tie tolerance of the best one on `key` (anchored on the best, so it's transitive). */
const leaders = (items, key) => {
  const best = bestOn(items, key)
  return items.filter((r) => r === best || improvement(key, best.metrics[key], r.metrics[key]) <= tol(key))
}

/**
 * Lexicographic ranking with a tie tolerance. Pairwise "within tolerance" isn't transitive,
 * so a sort comparator built on it can order the same results differently depending on input
 * order. Instead: the group within tolerance of the best on the first key comes first (ranked
 * the same way on the remaining keys), then the rest, recursively. Default order breaks
 * exact ties, so the result never depends on the order results arrived in.
 */
export function rankBy(results, keys) {
  const items = [...results].sort((a, b) => order(a) - order(b))
  if (items.length <= 1 || keys.length === 0) return items
  const [key, ...rest] = keys
  const out = []
  let left = items
  while (left.length) {
    const group = leaders(left, key)
    out.push(...rankBy(group, rest))
    left = left.filter((r) => !group.includes(r))
  }
  return out
}

function recommendGoal(results, goalKey) {
  const goal = GOALS[goalKey]
  const sorted = rankBy(results, goal.rank)
  const [winner, runnerUp] = sorted
  const lead = goal.rank[0]
  const m = winner.metrics
  const label = (k) => METRICS[k].label.toLowerCase()

  let why
  if (!runnerUp) {
    why = 'Only strategy with a plan.'
  } else {
    // Walk the ranking: the first criterion on which the runner-up fell out of the winner's group.
    let group = results
    let splitKey = null
    for (const key of goal.rank) {
      group = leaders(group, key)
      if (!group.includes(runnerUp)) { splitKey = key; break }
    }
    if (splitKey === lead) {
      why = `Best ${label(lead)}: ${value(lead, m[lead])}, ${value(lead, Math.abs(m[lead] - runnerUp.metrics[lead]))} ahead of ${short(runnerUp)}, the next best.`
    } else if (splitKey) {
      const tiedOnLead = leaders(results, lead).filter((r) => r !== winner)
      why = `Ties with ${names(tiedOnLead)} on ${label(lead)} (${value(lead, m[lead])}) and wins on ${label(splitKey)}: `
        + `${value(splitKey, m[splitKey])} vs ${value(splitKey, runnerUp.metrics[splitKey])} for ${short(runnerUp)}.`
    } else if (group.length === results.length) {
      why = `All ${results.length} strategies tie on this goal, so ${short(winner)} is listed first by default order.`
    } else {
      why = `Ties with ${names(group.filter((r) => r !== winner))} on every criterion of this goal; listed first by default order.`
    }
  }
  why += ` Covers ${fmt(m.assigned)} of ${plural(m.jobs, 'job')}.`

  // The honest part: what you give up versus the best alternative on other KPIs.
  const tradeoffs = []
  for (const key of ['coverage_pct', 'critical_coverage_pct', 'mean_response_min', 'wait_min_total', 'objective']) {
    if (lead === key) continue
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
    return `${ALGO_SHORT[t.algo]} is ${value(t.key, t.gain)} ${verb} on ${def2.label.toLowerCase()}`
  })
  return { winner, ranked: sorted, why, tradeoff }
}

/**
 * The recommended plan for a planning goal. While strategies are still solving (or the
 * plans on screen predate the current weights), the pick is marked provisional and the
 * comparative claims are held back: they'd be made against an incomplete field.
 */
export function recommend(results, goalKey, { complete = true, waiting = [], stale = false } = {}) {
  const rec = goalKey === 'value' ? recommendValue(results) : recommendGoal(results, goalKey)
  if (complete && !stale) return { ...rec, provisional: false }
  const why = stale
    ? 'Provisional: these plans were solved with the previous weights. Re-solving with the new ones.'
    : `Provisional: best of the ${plural(results.length, 'strategy', 'strategies')} solved so far.`
      + `${waiting.length ? ` Waiting for ${listOf(waiting.map((a) => ALGO_SHORT[a] ?? a))};` : ''} the full comparison appears when every strategy has finished.`
  return { ...rec, why, tradeoff: [], provisional: true }
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

// Findings are plain data: strings, and { b } for the emphasised lead. The view renders them
// as elements, so nothing here is ever interpreted as HTML.
const em = (text) => ({ b: text })
const finding = (icon, parts, extra = {}) => ({ icon, parts, text: parts.map((p) => (typeof p === 'string' ? p : p.b)).join(''), ...extra })

/**
 * What a cheaper plan saved, by cost component, using the cost weights. Names a component
 * only when the numbers say so: "mostly" needs it to be at least half of the saving.
 */
function savingDriver(C, S, weights, scenario) {
  if (!weights) {
    return S.wait_min_total < C.wait_min_total ? `with less idle wait (${fmt(S.wait_min_total, 0)} vs ${fmt(C.wait_min_total, 0)} min)` : ''
  }
  const totalPri = scenario.jobs.reduce((s, j) => s + j.priority, 0)
  const both = (k) => typeof C[k] === 'number' && typeof S[k] === 'number'
  const parts = [
    ['cutting idle wait', (C.wait_min_total - S.wait_min_total) * weights.wait_min, `${fmt(S.wait_min_total, 0)} vs ${fmt(C.wait_min_total, 0)} min`],
    both('walk_m_total') && ['cutting walking', ((C.walk_m_total - S.walk_m_total) / 100) * weights.travel_100m, `${fmt(S.walk_m_total, 0)} vs ${fmt(C.walk_m_total, 0)} m`],
    ['cutting over-qualification', (C.overqualification_levels - S.overqualification_levels) * weights.overqualification, `${fmt(S.overqualification_levels, 0)} vs ${fmt(C.overqualification_levels, 0)} levels`],
    ['serving more priority work', ((S.priority_weighted_coverage_pct - C.priority_weighted_coverage_pct) / 100) * totalPri * weights.priority_reward,
      `${fmt(S.priority_weighted_coverage_pct)}% vs ${fmt(C.priority_weighted_coverage_pct)}% priority-weighted`],
    both('workload_cost') && ['balancing workload', C.workload_cost - S.workload_cost, `${fmt(S.workload_cost)} vs ${fmt(C.workload_cost)} pts`],
  ].filter((p) => p && Number.isFinite(p[1]) && p[1] > 0).sort((a, b) => b[1] - a[1])
  const [top, second] = parts
  if (!top) return ''
  const saving = C.objective - S.objective
  if (top[1] >= 0.5 * saving) return `mostly by ${top[0]} (${top[2]})`
  return `by ${top[0]} (${top[2]})${second ? ` and ${second[0]} (${second[2]})` : ''}`
}

/** Plain-language findings from a complete set of results. */
export function insights(results, scenario, { weights } = {}) {
  const by = Object.fromEntries(results.map((r) => [r.algorithm, r]))
  const out = []
  const served = Object.fromEntries(results.map((r) => [r.algorithm, new Set(r.assignments.map((a) => a.job_id))]))
  const jobById = Object.fromEntries(scenario.jobs.map((j) => [j.id, j]))
  const ids = (jobs) => `${jobs.slice(0, 4).map((j) => j.id).join(', ')}${jobs.length > 4 ? '…' : ''}`

  // 1. Jobs greedy strands that a batch method rescues.
  if (by.greedy) {
    const rescued = scenario.jobs.filter((j) => !served.greedy.has(j.id) && results.some((r) => r.algorithm !== 'greedy' && served[r.algorithm].has(j.id)))
    if (rescued.length) {
      out.push(finding('↯', [
        em(`Greedy strands ${plural(rescued.length, 'job')} that a batch method serves`),
        ` (${ids(rescued)}). Committing engineers one job at a time gave away someone those jobs needed later.`,
      ], { jobs: rescued.map((j) => j.id) }))
    }
  }

  // 2. Work nobody serves: a staffing gap, not an algorithm gap.
  const never = scenario.jobs.filter((j) => results.every((r) => !served[r.algorithm].has(j.id)))
  if (never.length) {
    const byFam = {}
    never.forEach((j) => { byFam[j.skill] = (byFam[j.skill] || 0) + 1 })
    const fams = Object.entries(byFam).sort((a, b) => b[1] - a[1]).map(([f, n]) => `${n} ${familyLabel(f)}`).join(', ')
    out.push(finding('!', [
      em(`${plural(never.length, 'job')} served by no strategy`),
      ` (${fams}). That points to a certification or capacity gap, not an algorithm gap; see the Workforce tab.`,
    ], { jobs: never.map((j) => j.id) }))
  }

  // 3. What search buys over one-pass construction.
  const constructive = results.filter((r) => ['greedy', 'hungarian', 'regret'].includes(r.algorithm))
  const search = results.filter((r) => ['alns', 'pyvrp'].includes(r.algorithm))
  if (constructive.length && search.length) {
    const bestC = constructive.reduce((x, y) => (y.metrics.objective < x.metrics.objective ? y : x))
    const bestS = search.reduce((x, y) => (y.metrics.objective < x.metrics.objective ? y : x))
    const C = bestC.metrics, S = bestS.metrics
    if (C.objective - S.objective > costMargin(S.objective)) {
      const driver = savingDriver(C, S, weights, scenario)
      out.push(finding('↘', [
        em(`Search pays off: ${short(bestS)} costs ${pctOf(C.objective - S.objective, C.objective)} less than the best one-pass method`),
        ` (${short(bestC)})${driver ? `, ${driver}` : ''}. It takes ${ms(S.runtime_ms)} instead of ${ms(C.runtime_ms)}.`,
      ]))
    }
  }

  // 4. Hungarian's round structure: idle time, and balance only when it's really better.
  if (by.hungarian && by.regret) {
    const h = by.hungarian.metrics, r = by.regret.metrics
    if (h.wait_min_total > r.wait_min_total * 1.1) {
      const extra = `adds ${fmt(h.wait_min_total - r.wait_min_total, 0)} min of idle wait over Regret-2`
      const cause = '. Each round is optimal on its own, but later jobs land in routes where engineers wait for the window to open.'
      out.push(h.workload_std < r.workload_std - 0.05
        ? finding('◷', [em('Hungarian spreads work more evenly'), ` (workload std ${fmt(h.workload_std)} vs ${fmt(r.workload_std)} jobs) `, em(`but ${extra}`), cause])
        : finding('◷', [em(`Hungarian ${extra}`), ` (${fmt(h.wait_min_total, 0)} vs ${fmt(r.wait_min_total, 0)} min)`, cause]))
    }
  }

  // 5. Response to tool-downs, among plans that serve at least one (the mean covers served ones only).
  const servesDowns = (r) => r.assignments.some((a) => jobById[a.job_id]?.kind === 'down')
  const resp = results.filter((r) => servesDowns(r) && Number.isFinite(r.metrics.mean_response_min))
    .map((r) => [r, r.metrics.mean_response_min]).sort((a, b) => a[1] - b[1] || order(a[0]) - order(b[0]))
  if (resp.length > 1 && resp[resp.length - 1][1] - resp[0][1] >= 1) {
    out.push(finding('⏱', [
      em(`${short(resp[0][0])} reaches tool-downs fastest`),
      `: ${fmt(resp[0][1])} min on average over the tool-downs it serves, against ${fmt(resp[resp.length - 1][1])} min for ${short(resp[resp.length - 1][0])}.`,
    ]))
  }

  // 6. Agreement, so the reader knows how much the choice matters here.
  if (results.length > 1) {
    const maps = Object.fromEntries(results.map((r) => [r.algorithm, assignmentMap(r)]))
    const split = disagreements(results, scenario.jobs).filter((d) => d.coverageDiffers).length
    const servedByAny = scenario.jobs.filter((j) => results.some((r) => served[r.algorithm].has(j.id)))
    const same = servedByAny.filter((j) => {
      const who = results.map((r) => maps[r.algorithm][j.id] ?? null)
      return who.every((w) => w !== null && w === who[0])
    }).length
    out.push(finding('≡', [
      em(`${plural(split, 'job')} ${split === 1 ? 'is' : 'are'} served by some strategies and not others.`),
      servedByAny.length
        ? ` Of the ${plural(servedByAny.length, 'job')} at least one strategy serves, all ${results.length} send the same engineer to ${fmt(same)} (${pctOf(same, servedByAny.length)}). Many routes cost about the same, so the choice of engineer is often a near-tie.`
        : '',
    ]))
  }
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
