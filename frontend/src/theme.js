export const FAMILY_COLORS = {
  litho: '#d4a017',
  etch: '#3b82c4',
  deposition: '#8b5cf6',
  cmp: '#14a37f',
  implant: '#e0607e',
  metrology: '#6b7f99',
}

const ENGINEER_HUES = [210, 25, 140, 280, 350, 180, 55, 310, 100, 240, 5, 160, 80, 330, 195, 260, 40, 120]
export const engineerColor = (index) => `hsl(${ENGINEER_HUES[index % ENGINEER_HUES.length]} 65% 48%)`

export const PRIORITY_LABEL = { 1: 'PM', 2: 'Tool down', 3: 'Bottleneck down' }

export const fmtTime = (min) => {
  const h = Math.floor(min / 60)
  const m = Math.round(min % 60)
  return `${String(7 + h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
}
