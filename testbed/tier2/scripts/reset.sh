#!/usr/bin/env bash
# Reset the Tier-2 testbed to a known state.
#
# Every experimental run must start from a known state. Stale state from a
# previous run is not merely untidy: a leftover access binding is attributed to
# whichever device claimed it first, so the next run's devices are correctly
# judged UNTRUSTED and the result looks like a framework fault.
#
# Reset covers: CA-ZTCF in-memory state, MQTT sessions, UERANSIM processes, WLAN
# association, Open5GS session state, transition counters and the audit run
# context.
set -uo pipefail

CORE_URL="${CORE_URL:-http://127.0.0.1:8080}"
OUT="${OUT_DIR:-/var/lib/ca-ztcf/tier2}"
KEEP_LOGS="${KEEP_LOGS:-0}"

log() { echo "[tier2-reset] $*"; }

log "stopping UERANSIM"
sudo pkill -f "nr-ue" 2>/dev/null || true
sudo pkill -f "nr-gnb" 2>/dev/null || true

log "stopping WLAN"
sudo pkill -f "wpa_supplicant .*wlan" 2>/dev/null || true
sudo pkill -f "hostapd .*hostapd-hwsim.conf" 2>/dev/null || true
sudo modprobe -r mac80211_hwsim 2>/dev/null || true

log "stopping the CA-ZTCF service stack"
sudo pkill -f "ca_ztcf.enforcement.service" 2>/dev/null || true
sudo pkill -f "uvicorn ca_ztcf" 2>/dev/null || true
sudo pkill -f "mosquitto -c" 2>/dev/null || true

log "clearing Open5GS session state"
# Subscriber records stay; only live session state is cleared, so provisioning
# does not have to be repeated between runs.
sudo systemctl restart open5gs-smfd open5gs-upfd open5gs-amfd 2>/dev/null || true

if [ "${KEEP_LOGS}" != "1" ]; then
  log "clearing captured event streams"
  sudo rm -f "${OUT}"/nr-events.jsonl "${OUT}"/wlan-events.jsonl \
             "${OUT}"/transitions.jsonl "${OUT}"/*.log 2>/dev/null || true
fi

log "waiting for the core to settle"
for _ in $(seq 1 20); do
  active=$(systemctl is-active open5gs-amfd 2>/dev/null || echo inactive)
  [ "${active}" = "active" ] && break
  sleep 1
done

log "reset complete"
for svc in nrfd amfd smfd upfd udrd udmd ausfd; do
  printf "  open5gs-%-6s %s\n" "${svc}" "$(systemctl is-active open5gs-${svc} 2>/dev/null)"
done
printf "  ueransim       %s\n" "$(pgrep -c nr-ue >/dev/null 2>&1 && echo running || echo stopped)"
printf "  virtual radios %s\n" "$(ls /sys/class/ieee80211/ 2>/dev/null | tr '\n' ' ' || echo none)"
