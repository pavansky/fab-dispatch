// The active fab profile (served by /api/fabs/{id}). Everything site-specific in the UI
// (family labels, floor areas, shift length and start hour) reads from here, so a new
// fab needs a profile file on the server and nothing in the frontend.
let active = null

export function setActiveFab(profile) { active = profile }
export const activeFab = () => active
export const familyIds = (p = active) => p?.families.map((f) => f.id) ?? []
export const familyLabel = (id, p = active) => p?.families.find((f) => f.id === id)?.label ?? id
export const familyPrefix = (id, p = active) => p?.families.find((f) => f.id === id)?.prefix ?? id.slice(0, 3).toUpperCase()
export const areasOf = (p = active) => Object.fromEntries((p?.families ?? []).map((f) => [f.id, f.area]))
export const shiftLength = (p = active) => p?.shift.length_min ?? 720
export const shiftStartHour = (p = active) => p?.shift.start_hour ?? 7
export const isConstraint = (id, p = active) => p?.constraint_family === id

/** Which tool family's area contains this floor point (for "report a job here"). */
export function familyAt({ x, y }, p = active) {
  return p?.families.find(({ area: [x0, y0, x1, y1] }) => x >= x0 && x <= x1 && y >= y0 && y <= y1)?.id
}
