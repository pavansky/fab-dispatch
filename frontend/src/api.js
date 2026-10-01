async function call(path, body) {
  const res = await fetch(`/api${path}`, body === undefined ? undefined : {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}))
    throw new Error(typeof detail.detail === 'string' ? detail.detail : `${res.status} ${res.statusText}`)
  }
  return res.json()
}

export const getMeta = () => call('/meta')
export const generateScenario = (params) => call('/scenario', params)
export const allocate = (scenario, weights) => call('/allocate', { scenario, weights })
export const runBenchmark = (params) => call('/benchmark', params)
