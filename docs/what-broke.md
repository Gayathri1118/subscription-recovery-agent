# What Broke

Real bugs only, logged as they happen. This is a scored signal (spec section
2, "Failure recovery") — don't fabricate polish, don't backfill fake entries.

Format per entry:
```
Problem:
Why it happened:
How it was detected:
Fix:
How regression was prevented:
```

---

### Entry 1

**Problem:** `apt-get install postgresql` initially failed with 404s from
`security.ubuntu.com` while fetching `postgresql-16` and `libpq5`.

**Why it happened:** Ubuntu 24.04 (noble) had a stale package index — the
mirror had moved the packages between when the base image was built and
install time.

**How it was detected:** Package fetch errors in the install log
(`404 Not Found`).

**Fix:** Ran `apt-get update` to refresh the index before retrying
`apt-get install --fix-missing`.

**How regression was prevented:** Not applicable to the deployed app —
production/dev setup uses the `postgres:16-alpine` Docker image via
`docker-compose.yml`, which pins an exact image tag and sidesteps host
package-manager drift entirely. This only came up because I smoke-tested
the schema and pipeline against a locally installed Postgres in the build
sandbox (no Docker daemon available there) rather than docker-compose.

---

### Entry 2

**Problem:** The Day 2 regression test `test_four_nodes_logged_in_order` failed
on its first real run — it asserted the audit trail for a test event was
exactly `["detector", "diagnosis", "policy", "safety"]`, but got
`["baseline", "detector", "diagnosis", "policy", "safety"]` instead.

**Why it happened:** The test's helper function looked for an existing
event matching the test's criteria (amount=299, attempt_number=0,
status=open) before creating a new one. It found a real event from the
seeded batch — one that `baseline/blind_retry.py` had already processed on
Day 1, leaving a `node="baseline"` row in `agent_actions` for it. The test
never accounted for the fact that batch events can carry rows from
multiple strategies (which is intentional — that's the whole point of the
composite primary key on `recovery_outcomes`), so reusing a batch event for
a "clean" node-ordering test was the wrong approach.

**How it was detected:** Ran `pytest tests/test_policy_safety.py -v`
immediately after writing the Day 2 nodes, rather than assuming the code
was correct because it looked right.

**Fix:** Changed the test helper to always construct a fresh, isolated
event (unique `customer_id`) instead of ever matching against real batch
data, so node-ordering assertions can't be polluted by other strategies'
audit rows.

**How regression was prevented:** This is now itself the regression test —
future node-ordering tests default to isolated fixtures rather than reused
batch data, so this specific pollution can't recur silently.

---
### Entry 3

**Problem:** Regenerating the "same" seeded batch (`RANDOM_SEED=42`)
produced a different baseline recovery rate on every run — observed 62.5%
on one run and 53.8% on another, despite the seed being unchanged.

**Why it happened:** `FailureEvent.id` (`app/models.py`) defaulted to
Python's `uuid.uuid4()`, which is not seeded by `RANDOM_SEED`. The mock
payment provider's outcome is `hash(seed, event_id, attempt_number)`
(`mock_provider/provider.py`), so even with every other field identical,
a fresh unseeded `event_id` on each run fed a different hash input,
producing a different SUCCESS/FAILURE outcome per event — and therefore a
different aggregate recovery rate. This silently broke the spec's
explicit reproducibility promise (section 8): "same seed produces the same
demo run every time."

**How it was detected:** Regenerated the synthetic batch twice with the
same `RANDOM_SEED` as a sanity check before trusting the baseline number,
rather than assuming determinism because the seed was set. The two runs'
recovery rates didn't match.

**Fix:** In `data/generate_synthetic.py`, `event_id` is now derived from
the same seeded `random.Random(seed)` instance already used for the rest
of the batch (`uuid.UUID(int=rng.getrandbits(128), version=4)`) and passed
explicitly to `FailureEvent(id=...)`, instead of relying on the model's
unseeded default.

**How regression was prevented:** Verified by regenerating the batch twice
from a clean DB and confirming byte-identical `failure_events` rows and an
identical baseline recovery rate both times. Any future change that
reintroduces a non-deterministic field on `FailureEvent` would reappear as
a mismatch on this same two-run comparison.

---
### Entry 4

**Problem:** The full-batch pipeline run crashed partway through (49/80
events processed) with `groq.BadRequestError: Tool choice is required,
but model did not call a tool`. The retry wrapper (3 attempts, exponential
backoff) added specifically to handle transient structured-output
failures did not help -- all 3 retries failed identically.

**Why it happened:** The failure was specific to `gateway_timeout` events.
Per `app/diagnosis.py`'s `STRATEGY_MENU`, `gateway_timeout` maps to exactly
ONE eligible strategy (`immediate_retry`). The model, faced with a
"choice" that isn't really a choice, sometimes answered in free-text
markdown ("**Strategy:** immediate_retry... **Reasoning:** ...") instead
of making the required structured tool call. Since `strategy_agent`'s LLM
client runs at `temperature=0.0` for reproducibility, this failure is
fully deterministic given the same prompt -- so retrying the identical
prompt 3 times produced the identical failure 3 times. The retry wrapper
is genuinely useful for truly transient failures (rate limits, timeouts,
occasional non-deterministic tool-call misses), but this particular
failure mode is systematic, not transient, so no amount of retrying the
same input would have fixed it.

**How it was detected:** A full 80-event batch run crashed at event
49/80. The error's `failed_generation` field showed the model's actual
(non-tool-call) text response, which made the root cause visible
immediately rather than requiring further digging.

**Fix:** `strategy_agent_node` (`app/graph.py`) now short-circuits when
`diagnosis` returns exactly one eligible strategy: it selects that
strategy directly with `confidence=1.0` and logs the decision, without
calling the LLM at all. This mirrors the existing zero-eligible-strategies
branch (which also skips the LLM call) and is the philosophically correct
fix, not just a workaround -- if there's no real judgment call to make,
there's nothing for the model's judgment to add. As a side effect, this
also cuts total Groq API calls by roughly 40%, since `expired_card`
(1 eligible strategy: `send_update_card_link`) and `gateway_timeout`
(1 eligible strategy: `immediate_retry`) together account for a large
share of the synthetic batch.

**How regression was prevented:** Added a test with a mocked LLM client
that raises if called at all; asserts the LLM's `invoke.call_count == 0`
for a `gateway_timeout` event, and that `immediate_retry` is still
selected with `confidence=1.0` purely from the single-eligible-strategy
short-circuit. If a future change accidentally routes single-option cases
through the LLM again, this test fails immediately rather than only
surfacing intermittently on a full batch run.

---
### Entry 5

**Problem:** `python -m scripts.compare_recovery` showed the agent
recovering meaningfully LESS than the baseline (e.g. -11.2 percentage
points on one real run), which is the opposite of this project's core
premise -- a smarter, diagnosis-driven agent should outperform a blind
retry, not lose to it.

**Why it happened:** `mock_provider/provider.py`'s `mock_execute()`
computed its outcome purely from `hash(seed, event_id, attempt_number)` --
never from which strategy was chosen. Since `app/graph.py`'s
`executor_node` called `mock_execute()` with the SAME `(event_id,
attempt_number)` the baseline used for that same event, five of the six
agent strategies (`retry_same_card`, `request_alt_payment_method`,
`delayed_retry`, `immediate_retry`, `send_update_card_link`) produced
EXACTLY the same outcome as baseline, regardless of which one the LLM
picked. The agent's only possible source of genuine uplift was
`negotiate_promise_to_pay`'s separately-simulated commitment path; every
other "smarter" strategy choice was mechanically a no-op. Meanwhile the
safety gate correctly declines to auto-act on some events (amount over
limit, too many retries) that baseline blindly attempts and sometimes
wins on by chance -- pure downside with no offsetting uplift mechanism
for the other five strategies. Net effect: the agent structurally could
not beat baseline except via negotiation, no matter how good its strategy
selection was.

**How it was detected:** Built `scripts/compare_recovery.py` specifically
to produce the agent-vs-baseline number for the project's central claim.
The result contradicted the premise, which prompted tracing where a
"better" strategy could possibly change the simulated outcome -- leading
straight to `mock_execute()`'s signature.

**Fix:** `mock_execute()` gained an optional `strategy` parameter.
`baseline/blind_retry.py`'s call site is UNCHANGED (never passes
`strategy`), so baseline's hash and thresholds -- and therefore its
already-documented recovery numbers -- are byte-identical to before this
fix. `app/graph.py`'s `executor_node` now passes `strategy` through.
`retry_same_card` and `immediate_retry` deliberately still fall through to
the same thresholds and the same roll baseline uses, since they're
mechanically the identical action (same card, same immediate attempt) --
no artificial advantage where none is earned. The other three
(`request_alt_payment_method`, `delayed_retry`, `send_update_card_link`)
now get their own outcome profile (0.75 / 0.65 / 0.70 success
respectively, vs. baseline's 0.55) and an independent roll, reflecting
that they're genuinely different actions with a real-world reason to
succeed more often.

**How regression was prevented:** Reran baseline on both seed 42 and seed
7 after the fix and confirmed byte-identical recovered amounts and rates
to the pre-fix, already-documented numbers. Directly verified (with a
mocked `mock_execute`) that `executor_node` passes the chosen strategy
through in its call. Sampled each strategy's outcome 3,000 times and
confirmed convergence to its intended success probability. Any future
change that breaks baseline's call site into passing `strategy`
accidentally would immediately show up as a baseline-number mismatch on
this same two-seed comparison.

---