# ADR-0003: A two-tier testbed

- Status: Accepted
- Date: 2026-09-06

## Context

Real 802.11 emulation requires the `mac80211_hwsim` kernel module. Verified on the development machine on
2026-09-06: Docker Desktop's kernel (`7.0.12-linuxkit`) has no `/lib/modules` at all, and the available OrbStack
machine (`7.0.14-orbstack`) has `cfg80211` loaded but not `mac80211_hwsim`. Neither can host real virtual WiFi radios.

Making the entire experimental programme depend on a kernel module that is unavailable on the primary development
machine would be a single point of failure for the whole thesis.

## Decision

Two tiers, feeding the same collectors, engine, policy, enforcement point and metrics.

**Tier 1 — portable.** Runs anywhere, including CI. Access domains are network namespaces joined by veth pairs.
The WLAN side is a **portable 802.1X/EAP-TLS authentication-path emulation for WLAN security-context generation**
(`hostapd driver=wired` authenticator with a `wpa_supplicant -Dwired` supplicant). The 5G side uses a schema-faithful
synthetic fixture provider until a Tier-2 capture exists (see ADR-0006).

**Tier 2 — integration.** A Linux host or VM with a real Open5GS core, UERANSIM gNB and UE, and `mac80211_hwsim`
radios driving hostapd and wpa_supplicant.

## Consequences

**Positive.** Batches A–F carry no kernel or hardware risk. Tier 1 exercises genuine EAP authentication, genuine
authenticator events, genuine identity binding and the complete CA-ZTCF integration path.

**Negative and binding.** Tier 1 **cannot** measure WiFi association latency, RF behaviour, 802.11 radio transition
latency or interference. Those require Tier 2. Tier-1 and Tier-2 claims must never be mixed, and no Tier-1
measurement may be described as a WiFi radio measurement. Every result record carries its tier.
