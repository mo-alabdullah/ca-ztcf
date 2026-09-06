# Experimental limitations

> **FINAL THESIS EXPERIMENTAL EVIDENCE. Tier-2 live software-based testbed: real 5G NAS/NGAP/GTP-U via Open5GS and UERANSIM, and a real IEEE 802.11 association and EAP-TLS exchange via mac80211_hwsim, over simulated radios. Not an RF, propagation, interference, channel-quality, spectrum-coexistence or physical-handover measurement. Generated from results/final/raw/; no value was typed by hand.**

These are the boundaries of what the evidence in `results/final/` can support.
They are stated plainly because the value of the result depends on them being
understood, not on them being small.

## The testbed has no physical radio

Tier 2 is a **reproducible software-based 5G/WiFi coexistence testbed**. Every
protocol interaction is real; every radio is simulated.

- **UERANSIM is a software UE and gNB.** It speaks real 5G NAS, NGAP and GTP-U to
  Open5GS, and it synthesises the radio. It is not a commercial or physical 5G
  RAN, and no measurement from it describes one.
- **`mac80211_hwsim` is a simulated PHY.** The IEEE 802.11 association, the RSN
  four-way handshake and the EAP-TLS exchange are the real Linux implementations;
  the propagation is not real at all.

Nothing in these results supports a claim about RF propagation, physical radio
handover performance, interference, signal strength, spectrum efficiency,
channel-quality behaviour, or performance on a production mobile network.

## Scalability is logical, and bounded at 25

The maximum validated count is **25 logical devices**. Each has a distinct
service-domain identity, a distinct 5G address and access binding, a distinct WLAN
logical address and binding, a distinct MQTT session and a distinct audit trail.

**The 25 WLAN addresses share one IEEE 802.11 association.** E13 therefore
measures CA-ZTCF logical and service-domain scalability. It does **not** measure
independent WiFi-radio association scalability, and a run with 25 separate radio
associations would need 25 virtual radios and 25 supplicants, which was not
validated.

E13 declares 50 and 100 as possible future levels. They were **not run**. Nothing
here may be extrapolated to 50, 100 or 1000 devices.

## Transition rates are bounded by what was validated

E14 reports the four rates already validated: 1, 5, 10 and 25 transitions per
second. No higher rate was introduced to find a failure point, so no failure point
is claimed and no behaviour beyond 25 per second is described.

## Timing is single-host

Everything runs in one virtual machine on one host. Latency figures are influenced
by host scheduling, and they are software-testbed timings rather than the timings
of a distributed production deployment. The separate timing quantities — access
authentication, path switch, trust decision, application recovery and end-to-end
transition — are reported separately and must not be conflated. In the transition
records, `T4` to `T5` includes agent process start-up and is **not** a trust
decision time.

## Resource figures measure the experiment process

CPU and memory are sampled from the process that runs the trust function together
with the scenario driver. **They are not an IoT device measurement**: the device
agent is a separate process and, on Tier 2, lives in another network namespace. No
figure here describes what CA-ZTCF costs a constrained device.

## Two metrics were not measured

**Bytes exchanged (M9).** The metric counts bytes on the
device-to-enforcement-point socket. The experiment runner drives the framework in
process, so no such socket exists and the counter was never recorded in any of the
2160 runs. The byte-overhead half of P5 is unanswered by this campaign; message
counts were recorded and are reported.

**Trust engine evaluation time for the baselines (M12).** Neither baseline has a
trust engine, so the metric exists only for CA-ZTCF. It is reported descriptively
and no three-way comparison of it is possible.

## Token lifetime sensitivity is partly untested

Seven of the nine sensitivity scenarios span less scenario time than the shortest
token lifetime tested, so no token could expire in them and nothing was learned
about the lifetime there. The two that do outlast a 30-second token show no
difference at any lifetime — which is a result, but it rests on two scenarios
rather than nine.

## The 5G collector is version-specific

Access-context evidence is parsed from Open5GS 2.8.0's own log output. The parsing
follows what a running core actually emits, which is why `gnb_id` was corrected to
a serving-node address (ADR-0008). Another core, or another Open5GS release, needs
its own adapter, and posture policy constrains a serving-node address rather than
a cell identity.

## Adversarial conditions are injected by the harness

E06 to E10 and E15 apply their manipulations on top of real observations, and each
such event is marked. No access network can be asked to emit a genuinely malicious
event, so the adversary is modelled rather than observed. Ground truth is fixed by
the scenario before the run and is never derived from a CA-ZTCF decision.

## A laboratory is not a deployment

PLMN 999/70 is the 3GPP-reserved test network and the subscriber keys are
published Open5GS laboratory vectors. The workload is a controlled scenario set,
not production traffic. Nothing here establishes how the framework behaves under
an operator's real subscriber population, traffic mix or attack surface.
