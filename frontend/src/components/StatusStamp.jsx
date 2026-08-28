const CLASS_MAP = {
  ALLOWED: 'allowed',
  BLOCKED: 'blocked',
  ESCALATED: 'escalated',
  recovered: 'recovered',
  failed: 'failed',
  pending: 'pending',
}

export default function StatusStamp({ label }) {
  if (!label) return null
  const cls = CLASS_MAP[label] || 'neutral'
  return <span className={`stamp ${cls}`}>{label}</span>
}
