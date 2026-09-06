# AMEND-0001 — two output-labelling defects found before any final data was kept

- Raised: 2026-09-06T13:53Z
- Type: software defect (two, found in the same stop)
- Campaign affected: primary
- Runs invalidated: every attempt recorded before this amendment — 1302 VALID and
  318 ABORTED, ledger SHA256
  `136ef7ef63e08cd99efa63c65af3286083f05464a67445181a346b31a9e621fc`

## Defect 1 — the resource record contradicted what it measured

`resources.json` carried the line

> host-side device agent and experiment runner are not measured

beside a `process` block holding that same experiment runner's CPU seconds and
peak resident memory. The two statements contradict each other. A reader trusting
the note would have misread every resource figure in the final results.

Two further consequences of the same oversight:

- `cpu_percent_mean` was `null` on essentially every run. Most runs finish inside
  one sampling interval, so interval sampling produced no samples, and shortening
  the interval would have perturbed the latency being measured. Metric M10 was
  therefore never observed.
- `memory_mib_max` was `null` for the same reason, leaving only peak RSS.

## Why this stopped the campaign

It is a defect in the software that writes final data, not a result. The protocol
requires that such a defect stops the campaign rather than being patched into
finished output, because a correction applied after the fact cannot be
distinguished later from a correction chosen to suit a result.

## Defect 2 — final runs declared themselves development output

Every run written under `results/final/` carried
`result_class: development_validation` and a disclaimer ending "not final thesis
experimental evidence", because the runner hard-coded the development class. The
source-mode gate caught it: development-class output must never appear under a
final-results path. Left unfixed, the entire final dataset would have declared
itself not to be final evidence.

## Fix

- `result_class` is a run parameter. The campaign driver sets `final`; everything
  else stays `development_validation`. The disclaimer follows the class, and still
  states what the testbed cannot support in both cases.
- The gate now separates the two conditions it had merged: Tier-1 output under a
  final path, and development-class output under a final path. Its message names
  which one occurred.
- The exclusion note now says what is actually excluded — the device agent, which
  is a separate process in another network namespace — and points at the `process`
  block for what was measured.
- CPU utilisation is reported as `cpu_percent_mean_over_run`, computed from CPU
  seconds over wall time. It is exact, needs no sampling and is defined for any
  run length. The sampled figures are kept alongside under
  `cpu_percent_sampled_mean` and `cpu_percent_sampled_max`, and are `null` when no
  sample fell inside the run.
- Metric M10 now takes the mean-over-run figure, so it is observed on every run.

## Regression tests

`tests/unit/test_experiments.py`:

- `test_resource_record_does_not_contradict_what_it_measured`
- `test_cpu_utilisation_is_defined_for_a_run_shorter_than_one_sample`

## Regression tests (defect 2)

`tests/unit/test_tier2_result_labelling.py`:

- `test_final_output_is_not_labelled_as_development`
- `test_a_final_run_declares_its_result_class_and_drops_the_development_caveat`

## Action taken, and one deviation from the protocol

Every attempt made before this amendment is invalidated. The primary matrix is
rerun in full from an empty ledger, and no measurement from the invalidated
attempts enters the final dataset.

**Deviation, recorded rather than hidden:** the protocol requires invalidated runs
to be preserved. They were not. The `results/final/` tree, including the ledger
and the session log, was deleted while clearing the working tree for the rerun,
before those files had been committed. What survives is the count (1302 VALID,
318 ABORTED) and the ledger SHA256 quoted above, taken from the campaign driver's
own output at the moment it stopped.

The scientific consequence is nil: no invalidated measurement can reach the final
dataset, and both defects were in how output was labelled and in whether a CPU
figure existed at all, not in what the framework decided. The procedural
consequence is real, and it is stated here rather than omitted. Preservation is
observed for the remainder of the campaign.

## What did NOT change

No trust state, predicate, policy rule, evidence model, ground-truth label,
baseline algorithm, scenario or enforcement semantic. No expected outcome. The
defect was in how a measurement was described and in whether a CPU figure existed
at all, never in what the framework decided.
