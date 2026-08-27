# Subscription Revenue Recovery Agent

Razorpay Buildathon — Track 03: AI Revenue Recovery

## What it solves

Recovers failed subscription payments by diagnosing the cause, negotiating
in Hinglish, and tracking promises to pay — with every action gated by a
deterministic safety policy before anything executes.

## AI judgment, stated explicitly

The LLM is used **only** where language understanding is genuinely needed:
diagnosing customer intent and extracting a promise date from a customer
reply. Everything else — policy checks, safety gating, stopping rules — is
deterministic code. See `app/policy.py` / `app/safety.py` (Policy & Safety phase) for the
rules.

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
EXECUTOR (mock payment provider) → sends Hinglish message / retries
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

Currently on **LLM Integration phase** (Foundation and Policy & Safety phases complete — see full roadmap in the project spec).

- [x] Repo init, Postgres schema, FastAPI scaffold
- [x] Synthetic data generator (seeded, 80 events + 5-language reply bank:
      Hindi, Tamil, Telugu, Kannada, Malayalam code-mixed)
- [x] Mock payment provider
- [x] Baseline (blind-retry) function, metrics logged
- [x] Detector + Diagnosis + Policy + Safety (Policy & Safety phase), wired into LangGraph
- [ ] LLM integration — Groq / Llama 3.3 70B (LLM Integration phase)
- [ ] Full batch + evaluation + demo scenario (Evaluation phase)
- [ ] Polish, docs, video (Submission phase)

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
spec section 9).

### 4. Run the baseline

```bash
python -m baseline.blind_retry
```

Prints the baseline recovery rate — this is the number the real agent has
to beat in the final comparison (spec section 10).

### 5. Start the API

```bash
uvicorn app.main:app --reload
```

- `GET /health`
- `GET /failure-events` — list the batch
- `GET /failure-events/{id}` — one event's full audit trail + outcomes
- `GET /metrics/{strategy}` — aggregate recovery rate for a strategy label
  (e.g. `/metrics/baseline_blind_retry`)
- `POST /mock/recovery/{event_id}/execute` — mock provider endpoint

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

See `app/schema.sql` for the source of truth. One deliberate deviation
from the original spec: `recovery_outcomes` has a composite primary key
`(failure_event_id, strategy)` rather than just `failure_event_id`, so the
same event can carry both a `baseline_blind_retry` row and an agent-strategy
row for the section-10 side-by-side comparison.

## Failure recovery log

See [`docs/what-broke.md`](docs/what-broke.md) — started hour 1, real bugs
only.
