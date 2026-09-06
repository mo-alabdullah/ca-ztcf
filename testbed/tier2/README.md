# Tier 2 — reproducible software-based 5G/WiFi coexistence testbed

## What this is, and what it is not

A **reproducible software-based 5G/WiFi coexistence testbed**:

- **5G**: Open5GS 2.8.0 core with UERANSIM v3.2.6. Real 5G NAS, NGAP and GTP-U
  protocol interaction; a real PDU session; a real `uesimtun0` TUN interface.
  UERANSIM is a **software** UE and gNB — it synthesises the radio.
- **WiFi**: `mac80211_hwsim` virtual radios with hostapd and wpa_supplicant. Real
  IEEE 802.11 association, real RSN 4-way handshake, real WPA2-Enterprise
  EAP-TLS, through the real Linux `mac80211`/`cfg80211` stack. The **PHY is
  simulated**.

**There is no physical radio anywhere in this testbed.** It must never be
described as physical 5G radio, physical WiFi RF, a commercial 5G network, or a
real RF coexistence measurement.

### What Tier-2 measurements may support

Protocol and session transitions; authentication; trust evaluation; policy
enforcement; application continuity; software and testbed latency; CPU, memory
and message overhead.

### What they may never support

RF propagation performance; physical handover latency over real radios;
interference measurements; channel quality; spectrum coexistence performance.

Provenance is enforced in code, not left to discipline. Every Tier-2 observation
carries:

```
source_mode: live_testbed
testbed_type: software_based
access_implementation: ueransim | mac80211_hwsim
```

`scripts/check_source_modes.py` fails the build if a Tier-2 record omits
`testbed_type: software_based`, names no implementation, or asserts any
physical-radio property. The negative cases are tested.

## Environment

| Property | Value |
|---|---|
| Virtualisation | Lima 2.2.0 with the `vz` backend (Apple Virtualization) |
| Guest | Ubuntu 24.04.4 LTS |
| Kernel | 6.8.0-138-generic |
| Architecture | aarch64 |
| CPU / RAM / disk | 4 vCPU / 6 GiB / 38 GB |
| 5G core | Open5GS 2.8.0~noble5 (official PPA) |
| RAN + UE | UERANSIM v3.2.6 (built from source) |
| WLAN | `mac80211_hwsim`, hostapd 2.10, wpa_supplicant 2.10 |
| Subscriber DB | MongoDB 8.0 |

Lima was chosen because nothing suitable was already installed and it is the most
scriptable option on this host: the container runtimes present (Docker Desktop
LinuxKit, OrbStack) ship kernels with no loadable modules at all, so
`mac80211_hwsim` is impossible in them. Only one virtualisation system was added.

## Verified kernel capabilities

| Capability | Status |
|---|---|
| `/dev/net/tun` | present |
| network namespaces | working |
| veth pairs | working |
| `mac80211_hwsim` | **available and loaded** via `linux-modules-extra-6.8.0-138-generic` |
| `cfg80211` / `mac80211` | loaded |
| `nl80211` | working (`iw` enumerates phys and interfaces) |

## Reproducing the environment

```bash
limactl start testbed/tier2/ca-ztcf-tier2.yaml     # Ubuntu 24.04 VM
limactl shell ca-ztcf-tier2

sudo bash /opt/ca-ztcf/testbed/tier2/scripts/install_ueransim.sh
sudo bash /opt/ca-ztcf/testbed/tier2/scripts/provision_subscribers.sh 5
sudo bash /opt/ca-ztcf/testbed/tier2/scripts/start_services.sh
sudo bash /opt/ca-ztcf/testbed/tier2/scripts/start_5g.sh
sudo bash /opt/ca-ztcf/testbed/tier2/scripts/start_wlan.sh
sudo /opt/ca-ztcf-venv/bin/python /opt/ca-ztcf/testbed/tier2/scripts/tier2_validation.py
sudo bash /opt/ca-ztcf/testbed/tier2/scripts/reset.sh
```

Open5GS is pinned by the PPA package version; UERANSIM by git tag. The UERANSIM
build applies documented GCC 13 compatibility flags
(`-include cstring -include cstdio -include string -include cstdint`) because
v3.2.6 predates GCC 13's stricter transitive includes; this changes no behaviour
and leaves the pinned source untouched.

## Synthetic research identifiers

PLMN 999/70 is the 3GPP-reserved test network. Subscriber keys are the laboratory
test vectors published in the Open5GS documentation. No production credential and
no real subscriber identifier appears anywhere.

The SUPI is an **access-domain identifier**. It is hashed inside the 5G collector
before it reaches an access binding and is never the CA-ZTCF device identity,
which is a service-domain Ed25519 identity. See ADR-0002 and ADR-0004.

## Reset between runs

`scripts/reset.sh` clears CA-ZTCF state, MQTT sessions, UERANSIM processes, WLAN
association, Open5GS session state, transition counters and captured event
streams. Subscriber records are kept so provisioning need not be repeated.

Reset matters for correctness, not tidiness: a leftover access binding is
attributed to whichever device claimed it first, so the next run's devices would
be correctly judged UNTRUSTED and the result would look like a framework fault.

## Transition timing

`scripts/transition.sh` and the validation flow record seven timestamps
separately, so access authentication, path switching, trust decision and
application recovery can each be attributed rather than collapsed into one
unexplained number:

| Mark | Meaning |
|---|---|
| T0 | transition requested |
| T1 | target access authentication starts |
| T2 | target access authentication completes |
| T3 | route / application path switches |
| T4 | CA-ZTCF receives complete transition evidence |
| T5 | CA-ZTCF decision completes |
| T6 | MQTT protected operation succeeds |

## Known limitation: the 5G user-plane application path

The UE and the core are co-located on one host. Traffic addressed to the host's
own interfaces is either routed locally or source-NATed by the UPF masquerade
rule, so the enforcement point can observe the host address rather than the UE
tunnel address `10.45.0.2`. `nr-binder` forces `ping` onto the tunnel correctly
but did not reliably do so for the Python agent's socket.

Consequence: the 5G **control plane** is fully live and validated — registration,
authentication, PDU session, GTP-U, and real events consumed by the collector —
but the MQTT **application path** over the 5G user plane does not yet reliably
present the UE address to the enforcement point. Both real access-path addresses
have been observed by the core (`10.45.0.2` and `192.168.70.10`), so the
mechanism works; what is missing is a deterministic arrangement.

The fix is to separate the UE from the core network-namespace-wise, or to place
the service on an address reachable only through the tunnel, so that the UE
address is the only possible source. This is the last blocker before the final
experiment campaign and is tracked as such.
