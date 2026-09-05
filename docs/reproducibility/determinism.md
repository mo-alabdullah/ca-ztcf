# Determinism

Every source of non-determinism is either eliminated or recorded.

## Time

All time flows through the injected `Clock` (`ca_ztcf.clock`). `SystemClock` is used at runtime; `FrozenClock` is used
in tests and advances only when explicitly told to.

**No test sleeps.** The whole suite of 191 tests runs in well under a second because "thirty-one seconds later" is
expressed as `clock.advance(seconds=31)`. Sleep-based tests are rejected in review: they are slow, flaky and they hide
boundary behaviour.

Two time sources are kept strictly separate. Wall-clock UTC is used for evidence observation times, expiry, freshness
and audit records. The monotonic counter is used **only** for measuring durations and is never written into an
evidence record as a point in time.

## Configuration

Every research threshold lives in `config/`, with a declared unit, purpose and default, and an explicit statement that
it is an experimental value rather than a validated universal one. No threshold appears as a constant in Python.

`config_hash` is a SHA-256 digest over the canonical JSON of the fully resolved settings, excluding the configuration
directory path so that a host run and a container run of an identical configuration hash identically. It is recorded
on every evidence record, trust evaluation, decision and audit line.

## Evaluation

Given the same evidence record and configuration, the trust engine produces the same state, the same firing rule and
the same reason codes. Only the generated identifier and the measured duration differ, and neither participates in
the derivation. Asserted by `test_repeated_evaluation_of_one_record_is_identical`.

## Explicit evaluation instants

Collector ingestion accepts `observed_at`, and evaluation accepts `at`. These are deliberate research affordances:
they let a scenario or a test express elapsed time without sleeping, which is what keeps experiments deterministic.
They are documented as such in the API and are not an operational feature.

## Randomness

Two sources exist and neither affects a decision: proof-of-possession nonces (`secrets.token_bytes`) and per-collector
hash salts. Nonce values never enter the trust derivation, and salts only ever compare a digest with another digest
from the same collector. When the experiment controller introduces scenario randomness in Batch I, the root seed will
be recorded in the run metadata and derived per device.
