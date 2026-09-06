# ADR-0009: Each access path runs in its own network namespace

- Status: Accepted
- Date: 2026-09-06
- Refines: ADR-0003 (two-tier testbed)

## Context

Tier 2 runs the UE, the 5G core, the access point and the station on one host. In
the Batch J–K arrangement all of them shared the root network namespace, and the
CA-ZTCF services listened on `0.0.0.0`. That made every service address a *local*
address from the device's point of view, with two consequences.

On the 5G side, a connection from the UE to the enforcement point was resolved by
the kernel's local routing table and delivered over loopback. It never entered
`uesimtun0`, never reached GTP-U, and the enforcement point observed the VM's own
address `192.168.5.15` instead of the UE tunnel address. The live 5G access
binding could therefore not be correlated with the application connection, and the
outcome was `DEGRADED` — correctly, because the evidence genuinely did not match.
UERANSIM's `nr-binder` did not fix this. It uses `LD_PRELOAD` to force
`SO_BINDTODEVICE` onto a socket, but a locally-routed destination still
short-circuits, and the interception did not reliably apply to sockets created by
CPython's asyncio.

On the WLAN side the same defect existed and had been missed. The station and the
access point were both in the root namespace, so traffic between `192.168.70.10`
and `192.168.70.1` was also delivered locally. The association and the EAP-TLS
exchange were real, but the application traffic attributed to the WLAN access path
had not crossed the 802.11 link.

Binding the agent's source address made the *observed address* correct while the
*path* remained wrong. That is precisely the situation the framework must not be
allowed to reward: a device would have been asserting its access context rather
than demonstrating it.

## Decision

Each access path gets its own network namespace, and the service is placed where
only that path can reach it.

**5G — namespace `ca-ztcf-ue`** (`testbed/tier2/network/ue_path.sh`)

- `nr-ue` runs inside the namespace, so `uesimtunN` is created there.
- A veth pair `uectl0` (root, `10.200.0.1/30`) / `uectl1` (`10.200.0.2/30`) carries
  UERANSIM's Radio Link Simulation. The gNB's `linkIp` moves to `10.200.0.1`;
  NGAP and GTP-U stay on loopback with the co-located AMF and UPF.
- The CA-ZTCF service address is `10.99.0.1/32` on a dummy interface `ztcfsvc0` in
  the root namespace. The only route to it from the UE namespace is through
  `uesimtunN`. Packets arrive on `ogstun` after GTP-U decapsulation and are
  delivered locally, so they never traverse `nat POSTROUTING` and are never
  masqueraded; a `RETURN` rule ahead of the Open5GS `MASQUERADE` rule states that
  invariant explicitly.
- TCP is rejected on the control veth inside the namespace. Without that, a
  service listening on `0.0.0.0` would be reachable at `10.200.0.1` and the tunnel
  could be bypassed silently. The rejection is restricted to TCP: a blanket
  `REJECT` destabilises RLS and drops the UE into repeated radio-link failure.

**WLAN — namespace `ca-ztcf-sta`** (`testbed/tier2/network/sta_path.sh`)

- The station's PHY is moved into the namespace with `iw phy … set netns`, and
  `wpa_supplicant` runs there. `mac80211_hwsim` still carries the frames between
  the two radios, so association, the RSN four-way handshake and EAP-TLS are
  unchanged.
- `hostapd` and the AP address `192.168.70.1` stay in the root namespace, which is
  now genuinely remote from the station's point of view.

Two further testbed properties follow from this decision.

**Static UE addresses.** The dynamic pool issues a different address after every
session teardown, which makes an access binding unpredictable and a run
irreproducible. Each subscriber is provisioned with a fixed address
(`10.45.10.<n>`, via `session[].ue.ipv4` in the Open5GS subscriber document), so
every Tier-2 device has a stable, unique identity on the 5G user plane.

**A keepalive on the 5G user plane.** UERANSIM's UE drops to RRC idle after a few
minutes without traffic, and resuming fails here: the gNB still holds the UE
context, answers the RRC Setup Request with "UE context already exists", and the
Service Request times out. The tunnel interface stays up while carrying nothing. A
five-second keepalive prevents the idle transition, and `ue_path.sh ensure`
verifies reachability and re-establishes the gNB and UE if it has already
happened. An IoT device sending periodic telemetry behaves the same way; the
keepalive touches no evidence, no trust logic and no measured interval.

## Consequences

- A Tier-2 device's traffic can only reach the enforcement point through the
  access technology it is attributed to. The observed source address is a
  *consequence* of the path rather than an assertion by the device, which is what
  makes C5 `BINDING_CONSISTENT` meaningful on live evidence.
- The device agent must be executed with `ip netns exec` inside the namespace that
  owns the path. It is run as a subprocess for that reason.
- Multiple devices no longer risk collapsing onto one observed identity: each UE
  has its own tunnel and a source-based routing rule, and the station namespace
  carries one address per device.
- Nothing in the framework changed. No predicate was weakened, no expectation was
  relaxed, and no address is trusted because a client claimed it. The defect was in
  the testbed's network topology and it was fixed there.
- The scope of Tier-2 claims is unchanged: this is a software-based testbed. Real
  5G NAS/NGAP/GTP-U and a real 802.11/EAP-TLS stack, simulated PHY. Nothing here
  supports a claim about RF propagation, interference, channel quality or physical
  handover.
