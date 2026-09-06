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

## Network topology

Each access path lives in its own network namespace, so a device's traffic can
only reach the enforcement point through the access technology it is attributed
to. Without that, every service address is also a local address, the kernel
delivers the traffic over loopback, and the enforcement point observes the VM's
own address instead of the device's access-path address. ADR-0009 records the
reasoning and the rejected alternatives.

```
  root namespace                        ca-ztcf-ue namespace
  ---------------------------------     ---------------------------------
  nr-gnb  RLS   10.200.0.1  <--veth-->  10.200.0.2   (uectl1)
          NGAP  -> 127.0.0.5            uesimtunN    10.45.10.N/32
          GTP-U <-> 127.0.0.7           route 10.99.0.0/24 dev uesimtunN
  open5gs-upfd -> ogstun 10.45.0.1/16   (TCP rejected on the control veth)
  ztcfsvc0 (dummy) 10.99.0.1/32

  hostapd -> wlan0 192.168.70.1         ca-ztcf-sta namespace
       ^                                ---------------------------------
       +------ 802.11 over hwsim -----> wlan1  192.168.70.10 .. .10+N-1
                                        wpa_supplicant (EAP-TLS)

  CA-ZTCF core :8080  |  mosquitto :1883  |  MQTT enforcement point :1884
```

| Property | Value |
|---|---|
| UE namespace | `ca-ztcf-ue` |
| Station namespace | `ca-ztcf-sta` |
| Control veth | `uectl0` 10.200.0.1/30 ↔ `uectl1` 10.200.0.2/30 (RLS only) |
| 5G service address | `10.99.0.1/32` on `ztcfsvc0`, reachable only via the tunnel |
| WLAN service address | `192.168.70.1` on `wlan0`, reachable only over 802.11 |
| UE addresses | `10.45.10.1 …` static, one per subscriber |
| Station addresses | `192.168.70.10 …` one per device |
| NAT | `-s 10.45.0.0/16 -d 10.99.0.0/24 -j RETURN` ahead of the Open5GS MASQUERADE |
| Expected 5G source at the PEP | the UE tunnel address, never `192.168.5.15` |

`network/verify_ue_path.py` proves this independently of CA-ZTCF: a plain TCP
server on the service address, a plain TCP client inside the UE namespace, and
packet captures on both ends of the tunnel.

Two supporting properties. Subscribers get **static UE addresses**
(`session[].ue.ipv4`), because the dynamic pool issues a different address after
every teardown and makes a run impossible to repeat. A five-second **keepalive**
holds the user plane open: UERANSIM's UE drops to RRC idle after a few minutes
without traffic and cannot resume while the gNB holds a stale UE context, leaving
a tunnel interface that is up but carries nothing. `ue_path.sh ensure N` checks
reachability *and* that N sessions exist, and re-establishes if not.

## Reproducing the environment

```bash
limactl start testbed/tier2/ca-ztcf-tier2.yaml     # Ubuntu 24.04 VM
limactl shell ca-ztcf-tier2

sudo bash /opt/ca-ztcf/testbed/tier2/scripts/install_ueransim.sh
sudo bash /opt/ca-ztcf/testbed/tier2/scripts/provision_subscribers.sh 25
sudo bash /opt/ca-ztcf/testbed/tier2/scripts/start_services.sh
# UE_COUNT and STA_COUNT are one live access path per device. E13 sweeps to 25.
sudo UE_COUNT=25 bash /opt/ca-ztcf/testbed/tier2/scripts/start_5g.sh    # gNB + UE namespace
sudo STA_COUNT=25 bash /opt/ca-ztcf/testbed/tier2/scripts/start_wlan.sh # AP + station namespace
sudo bash /opt/ca-ztcf/testbed/tier2/network/capture_events.sh start

# prove the 5G path, then the framework end to end
sudo /opt/ca-ztcf-venv/bin/python /opt/ca-ztcf/testbed/tier2/network/verify_ue_path.py
sudo /opt/ca-ztcf-venv/bin/python /opt/ca-ztcf/testbed/tier2/scripts/tier2_validation.py

# E01-E15 against live evidence, at a development repetition count
cd /opt/ca-ztcf && sudo PYTHONPATH=/opt/ca-ztcf/src:/opt/ca-ztcf \
  /opt/ca-ztcf-venv/bin/python scripts/run_matrix.py \
  --access-source tier2 --repetitions 3 --out results/dev/tier2

sudo bash /opt/ca-ztcf/testbed/tier2/scripts/reset.sh soft   # or: reset.sh full
```

`--access-source tier2` reads evidence from Open5GS's and hostapd's own logs and
from the live interfaces. If the testbed cannot supply a device's access path the
run **fails**; it never falls back to a fixture, because a run that quietly fell
back would be reported as live evidence while not being live evidence.

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

`scripts/reset.sh` has two levels.

- `reset.sh soft` (default) restarts the CA-ZTCF core, broker and enforcement
  point, which is where the device registry, binding store, trust states and
  transition counters live. The access paths stay up, so repetitions start clean
  without paying for re-registration and re-association.
- `reset.sh full` also tears down both namespaces, the UE, the gNB, the virtual
  radios and Open5GS session state, back to a freshly provisioned VM. Subscriber
  records are kept so provisioning need not be repeated.

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

## The access domain is derived, never declared

The enforcement point sees a TCP peer address and nothing about the access
network the connection crossed. It therefore states no access domain, and the
service derives it from the access binding that matches the observed address.
Every decision's audit record carries `domain_source`, which is
`derived_from_binding` unless a caller explicitly declared one.

This became visible only once two real access paths existed. Before that, a fixed
default happened to be right; with both paths live it mislabelled every
connection arriving over the other access, and a device that had not moved was
recorded as transitioning.

A transition is likewise not announced. Every strategy calls
`transitions.observe()` while deciding, so the change is detected from the device
presenting itself at a new address in a new domain. Announcing it to
`/v1/transitions` as well counts the same transition twice and inflates the rate
window, which makes a first transition come back as a repeated one.

## Timing labels

`T4_to_T5` in the transition records covers the device reconnecting and the
enforcement point acting on the decision. The agent runs as a separate process
inside its access namespace, so that interval **includes interpreter start-up**
and is not a trust decision time. The decision alone is recorded separately as
`trust_decision_ms`.

## Scale reached, and its bound

25 concurrent UEs (one PDU session each, a distinct static address each) and 25
station addresses have been exercised, which covers every scenario's declared
device count. E13 declares sweeps to 50 and 100; those have **not** been run and
nothing about them is claimed. The station addresses share one 802.11 association:
devices are distinct by address, by service-domain identity and in the audit
trail, but a run with N independent radio associations would need N hwsim radios
and N supplicants, which has not been validated.
