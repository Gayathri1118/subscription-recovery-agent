const BASE_URL = 'http://localhost:8000'

async function get(path) {
  const res = await fetch(`${BASE_URL}${path}`)
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || `${res.status} ${res.statusText}`)
  }
  return res.json()
}

export const api = {
  listEvents: () => get('/failure-events?limit=200'),
  getEvent: (id) => get(`/failure-events/${id}`),
  comparison: () => get('/metrics/comparison'),
}
