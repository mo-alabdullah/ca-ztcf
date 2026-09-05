# The Tier-1 testbed: what runs where

## Topology

```
host                         containers
----                         ----------
device agent      ------->   ca-ztcf-mqtt-pep : 1884  ------->  mosquitto : 1883
experiment runner                    |                          (no host port)
                                     v
                             ca-ztcf-core : 8080

                             tier1-wlan  (on demand)
                             hostapd <-- veth --> wpa_supplicant
```

| Component | Where | Why |
|---|---|---|
| `ca-ztcf-core` | container | The trust function. Config mounted read-only. |
| `ca-ztcf-mqtt-pep` | container | Enforcement. Calls the core for every decision. |
| `mosquitto` | container | The protected resource. No host port. |
| `tier1-wlan` | container, on demand | Needs `CAP_NET_ADMIN` and `CAP_NET_RAW` for a veth pair and raw EAPOL. Gets exactly those two. |
| device agent | **host** | Driven by the experiment runner and the integration flow. |
| experiment runner | **host** | Owns scenario time and writes raw output. |
| Tier 2 | **not present** | Open5GS, UERANSIM and `mac80211_hwsim` need a Linux VM. A later batch. |

Nothing is containerised for tidiness. `tier1-wlan` is a container because
`hostapd`'s wired driver and `wpa_supplicant`'s wired driver need real Linux
interfaces and raw frames, which macOS cannot provide; the container *is* the
Linux environment.

## The Tier-1 WLAN authentication path

Real `hostapd driver=wired` as 802.1X authenticator with its integrated EAP
server, and real `wpa_supplicant -Dwired` as supplicant, exchanging genuine
EAP-TLS over a veth pair against a research CA.

```bash
make tier1-wlan
```

Six scenarios, each verified to behave as declared:

| Scenario | Outcome |
|---|---|
| `valid` | EAP success |
| `reauth` | EAP success on a second authentication |
| `rogue` | EAP failure — client certificate from an untrusted CA |
| `expired` | EAP failure — certificate signed under a backdated clock, already expired |
| `no_cert` | EAP failure — no client certificate offered |
| `disconnect` | Station disconnected, binding released |

The 802.1X port state is reset between scenarios so each starts from a clean
authenticator state rather than inheriting the previous outcome.

Events land in `artifacts/tier1-wlan/events.jsonl` and are consumed by
`ca_ztcf.collectors.wlan_hostapd`, which normalises them into the same
`AccessBinding` schema everything else uses.

**This is not IEEE 802.11 radio access.** See ADR-0007.

## Running the milestone end to end

```bash
make testbed-build      # build core, enforcement point and the WLAN image
make testbed-up         # start core + mosquitto + enforcement point
make tier1-wlan         # run the EAP-TLS authentication-path scenarios
python scripts/mqtt_integration_flow.py    # end-to-end enforcement through the stack
make experiments        # E01-E05 under all three strategies
make process            # regenerate tables and figures from raw output
make verify             # expectations, reproducibility and source-mode gates
make testbed-down
```

## Determinism

Scenario time advances through a `FrozenClock`; the runner never sleeps to make
something happen. Durations use `time.perf_counter_ns`; timestamps are UTC wall
clock. Device keys are generated from the system CSPRNG rather than a seed: a
laboratory key is still a real key, and determinism comes from the clock and the
scenario, not from predictable secrets.

## Results

Development output goes to `results/dev/`. Nothing Tier-1 may be written to
`results/final/`, `results/thesis/` or `results/publication/`; the source-mode
gate fails the build if it is.
