import { shiftStartHour } from './fab.js'

/** Shift-relative minutes as wall-clock time; the start hour comes from the active fab. */
export function clock(min) {
  const total = Math.round(min)
  const h = (shiftStartHour() + Math.floor(total / 60)) % 24
  return `${String(h).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`
}

/** A number for display; a missing one (null, undefined, NaN) reads "n/a", never "NaN". */
export function fmt(v, digits = 1) {
  if (v === null || v === undefined || typeof v !== 'number' || Number.isNaN(v)) return 'n/a'
  if (Number.isInteger(v)) return v.toLocaleString()
  return v.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

/** "1 job", "3 jobs": a count with the noun agreeing. */
export function plural(n, one, many = `${one}s`) {
  return `${fmt(n)} ${n === 1 ? one : many}`
}

/** "A", "A and B", "A, B and C". */
export function listOf(items) {
  if (items.length <= 1) return items.join('')
  return `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`
}

/** A solve time that stays readable below 10 ms. */
export const ms = (v) => `${fmt(v, v < 10 ? 1 : 0)} ms`

export const PRIORITY = {
  1: { label: 'PM', long: 'Preventive maintenance' },
  2: { label: 'Tool down', long: 'Tool down' },
  3: { label: 'Bottleneck', long: 'Bottleneck tool down' },
}


export const REJECTION_LABEL = {
  skill_missing: 'not certified',
  level_too_low: 'certification too low',
  at_capacity: 'at max jobs',
  window_missed: "can't arrive in window",
  shift_overrun: 'would overrun shift',
}
