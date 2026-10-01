// Shift time 0 = 07:00 (day shift of a 12h rotation).
export const SHIFT_START_HOUR = 7
export const SHIFT_MIN = 720

export function clock(min) {
  const total = Math.round(min)
  const h = (SHIFT_START_HOUR + Math.floor(total / 60)) % 24
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

export const FAMILY_LABEL = {
  litho: 'Lithography', etch: 'Etch', deposition: 'Deposition', cmp: 'CMP', implant: 'Implant', metrology: 'Metrology',
}

export const REJECTION_LABEL = {
  skill_missing: 'not certified',
  level_too_low: 'certification too low',
  at_capacity: 'at max jobs',
  window_missed: "can't arrive in window",
  shift_overrun: 'would overrun shift',
}
