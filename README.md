# Subscription Revenue Recovery Agent
![CI](https://github.com/Gayathri1118/subscription-recovery-agent/actions/workflows/ci.yml/badge.svg)

A personal project exploring AI-driven recovery of failed subscription
payments for Indian markets — built to go deep on two things most
recovery tools skip: code-mixed Indian-language negotiation and a
deterministic safety layer that gates every automated action.

## Why this project

Most payment-recovery tooling either retries blindly or assumes customers
reply in plain English. Neither holds up in the Indian subscription market,
where customer replies routinely mix English with Hindi, Tamil, Telugu,
Kannada, or Malayalam, and where trusting an LLM to act on its own on a
real customer's payment method is not something any serious system should
do without a hard, auditable check first. This project builds both: an
agent that can actually understand a "kal tak pay kar dunga" reply, and a
policy/safety layer that keeps every LLM decision inside deterministic
guardrails before it touches anything.

## What it solves

Recovers failed subscription payments by diagnosing the cause, negotiating
in code-mixed Indian languages, and tracking promises to pay — with every
action gated by a deterministic safety policy before anything executes.

## AI judgment, stated explicitly

The LLM is used **only** where language understanding is genuinely needed:
diagnosing customer intent and extracting a promise date from a customer
reply. Everything else — policy checks, safety gating, stopping rules — is
deterministic code. See `app/policy.py` / `app/safety.py` for the rules.

### Language coverage

Beyond Hinglish, the reply bank (`data/customer_replies.py`) covers Tamil,
Telugu, Kannada, and Malayalam code-mixed replies — the transliteration
patterns most common among Indian subscription customers. Language ID is
**not** a separate detection step: it's one more field in the Promise-to-Pay
node's structured JSON output (LLM Integration phase), extracted in the same LLM call that
pulls the commitment date. This keeps it free — no extra API calls, no
extra latency — and avoids the unrealistic shortcut of tagging a customer's
language at generation time (real customers don't self-report that).
Language groupings in the reply bank exist only for your own stratified
eval scoring, never as model input.

## Architecture

```
Synthetic failure event
        │
        ▼
   DETECTOR (rule-based)          → classifies failure_type
        ▼
   DIAGNOSIS (rules + LLM)        → ranks valid interventions
        ▼
   RECOVERY STRATEGY AGENT (LLM)  → proposes ONE strategy + confidence
        ▼
   POLICY ENGINE (deterministic)  → amount limits, retry limits, dup checks
        ▼
   SAFETY GATE (deterministic)    → idempotency check, final go/no-go
        │
   ┌────┴────┐
   ▼         ▼
ALLOWED   BLOCKED/ESCALATE → audit event, human review queue
   │
   ▼
EXECUTOR (mock payment provider) → sends language-appropriate message / retries
   │
   ▼
PROMISE-TO-PAY NODE (LLM)        → extracts commitment date
   │
   ▼
Outcome → AUDIT TRAIL + METRICS
```

Every node writes to `agent_actions` — audit trail, demo narration, and
what-broke evidence in one table.

## Status

All phases complete: Foundation, Policy & Safety, LLM Integration, Evaluation.

- [x] Repo init, Postgres schema, FastAPI scaffold
- [x] Synthetic data generator (seeded, 80 events + 5-language reply bank:
      Hindi, Tamil, Telugu, Kannada, Malayalam code-mixed)
- [x] Mock payment provider
- [x] Baseline (blind-retry) function, metrics logged
- [x] Detector + Diagnosis + Policy + Safety, wired into LangGraph
- [x] LLM integration — Groq / `openai/gpt-oss-120b`, 7-node LangGraph pipeline
- [x] Full batch evaluation + promise-to-pay resolution
- [x] CI — GitHub Actions running pytest on every push
- [x] React dashboard + demo UI (`frontend/`) for browsing events and the
      full pipeline trace
- [ ] Demo script / narrated walkthrough (optional polish)

## Evaluation results

Seed 7, 80 synthetic failure events, same denominator for both arms.

| | Baseline (blind retry) | Agent |
|---|---|---|
| Recovered (count) | 41 | 31 |
| Recovery rate | 51.2% | 38.8% |
| Amount recovered | ₹101,459 | ₹55,269 |

The agent recovers less than baseline on the headline number. That's a
real, investigated result, not a bug — see
[`docs/what-broke.md`, Entry 6](docs/what-broke.md) for the full
breakdown. Two things drive the gap:

1. **The safety gate.** 10 of 80 events were declined outright (amount
   over limit, retry count exceeded) — baseline blindly attempts these
   and sometimes wins by chance; the agent correctly refuses to.
2. **Negotiation's low immediate-conversion rate.** The LLM chose
   `negotiate_promise_to_pay` 12 times; only 5 of those conversations
   produced a commitment, and 3 were kept — an effective ~25% hit
   rate, well under `delayed_retry`'s 65% for the same failure cause.
   The prompt deliberately favors negotiation on repeat
   `insufficient_funds` failures so the multi-language conversation path
   actually gets exercised in the batch, trading same-day recovery rate
   for demonstrating the code-mixed-language capability.

Isolating strategy choice from the safety gate (same 70 events the agent
actually attempted) still shows a gap — 44.3% vs. 50.0% — confirming
negotiation's conversion rate, not the safety gate, is the primary driver.

Negotiation also recovers revenue baseline structurally cannot reach by
construction: ₹7,997 across the 3 kept commitments this run, reported
separately here rather than blended into the rate comparison above, where
it would just look like noise on this sample size.

Note: these figures come from the batch seeded on the live Neon database
backing the deployed demo. A local run against the same seed can differ
slightly run to run, since Groq's model responses aren't bit-for-bit
reproducible even at temperature 0 — only the deterministic parts of the
pipeline (policy, safety, mock payment outcomes) are guaranteed identical.
## How to run

### 1. Start Postgres

```bash
docker compose up -d
```

This auto-loads `app/schema.sql` on first run. If you change the schema
after the volume already exists, re-apply manually:

```bash
docker exec -i recovery_agent_db psql -U recovery -d recovery_agent < app/schema.sql
```

### 2. Set up Python env

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### 3. Generate the synthetic batch

```bash
python -m data.generate_synthetic
```

Writes 80 seeded failure events to Postgres and a holdout manifest to
`data/holdout_ids.json` (20% of IDs, don't tune prompts against these —
keep them clean for final evaluation).

### 4. Run the baseline

```bash
python -m baseline.blind_retry
```

Prints the baseline recovery rate — this is the number the real agent has
to beat in the final comparison.

### 5. Start the API

```bash
uvicorn app.main:app --reload
```

- `GET /health`
- `GET /failure-events` — list the batch
- `GET /failure-events/{id}` — one event's full audit trail + outcomes
- `GET /metrics/{strategy}` — aggregate recovery rate for a strategy label
  (e.g. `/metrics/baseline_blind_retry`)
- `GET /metrics/comparison` — the agent-vs-baseline 3-part comparison, as JSON
- `POST /mock/recovery/{event_id}/execute` — mock provider endpoint

## Dashboard & demo UI

A React frontend (`frontend/`) provides a browsable ledger of all events
and a full 7-node pipeline trace per event — this doubles as the project
demo, in place of a terminal recording.

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173` (with the API running per step 5 above).
The **Ledger** tab lists every event and opens into its full pipeline
trace on click; the **Comparison** tab renders the same 3-part
agent-vs-baseline breakdown as the Evaluation results section above,
live from the database.

## Policy & Safety phase — deterministic pipeline (no LLM yet)

```bash
pytest tests/test_policy_safety.py -v
python -m scripts.run_policy_safety_pipeline
```

The pytest run is the actual Policy & Safety-phase checkpoint: it proves node ordering,
the amount-limit block, the retry-limit block, the already-recovered
block, and the duplicate-idempotency block all work. The pipeline script
runs the full batch through `detector -> diagnosis -> policy -> safety`
(via LangGraph, `app/graph.py`) and prints a decision breakdown.

Note: `proposed_strategy` and `confidence=1.0` are Policy & Safety-phase placeholders in
`diagnosis_node` — there's no Strategy Agent yet, so the graph
deterministically proposes the first eligible strategy from
`app/diagnosis.py`'s menu. LLM Integration phase replaces that placeholder with the real
LLM call's output.

## Data model

See `app/schema.sql` for the source of truth. One deliberate design choice: `recovery_outcomes` has a composite primary key
`(failure_event_id, strategy)` rather than just `failure_event_id`, so the
same event can carry both a `baseline_blind_retry` row and an agent-strategy
row for a direct side-by-side comparison.

## Failure recovery log

See [`docs/what-broke.md`](docs/what-broke.md) — kept from day one of the build, real bugs only.
