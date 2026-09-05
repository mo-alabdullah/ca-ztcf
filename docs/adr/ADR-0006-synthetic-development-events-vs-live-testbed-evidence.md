# ADR-0006: Synthetic development events versus live testbed evidence

- Status: Accepted
- Date: 2026-09-06

## Context

No Tier-2 Open5GS/UERANSIM capture exists yet, and batches A–E must not wait for one. Development therefore needs 5G
access-context events before any real 5G core has run. The risk is obvious and serious: synthetic development data
silently becoming "results" in a thesis.

## Decision

Provenance is a mandatory field on every observation and every derived evidence item, not an annotation that can be
forgotten. `ca_ztcf.collectors.base.SourceMode` declares four values:

| Value | Meaning |
|---|---|
| `synthetic_fixture` | A development fixture. **Never a measurement.** |
| `replay_capture` | A recorded live capture, replayed deterministically. |
| `live_testbed` | Observed from a real Open5GS/UERANSIM or hostapd deployment. |
| `service_domain` | Computed by CA-ZTCF itself rather than observed in an access domain. |

`SyntheticFixtureProvider` refuses to accept an event that is not marked `synthetic_fixture`
(`tests/unit/test_collectors.py::test_synthetic_provider_rejects_non_fixture_events`). `EvidenceRecord.source_modes()`
and `contains_synthetic()` expose a record's provenance, and the API returns `contains_synthetic_evidence` on every
evidence evaluation, so a synthetic record cannot be mistaken for a measured one even at the HTTP boundary.

Development validation output is written to `artifacts/dev-validation/`, deliberately separate from any future
`results/` tree, and each report carries an explicit disclaimer.

## Consequences

**Positive.** Batches A–E proceed with no Tier-2 dependency, and the boundary between fixture and measurement is
enforced by code rather than by discipline.

**Negative.** The fixtures encode our current belief about what a 5G core exposes. Batch K must validate that belief
against real Open5GS AMF/SMF events and correct the fixture schema if it diverges. Until then, no claim whatsoever
may be made about 5G-side behaviour.
