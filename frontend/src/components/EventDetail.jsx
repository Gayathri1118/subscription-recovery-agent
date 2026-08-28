import { useEffect, useState } from 'react'
import { api } from '../api'
import StatusStamp from './StatusStamp'

function renderOutput(output) {
  if (output == null) return null
  if (typeof output === 'string') return <p className="timeline-body">{output}</p>
  if (typeof output === 'object') {
    return (
      <dl className="event-meta" style={{ marginTop: 8, marginBottom: 0 }}>
        {Object.entries(output).map(([key, value]) => (
          <div key={key}>
            <dt>{key.replace(/_/g, ' ')}</dt>
            <dd>{typeof value === 'object' ? JSON.stringify(value) : String(value)}</dd>
          </div>
        ))}
      </dl>
    )
  }
  return <p className="timeline-body">{String(output)}</p>
}

export default function EventDetail({ eventId, onBack }) {
  const [event, setEvent] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    setEvent(null)
    setError(null)
    api
      .getEvent(eventId)
      .then(setEvent)
      .catch((e) => setError(e.message))
  }, [eventId])

  return (
    <div className="panel">
      <button className="back-link" onClick={onBack}>← back to ledger</button>

      {error && <div className="error">Failed to load event: {error}</div>}
      {!event && !error && <div className="loading">Loading pipeline trace…</div>}

      {event && (
        <>
          <h2>Event {event.id.slice(0, 8)}</h2>

          <dl className="event-meta">
            <div>
              <dt>Customer</dt>
              <dd className="mono">{event.customer_id}</dd>
            </div>
            <div>
              <dt>Failure type</dt>
              <dd>{event.failure_type}</dd>
            </div>
            <div>
              <dt>Amount</dt>
              <dd className="mono">₹{event.amount.toLocaleString('en-IN')}</dd>
            </div>
            <div>
              <dt>Status</dt>
              <dd><StatusStamp label={event.status} /></dd>
            </div>
          </dl>

          <h2>Pipeline trace</h2>
          <div className="timeline">
            {event.actions.length === 0 && (
              <p className="dim">No actions recorded yet for this event.</p>
            )}
            {event.actions.map((a, i) => (
              <div className="timeline-step" key={i}>
                <div className="timeline-marker">{i + 1}</div>
                <div className="timeline-head">
                  <span className="timeline-node">{a.node}</span>
                  <StatusStamp label={a.decision} />
                  {a.confidence != null && (
                    <span className="mono dim" style={{ fontSize: '0.75rem' }}>
                      confidence {a.confidence.toFixed(2)}
                    </span>
                  )}
                </div>
                {a.reasoning && <div className="timeline-reasoning">{a.reasoning}</div>}
                {renderOutput(a.output)}
              </div>
            ))}
          </div>

          <h2>Recovery outcomes</h2>
          {event.outcomes.length === 0 ? (
            <p className="dim">No recovery outcome recorded yet — likely still pending or blocked before execution.</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Strategy</th>
                  <th>Status</th>
                  <th>Recovered amount</th>
                  <th>Attempts</th>
                </tr>
              </thead>
              <tbody>
                {event.outcomes.map((o, i) => (
                  <tr key={i} style={{ cursor: 'default' }}>
                    <td className="mono">{o.strategy}</td>
                    <td><StatusStamp label={o.recovery_status} /></td>
                    <td className="mono">
                      {o.recovered_amount != null ? `₹${o.recovered_amount.toLocaleString('en-IN')}` : '—'}
                    </td>
                    <td className="mono">{o.attempt_count ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </div>
  )
}
