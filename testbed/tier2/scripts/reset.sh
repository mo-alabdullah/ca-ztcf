#!/usr/bin/env bash
# Reset the Tier-2 testbed to a known state.
#
# Every run must start from a known state. Stale state is not merely untidy: an
# access binding is attributed to whichever device claimed it first, so a leftover
# binding makes the next run's devices correctly UNTRUSTED and the result looks
# like a framework fault when it is a testbed hygiene fault.
#
# Two levels:
#   soft (default)  clear CA-ZTCF service state only. The 5G and WLAN access paths
#                   stay up, so repetitions of a scenario start clean without
#                   paying for a full re-registration and re-association.
#   full            also tear down the access paths, the namespaces and the
#                   virtual radios, back to a freshly provisioned VM.
#
# Note on pkill: patterns match the executable name (-x) or a pattern that cannot
# match this script's own command line. `pkill -f nr-ue` would match the shell
# running this script and kill it.
set -uo pipefail

MODE="${1:-soft}"
CORE_URL="${CORE_URL:-http://127.0.0.1:8080}"
OUT="${OUT_DIR:-/var/lib/ca-ztcf/tier2}"
TIER2="${TIER2:-/opt/ca-ztcf/testbed/tier2}"
KEEP_LOGS="${KEEP_LOGS:-0}"

log() { echo "[tier2-reset] $*"; }

log "stopping the CA-ZTCF service stack"
sudo pkill -f "ca_ztcf[.]enforcement[.]service" 2>/dev/null || true
sudo pkill -f "uvicorn ca_ztcf[.]api" 2>/dev/null || true
sudo pkill -x mosquitto 2>/dev/null || true
sleep 1

# The core holds the device registry, the binding store, the trust states and the
# transition counters in memory, so restarting it is the reset.
log "restarting the CA-ZTCF service stack"
bash "${TIER2}/scripts/start_services.sh" >/dev/null 2>&1 || {
  log "FATAL: the service stack did not come back"; exit 2; }

if [ "${MODE}" = "full" ]; then
  log "stopping UERANSIM and tearing down the UE path"
  bash "${TIER2}/network/ue_path.sh" teardown 2>/dev/null || true
  sudo pkill -x nr-gnb 2>/dev/null || true

  log "tearing down the station path"
  bash "${TIER2}/network/sta_path.sh" teardown 2>/dev/null || true
  sudo pkill -x hostapd 2>/dev/null || true
  sudo modprobe -r mac80211_hwsim 2>/dev/null || true

  log "clearing Open5GS session state"
  # Subscriber records stay; only live session state is cleared, so provisioning
  # does not have to be repeated between runs.
  sudo systemctl restart open5gs-smfd open5gs-upfd open5gs-amfd 2>/dev/null || true
  for _ in $(seq 1 20); do
    [ "$(systemctl is-active open5gs-amfd 2>/dev/null)" = "active" ] && break
    sleep 1
  done
fi

if [ "${KEEP_LOGS}" != "1" ] && [ "${MODE}" = "full" ]; then
  log "clearing captured event streams"
  sudo rm -f "${OUT}"/nr-events.jsonl "${OUT}"/wlan-events.jsonl \
             "${OUT}"/transitions.jsonl "${OUT}"/*.log 2>/dev/null || true
fi

log "reset complete (${MODE})"
printf "  ca-ztcf core   %s\n" \
  "$(curl -fsS "${CORE_URL}/healthz" >/dev/null 2>&1 && echo healthy || echo down)"
printf "  bindings held  %s\n" \
  "$(curl -fsS "${CORE_URL}/v1/collectors/bindings" 2>/dev/null | grep -o binding_id | wc -l | tr -d ' ')"
for svc in nrfd amfd smfd upfd udrd udmd ausfd; do
  printf "  open5gs-%-6s %s\n" "${svc}" "$(systemctl is-active open5gs-${svc} 2>/dev/null)"
done
printf "  ueransim ue    %s\n" "$(pgrep -x nr-ue >/dev/null 2>&1 && echo running || echo stopped)"
printf "  ueransim gnb   %s\n" "$(pgrep -x nr-gnb >/dev/null 2>&1 && echo running || echo stopped)"
printf "  virtual radios %s\n" "$(ls /sys/class/ieee80211/ 2>/dev/null | tr '\n' ' ' || echo none)"
printf "  ue namespace   %s\n" "$(sudo ip netns list 2>/dev/null | grep -qw ca-ztcf-ue && echo present || echo absent)"
printf "  sta namespace  %s\n" "$(sudo ip netns list 2>/dev/null | grep -qw ca-ztcf-sta && echo present || echo absent)"
