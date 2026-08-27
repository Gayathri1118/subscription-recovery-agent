"""Isolated test of the Promise-to-Pay extraction prompt against
data/customer_replies.py's 120-reply bank -- BEFORE wiring the LangGraph.

This is the highest-risk checkpoint of LLM Integration phase (per the
project spec, section 9): Llama 3.3 70B's Hinglish handling is a known
quantity, but Tamil/Telugu/Kannada/Malayalam code-mixed accuracy is not.
Run this in isolation and read the per-language breakdown before trusting
the extraction inside the full pipeline.

No DB writes, no LangGraph, no policy/safety gating -- just
prompt -> PromiseExtraction, scored against the reply bank's bucket labels
(intent) and language keys (detected_language), which serve as ground
truth here since the bank is hand-labeled by construction.

Run:
    python -m scripts.test_extraction_isolated                  # full 120
    python -m scripts.test_extraction_isolated --limit 20        # quick smoke test
    python -m scripts.test_extraction_isolated --language tanglish
    python -m scripts.test_extraction_isolated --language tanglish --language kanglish

Writes a full per-reply result dump to
scripts/extraction_results_<timestamp>.json for later inspection of
specific misses, in addition to the printed summary tables.
"""
import argparse
import datetime
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.llm_client import promise_llm
from data.customer_replies import ALL_REPLIES, LANGUAGES

REFERENCE_DATE = datetime.date.today().isoformat()

PROMPT_TEMPLATE = """You are extracting a payment commitment from a customer's reply to a \
payment-failure recovery message, in a subscription billing context in India.

Reference date (today): {reference_date}

Customer reply: "{reply}"

Classify the intent, resolve any relative date phrase (e.g. "kal", \
"naalaikku", "repu", "naale", "2 din mein") against the reference date \
into an ISO 8601 date, identify which code-mixed Indian language/script \
the reply is written in, and give your confidence.

If the reply is empty, a single word of acknowledgement, an emoji, or \
otherwise non-substantive, classify intent as "silence"."""


def build_prompt(reply: str) -> str:
    return PROMPT_TEMPLATE.format(reference_date=REFERENCE_DATE, reply=reply)


def run_one(lang_code: str, bucket: str, text: str, max_retries: int = 3) -> dict:
    """Call the LLM once for a single reply, with basic retry on transient
    errors (rate limits, timeouts). Returns a result dict; never raises --
    a permanent failure is recorded as an error entry so one bad reply
    doesn't kill the whole batch run."""
    prompt = build_prompt(text)
    last_error = None

    for attempt in range(max_retries):
        try:
            result = promise_llm().invoke(prompt)
            return {
                "language_expected": lang_code,
                "bucket_expected": bucket,
                "text": text,
                "intent_predicted": result.intent,
                "language_predicted": result.detected_language,
                "promised_date": result.promised_date,
                "confidence": result.confidence,
                "intent_correct": result.intent == bucket,
                "language_correct": result.detected_language == lang_code,
                "error": None,
            }
        except Exception as e:  # noqa: BLE001 -- deliberately broad, see docstring
            last_error = str(e)
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)  # 1s, 2s backoff

    return {
        "language_expected": lang_code,
        "bucket_expected": bucket,
        "text": text,
        "intent_predicted": None,
        "language_predicted": None,
        "promised_date": None,
        "confidence": None,
        "intent_correct": False,
        "language_correct": False,
        "error": last_error,
    }


def summarize(results: list[dict]) -> None:
    by_lang = defaultdict(lambda: {"n": 0, "intent_ok": 0, "lang_ok": 0, "errors": 0})
    by_bucket = defaultdict(lambda: {"n": 0, "intent_ok": 0})

    for r in results:
        lg = by_lang[r["language_expected"]]
        lg["n"] += 1
        lg["intent_ok"] += int(r["intent_correct"])
        lg["lang_ok"] += int(r["language_correct"])
        lg["errors"] += int(r["error"] is not None)

        bk = by_bucket[r["bucket_expected"]]
        bk["n"] += 1
        bk["intent_ok"] += int(r["intent_correct"])

    print("\n" + "=" * 72)
    print("PER-LANGUAGE ACCURACY")
    print("=" * 72)
    print(f"{'language':<20}{'n':>5}{'intent acc':>14}{'lang-id acc':>14}{'errors':>10}")
    for lang_code, lang in LANGUAGES.items():
        s = by_lang.get(lang_code, {"n": 0, "intent_ok": 0, "lang_ok": 0, "errors": 0})
        if s["n"] == 0:
            continue
        intent_acc = s["intent_ok"] / s["n"]
        lang_acc = s["lang_ok"] / s["n"]
        print(f"{lang['name']:<20}{s['n']:>5}{intent_acc:>13.0%} {lang_acc:>13.0%} {s['errors']:>10}")

    print("\n" + "=" * 72)
    print("PER-INTENT-BUCKET ACCURACY (across all languages)")
    print("=" * 72)
    print(f"{'bucket':<20}{'n':>5}{'intent acc':>14}")
    for bucket in ("clear_promise", "vague_stall", "dispute", "silence"):
        s = by_bucket.get(bucket, {"n": 0, "intent_ok": 0})
        if s["n"] == 0:
            continue
        acc = s["intent_ok"] / s["n"]
        print(f"{bucket:<20}{s['n']:>5}{acc:>13.0%}")

    total = len(results)
    total_intent_ok = sum(r["intent_correct"] for r in results)
    total_lang_ok = sum(r["language_correct"] for r in results)
    total_errors = sum(1 for r in results if r["error"] is not None)

    print("\n" + "=" * 72)
    print(
        f"OVERALL: {total} replies | "
        f"intent acc {total_intent_ok / total:.0%} | "
        f"language-id acc {total_lang_ok / total:.0%} | "
        f"errors {total_errors}"
    )
    print("=" * 72)

    misses = [r for r in results if not r["intent_correct"] and r["error"] is None]
    if misses:
        print(f"\n{len(misses)} intent MISSES (predicted != expected bucket):\n")
        for r in misses[:20]:  # cap console output; full list is in the JSON dump
            print(
                f"  [{r['language_expected']}] expected={r['bucket_expected']!r} "
                f"got={r['intent_predicted']!r}  text={r['text']!r}"
            )
        if len(misses) > 20:
            print(f"  ... and {len(misses) - 20} more (see JSON dump)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Only run the first N replies (across all languages) -- useful for a quick smoke test.",
    )
    parser.add_argument(
        "--language", action="append", default=None,
        help="Restrict to one or more language codes (e.g. --language tanglish). Repeatable.",
    )
    parser.add_argument(
        "--delay", type=float, default=0.0,
        help="Seconds to sleep between calls, to stay under free-tier rate limits if needed.",
    )
    args = parser.parse_args()

    replies = ALL_REPLIES
    if args.language:
        replies = [r for r in replies if r[0] in args.language]
    if args.limit:
        replies = replies[: args.limit]

    if not replies:
        print("No replies matched the given filters. Check --language values against "
              f"{list(LANGUAGES.keys())}.")
        return

    print(f"Running isolated extraction test: {len(replies)} replies "
          f"(reference_date={REFERENCE_DATE}, model=Groq Llama 3.3 70B)")

    results = []
    for i, (lang_code, bucket, text) in enumerate(replies, start=1):
        r = run_one(lang_code, bucket, text)
        results.append(r)
        status = "OK" if r["error"] is None else f"ERROR: {r['error'][:60]}"
        marker = "OK" if r["intent_correct"] else "MISS"
        print(f"[{i}/{len(replies)}] {marker} {lang_code}/{bucket}: {status}")
        if args.delay:
            time.sleep(args.delay)

    summarize(results)

    out_path = Path(__file__).resolve().parent / (
        f"extraction_results_{datetime.datetime.now():%Y%m%d_%H%M%S}.json"
    )
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(
            {"reference_date": REFERENCE_DATE, "results": results},
            f, ensure_ascii=False, indent=2,
        )
    print(f"\nFull results written to {out_path}")


if __name__ == "__main__":
    main()
