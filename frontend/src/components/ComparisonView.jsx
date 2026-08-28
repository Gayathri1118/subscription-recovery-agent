import { useEffect, useState } from 'react'
import { api } from '../api'

function pct(x) {
  return x != null ? `${(x * 100).toFixed(1)}%` : '—'
}

function inr(x) {
  return x != null ? `₹${x.toLocaleString('en-IN')}` : '—'
}

export default function ComparisonView() {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    api
      .comparison()
      .then(setData)
      .catch((e) => setError(e.message))
  }, [])

  if (error) return <div className="panel"><div className="error">Failed to load comparison: {error}</div></div>
  if (!data) return <div className="panel"><div className="loading">Tallying the ledger…</div></div>

  const deltaPP = ((data.agent.recovery_rate - data.baseline.recovery_rate) * 100).toFixed(1)
  const deltaAmt = data.agent.recovered_amount - data.baseline.recovered_amount

  return (
    <>
      <div className="panel">
        <h2>Baseline vs. Agent — {data.total_events} events, same denominator</h2>
        <div className="comparison-grid">
          <div className="comparison-col">
            <h3>Baseline (blind retry)</h3>
            <div className="big-number">{pct(data.baseline.recovery_rate)}</div>
            <div className="sub-number">{data.baseline.recovered_count} recovered · {inr(data.baseline.recovered_amount)}</div>
          </div>
          <div className="comparison-col">
            <h3>Agent</h3>
            <div className="big-number">{pct(data.agent.recovery_rate)}</div>
            <div className="sub-number">{data.agent.recovered_count} recovered · {inr(data.agent.recovered_amount)}</div>
          </div>
        </div>
        <p className="note">
          Delta: {deltaPP >= 0 ? '+' : ''}{deltaPP} percentage points, {deltaAmt >= 0 ? '+' : ''}
          {inr(deltaAmt)} vs. baseline.
          Of the {data.total_events - data.agent.recovered_count} not recovered by the agent:{' '}
          {data.agent.attempted_but_failed} attempted but failed,{' '}
          {data.agent.declined_by_safety} declined by the safety gate
          {data.agent.still_pending ? `, ${data.agent.still_pending} still pending resolution` : ''}.
        </p>
      </div>

      <div className="panel">
        <h2>Strategy-selection uplift only</h2>
        <p className="note">
          Same {data.strategy_selection_uplift.attempted_count} events the agent actually attempted —
          safety declines excluded from both sides, isolating whether the LLM's strategy choice itself helps.
        </p>
        <div className="comparison-grid">
          <div className="comparison-col">
            <h3>Baseline on this subset</h3>
            <div className="big-number">{pct(data.strategy_selection_uplift.baseline_rate_on_subset)}</div>
          </div>
          <div className="comparison-col">
            <h3>Agent on this subset</h3>
            <div className="big-number">{pct(data.strategy_selection_uplift.agent_rate_on_subset)}</div>
          </div>
        </div>
      </div>

      <div className="panel">
        <h2>Negotiation-only revenue</h2>
        <p className="note">
          Revenue baseline structurally cannot reach — it never negotiates. Reported separately rather than
          blended into the rate above, where it would just look like noise at this sample size.
        </p>
        <div className="big-number">{inr(data.negotiation_only.recovered_amount)}</div>
        <div className="sub-number">{data.negotiation_only.kept_commitments} kept commitments</div>
      </div>
    </>
  )
}
