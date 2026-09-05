# The Dual-Context Evidence Model

One versioned record per evaluation, `schema_version: "1"`. Evidence from the 5G domain and evidence from the WLAN
domain are kept distinct, and transition evidence is represented explicitly, so that assurance obtained in one domain
is never silently reused in the other.

Every item carries `source`, `source_mode`, `observed_at`, an optional `expires_at`, a `validation` status and a
free-text `detail`. An item that could not be produced or emulated reproducibly does not belong in this model.

## Validation status

| Status | Meaning | Contributes to |
|---|---|---|
| `VALID` | Validated and current | — |
| `STALE` | Observed, but older than its freshness bound | DEGRADED |
| `MISSING` | Not available at all | DEGRADED |
| `INVALID` | Present and failed validation | UNTRUSTED or SUSPICIOUS |
| `UNVERIFIED` | Recorded; no validation applies | — |

Missing evidence is never contradictory evidence. That distinction is what separates DEGRADED from SUSPICIOUS.

## Categories and items

### 1. Device identity
| Item | Source | Meaning |
|---|---|---|
| `identity_registered` | registry | A registry entry exists |
| `identity_enabled` | registry | Administrative status is ACTIVE |
| `proof_of_possession_valid` | proof verifier | A verified proof exists and is within `proof_of_possession_ttl_s` |
| `public_key_fingerprint` | registry | SHA-256 of the DER SubjectPublicKeyInfo |

### 2. Access binding
| Item | Source | Meaning |
|---|---|---|
| `binding_present` | NR or WLAN collector | An access domain asserts a binding for the peer address |
| `binding_domain` | collector | Which domain asserts it |
| `binding_fresh` | collector | Refreshed within `binding_freshness_max_s` and not expired |
| `binding_consistent` | binding store | Not already attributed to a different device |

### 3. Access context
| Item | Meaning |
|---|---|
| `current_domain` / `previous_domain` | Where the device is now observed, and where it was |
| `transition_detected` | A transition falls within `transition_window_s` |
| `transition_age` | Seconds since the last detected transition |
| `transition_count_window` | Transitions within `rate_window_s` |

### 4. Security events
| Item | Meaning |
|---|---|
| `authentication_failure_count` | Failures within `authn_failure_window_s`, computed by CA-ZTCF |
| `identity_mismatch` | The binding is attributed to another device (the negation of `binding_consistent`) |
| `session_mismatch` | The service-layer session identity does not match the device identity |
| `unauthorized_context` | The observed access context violates a configured allow-list |

These are *computed* by the service domain from what it observes. An earlier conceptual design had a "risk indicators"
category that no real deployment could supply; it was removed and replaced by these counters.

### 5. Domain posture
| Item | Meaning |
|---|---|
| `domain_posture_ok` | The access context satisfies the configured allow-lists for its domain |
| `collector_available` | The collector is currently able to observe its domain |
| `evidence_complete` | Every item in `evidence_completeness_required` is present |

### 6. Evidence metadata
`assembled_at`, `evidence_age` (age of the oldest contributing observation), `schema_version`, `config_hash`.

## Provenance

`EvidenceRecord.source_modes()` and `.contains_synthetic()` expose where a record's content came from, and the API
returns `contains_synthetic_evidence` on every evaluation. In this milestone all 5G-side evidence is
`synthetic_fixture`. See ADR-0006.
