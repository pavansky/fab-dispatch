import { shiftStartHour } from './fab.js'

/** Shift-relative minutes as wall-clock time; the start hour comes from the active fab. */
export function clock(min) {
  const total = Math.round(min)
  const h = (shiftStartHour() + Math.floor(total / 60)) % 24
  return `${String(h).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`
}

export function fmt(v, digits = 1) {
  if (v === null || v === undefined || Number.isNaN(v)) return '–'
  if (Number.isInteger(v)) return v.toLocaleString()
  return v.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

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
