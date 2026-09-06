# ADR-0008: Correcting the 5G evidence schema against a running Open5GS core

- Status: Accepted
- Date: 2026-09-06
- Refines: ADR-0006 (synthetic development events versus live testbed evidence)

## Context

Batches A–I used a synthetic fixture for all 5G access-context evidence, and
ADR-0006 recorded the obligation plainly: "the fixtures encode our current belief
about what a 5G core exposes. Batch K must validate that belief against real
Open5GS AMF/SMF events and correct the fixture schema if it diverges."

Tier 2 now runs a real Open5GS 2.8.0 core with UERANSIM v3.2.6 attached, so the
belief could finally be checked. It was checked by reading the logs of a running
core with a registered UE and an established PDU session, not by reading
documentation.

## Findings

| Evidence field | Assumed | Reality in Open5GS 2.8.0 | Verdict |
|---|---|---|---|
| `subscriber_ref` (SUPI) | free-form subscriber reference | `imsi-999700000000001`, in AMF and SMF | **Supported directly** |
| `peer_address` (UE IPv4) | present on the NR event | SMF: `UE SUPI[...] DNN[internet] IPv4[10.45.0.2]`; UPF: `APN[...] PDN-Type[1] IPv4[...]` | **Supported directly**, but in a different line shape than assumed |
| `dnn` | present | `DNN[internet]` / `APN[internet]` | **Supported directly** |
| `registration_state` | present | `Registration complete` is logged | **Supported directly** |
| `pdu_session_id` | a plain field | embedded in the AMF context tag `[imsi-…:1:11]` | **Derivable** |
| `pdu_session_active` | a boolean field | no such field; derivable from establish/release events | **Derivable** |
| `rat_type` | a per-session field | not logged per session | **Derivable** only as an invariant of a 5G core |
| **`gnb_id`** | **a serving-cell identifier** | **not logged per session at all; only the N2 peer address, `gNB-N2[127.0.0.1]`** | **Incorrect assumption** |
| `snssai` | absent from the fixture | available: `S_NSSAI[SST:1 SD:0xffffff]` | Available, currently unused |

## Decision

The real system is authoritative. The framework changes, not the testbed.

1. **`gnb_id` is corrected to `serving_node`.** Open5GS exposes no per-session gNB
   identifier, so the collector now reports the N2 peer address, which is what
   actually exists, and the field is named for what it is. The `Open5gsEvent`
   model carries `serving_node`; the binding attribute keeps the key `gnb_id` so
   the evidence model and predicate C11 are unchanged, but its value is now an
   honest serving-node address rather than an invented cell identity.

   This has a direct consequence for policy: `posture.nr.allowed_gnb_ids` cannot
   be populated with cell identities from a deployment of this kind. It
   constrains the serving node by address. Any thesis statement about
   cell-level access control must be qualified accordingly.

2. **Log patterns follow the real formats.** The SMF session line is the
   authoritative SUPI-to-address binding; the UPF line provides the address
   without a SUPI; the AMF context tag yields the PDU session identifier. Release
   is matched before establishment, because a release line also mentions the SUPI
   and would otherwise resurrect a torn-down session.

3. **`rat_type` and `pdu_session_active` stay derived, and are labelled as
   derived.** Neither is an observed field.

4. **`snssai` is captured but not yet consumed.** It is recorded on the event so
   that a future slice-aware predicate has real data to work from, rather than
   being invented later.

5. **Tier-1 fixtures are unchanged and remain `synthetic_fixture`.** They are
   development fixtures, and correcting them to mimic real formats more closely
   would only make it easier to mistake them for measurements.

## Consequences

**Positive.** The 5G evidence schema now matches a real core. The one genuinely
wrong assumption was found and corrected before any experimental claim rested on
it, which is exactly what the gate in ADR-0006 existed to catch.

**Negative.** `allowed_gnb_ids` is weaker than the name suggested: it constrains a
serving-node address, not a cell identity. That limitation is now documented
rather than silently assumed, and it must be stated wherever posture policy is
described.

**Open.** These patterns are specific to Open5GS 2.8.0 log output. A different
core, or a deployment exposing events through NEF or NWDAF instead of logs, would
need its own adapter. The framework contract is the `AccessBinding` schema, not
the log format, so only the adapter would change.
