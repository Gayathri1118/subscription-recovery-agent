import { useEffect, useState } from 'react'
import { api } from '../api'
import StatusStamp from './StatusStamp'

export default function EventList({ onSelect }) {
  const [events, setEvents] = useState(null)
  const [error, setError] = useState(null)
  const [filter, setFilter] = useState('')

  useEffect(() => {
    api
      .listEvents()
      .then(setEvents)
      .catch((e) => setError(e.message))
  }, [])

  if (error) return <div className="error">Failed to load events: {error}</div>
  if (!events) return <div className="loading">Loading ledger…</div>

  const failureTypes = [...new Set(events.map((e) => e.failure_type))]
  const filtered = filter ? events.filter((e) => e.failure_type === filter) : events

  return (
    <div className="panel">
      <h2>Failure Ledger — {filtered.length} of {events.length} events</h2>
      <div style={{ marginBottom: 16 }}>
        <select
          className="mono"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          style={{ padding: '6px 10px', fontFamily: 'var(--font-mono)', fontSize: '0.8rem' }}
        >
          <option value="">All failure types</option>
          {failureTypes.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
      </div>
      <table>
        <thead>
          <tr>
            <th>Customer</th>
            <th>Failure type</th>
            <th>Amount</th>
            <th>Attempt</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {filtered.map((e) => (
            <tr key={e.id} onClick={() => onSelect(e.id)}>
              <td className="mono dim">{e.customer_id}</td>
              <td>{e.failure_type}</td>
              <td className="mono">₹{e.amount.toLocaleString('en-IN')}</td>
              <td className="mono">{e.attempt_number}</td>
              <td><StatusStamp label={e.status} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
