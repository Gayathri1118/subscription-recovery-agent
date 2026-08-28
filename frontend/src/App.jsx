import { useState } from 'react'
import EventList from './components/EventList'
import EventDetail from './components/EventDetail'
import ComparisonView from './components/ComparisonView'

export default function App() {
  const [tab, setTab] = useState('ledger') // 'ledger' | 'comparison'
  const [selectedEventId, setSelectedEventId] = useState(null)

  function goToTab(next) {
    setTab(next)
    setSelectedEventId(null)
  }

  return (
    <div className="app">
      <header className="app-header">
        <h1 className="app-title">
          RECOVERY LEDGER
          <small>subscription-recovery-agent — audit trail &amp; evaluation</small>
        </h1>
        <nav className="tabs">
          <button
            className={`tab ${tab === 'ledger' ? 'active' : ''}`}
            onClick={() => goToTab('ledger')}
          >
            Ledger
          </button>
          <button
            className={`tab ${tab === 'comparison' ? 'active' : ''}`}
            onClick={() => goToTab('comparison')}
          >
            Comparison
          </button>
        </nav>
      </header>

      <main>
        {tab === 'ledger' &&
          (selectedEventId ? (
            <EventDetail eventId={selectedEventId} onBack={() => setSelectedEventId(null)} />
          ) : (
            <EventList onSelect={setSelectedEventId} />
          ))}
        {tab === 'comparison' && <ComparisonView />}
      </main>
    </div>
  )
}
