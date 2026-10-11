// Reconnect delays after a dropped shift stream: 1, 2, 4, 8 … s, never more than 30 s.
// Tests shorten these.
export const RECONNECT_MS = { first: 1000, max: 30000 }
