# AMEND-0002 — the trust engine timed itself with the frozen scenario clock

- Raised: 2026-09-06T14:20Z
- Type: software defect (measurement instrumentation)
- Campaign affected: primary and sensitivity
- Runs invalidated: all 2160, preserved under `results/invalidated/final-AMEND-0002/`
  (git-ignored; ledger SHA256
  `7333b8be6dd41ba2c4924a447126acaf6e921d2f64101b7747c7729fbc38df5c`)

## What was wrong

`TrustEngine.evaluate` measured its own duration through the **injected** clock:

```python
started_ns = self._clock.monotonic_ns()
...
duration_ns = max(0, self._clock.monotonic_ns() - started_ns)
```

The experiment runner injects a `FrozenClock`, whose `monotonic_ns` only moved
when a scenario explicitly advanced it. Metric **M12 — pure predicate evaluation
and state derivation** was therefore structurally zero: **540 of 540** CA-ZTCF
runs reported a maximum engine time of exactly 0.0 microseconds.

`PolicyEvaluator` measured its decision duration the same way and was affected
identically.

## Why this mattered enough to stop the campaign

P4 of the frozen protocol is *trust engine cost*. Publishing "median engine
evaluation time: 0.000 microseconds" would have read as an immeasurably fast
engine. It was not a fast engine; it was an instrument that had never been
connected. That is precisely the kind of number a thesis cannot carry.

The defect was found by inspecting the distribution before writing any claim, not
by a reader afterwards.

## Fix

A frozen wall clock and a frozen duration counter are different things, and
conflating them was the error.

- `FrozenClock` continues to freeze `now`, which is what makes evidence freshness,
  staleness and transition windows testable without sleeping.
- Its `monotonic_ns` now measures **real** elapsed time by default, because
  anything timing itself through it is measuring how long code actually took, and
  freezing that does not make the code instantaneous.
- `FrozenClock(real_durations=False)` remains available where a test genuinely
  needs a deterministic duration counter; the three clock tests that do now ask
  for it explicitly.

Scenario determinism is unaffected: wall-clock time, evidence, predicates,
decisions and trust states are identical. Only measured durations changed, and
they changed from "zero" to "measured".

## Regression tests

- `tests/unit/test_clock.py::test_a_frozen_wall_clock_still_measures_real_durations`
- `tests/unit/test_trust_engine.py::test_engine_reports_a_real_evaluation_duration`

The second asserts that at least one of twenty-five evaluations reports a non-zero
duration, which is the exact condition that failed silently here.

## Action taken

All 2160 runs invalidated and preserved. Both campaigns rerun in full from an
empty ledger at the corrected commit, with the same frozen seeds and the same
frozen configuration hash.

## What did NOT change

No trust state, predicate semantic, policy rule, evidence model, ground-truth
label, baseline algorithm, scenario meaning or enforcement semantic. No expected
outcome, and no threshold. The defect was in a stopwatch.
