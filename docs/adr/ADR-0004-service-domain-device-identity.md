# ADR-0004: An access-independent, service-domain device identity

- Status: Accepted
- Date: 2026-09-06

## Context

The framework needs one stable identifier for a device across both access domains. The tempting candidates are all
access-domain identifiers: station MAC, SUPI, PEI/IMEI, EAP identity. Each is available, and each is wrong.

A MAC address is spoofable and changes under randomisation. A SUPI is confined to the operator domain and, per
ADR-0002, must not leave it. An EAP identity is confined to the WLAN. None of them survives a change of access
technology, which is precisely the event the framework exists to reason about.

## Decision

The CA-ZTCF `device_id` is a **service-domain identity**, bound to a device-held Ed25519 key pair. A device proves
control of that key by signing a single-use, time-limited server nonce (`ca_ztcf.identity.proof`). The registry
stores the device identifier, the public key, its SHA-256 fingerprint, an administrative status and research labels.
It never accepts, stores or returns private key material — enforced by a validator on the model and asserted by
`tests/unit/test_identity.py::test_private_key_is_never_accepted`.

5G and WiFi identifiers are **access evidence only**. They live in `AccessBinding.attributes`, hashed per ADR-0002.

## Consequences

**Positive.** The identity is invariant across access transitions, so the trust engine reasons about one subject
rather than two correlated ones. It requires only capabilities the IoT baselines already expect: a protected device
identity and secure storage of security parameters (ETSI EN 303 645; NIST IR 8425; NIST SP 800-213). And it is what
makes ADR-0002 possible: attribution happens through the device's own key, not through a shared identifier.

**Negative.** Devices must be enrolled before they can be trusted, which is an operational cost and is why UNKNOWN
denies rather than re-authenticates (ADR-0005). Compromise of the device private key defeats the scheme entirely;
this is stated in the threat model as an explicit boundary.
