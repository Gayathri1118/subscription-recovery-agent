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
