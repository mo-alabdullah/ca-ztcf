#!/usr/bin/env bash
# Deterministic WLAN application path for the Tier-2 software-based testbed.
#
# THE PROBLEM THIS SOLVES
# -----------------------
# The station and the access point are two virtual radios on one host. With both
# in the same network namespace, the station address and the AP address are both
# local addresses, so a connection between them is delivered over the loopback
# path and never crosses the 802.11 link at all. The association and the EAP-TLS
# exchange are real, but the application traffic that CA-ZTCF observes would not
# have travelled over the access technology it is being attributed to.
#
# This is the same defect as the co-located 5G user plane, and it gets the same
# treatment.
#
# THE FIX
# -------
# Move the station's PHY into its own network namespace. mac80211_hwsim still
# carries the frames between the two radios, so association, the RSN four-way
# handshake and EAP-TLS are unchanged, but the AP address is now genuinely remote
# and the only route to it is over the wireless link.
#
#   root namespace                     ca-ztcf-sta namespace
#   ---------------------------        ---------------------------
#   phy(AP)  wlan0 192.168.70.1  <-802.11 over mac80211_hwsim->  wlanN 192.168.70.10+
#   hostapd (WPA2-EAP / EAP-TLS)       wpa_supplicant (EAP-TLS)
#   CA-ZTCF PEP / core / broker
#
# SOFTWARE-BASED TESTBED. Real IEEE 802.11 and real EAP-TLS through the Linux
# mac80211/cfg80211 stack over a simulated PHY. No physical radio: nothing here is
# an RF, propagation, interference or channel-quality measurement.
#
# All subcommands are idempotent.
set -euo pipefail

NS="${STA_NETNS:-ca-ztcf-sta}"
STA_IF="${STA_IF:-wlan1}"
AP_IF="${AP_IF:-wlan0}"
STA_ADDR="${STA_ADDR:-192.168.70.10}"
STA_PREFIX="${STA_PREFIX:-24}"
WLAN_NET="${WLAN_NET:-192.168.70.0/24}"
OUT="${OUT_DIR:-/var/lib/ca-ztcf/tier2}"
WPA_CONF="${WPA_CONF:-/etc/wpa_supplicant/wpa_supplicant-hwsim.conf}"

log() { echo "[sta-path] $*"; }
nsx() { sudo ip netns exec "${NS}" "$@"; }

# The station interface may already have been moved. Report where it is.
locate_sta() {
  if ip link show "${STA_IF}" >/dev/null 2>&1; then echo root; return; fi
  if sudo ip netns list 2>/dev/null | grep -qw "${NS}" \
     && nsx ip link show "${STA_IF}" >/dev/null 2>&1; then echo ns; return; fi
  echo missing
}

setup() {
  sudo install -d -m 0775 "${OUT}"
  sudo ip netns list | grep -qw "${NS}" || sudo ip netns add "${NS}"
  nsx ip link set lo up

  case "$(locate_sta)" in
    root)
      # A wireless interface cannot be moved with `ip link set netns`; the whole
      # PHY has to move, and every interface on it moves with it.
      local phy
      phy=$(cat "/sys/class/net/${STA_IF}/phy80211/name")
      log "moving ${phy} (${STA_IF}) into ${NS}"
      sudo pkill -f "wpa_supplicant .*${STA_IF}" 2>/dev/null || true
      sleep 1
      sudo iw phy "${phy}" set netns name "${NS}"
      ;;
    ns) log "${STA_IF} already in ${NS}" ;;
    missing) log "FATAL: ${STA_IF} exists in neither namespace"; return 2 ;;
  esac

  nsx ip link set "${STA_IF}" up
  log "namespace ${NS} ready"
}

associate() {
  # Restart the supplicant inside the namespace so the association and the
  # EAP-TLS exchange genuinely happen there.
  nsx pkill -x wpa_supplicant 2>/dev/null || true
  sleep 1
  sudo setsid bash -c "exec ip netns exec ${NS} wpa_supplicant -Dnl80211 -i ${STA_IF} \
    -c ${WPA_CONF} -dd > ${OUT}/wpa_supplicant.log 2>&1" \
    < /dev/null > /dev/null 2>&1 &
  disown 2>/dev/null || true

  local ok=0
  for _ in $(seq 1 60); do
    if nsx iw dev "${STA_IF}" link 2>/dev/null | grep -q "Connected to"; then ok=1; break; fi
    sleep 1
  done
  [ "${ok}" = "1" ] || { log "FATAL: station did not associate"; tail -30 "${OUT}/wpa_supplicant.log"; return 3; }

  nsx ip addr replace "${STA_ADDR}/${STA_PREFIX}" dev "${STA_IF}"
  log "associated; ${STA_IF} = ${STA_ADDR}"
  nsx iw dev "${STA_IF}" link | sed 's/^/  /' | head -4
}

addresses() {
  # Extra station addresses for multi-device runs. Each Tier-2 device binds its
  # own source address, so no two devices can present the same identity to the
  # enforcement point.
  local count="${1:-1}" base i
  base="${STA_ADDR%.*}"
  local last="${STA_ADDR##*.}"
  for i in $(seq 0 $((count - 1))); do
    nsx ip addr replace "${base}.$((last + i))/${STA_PREFIX}" dev "${STA_IF}"
  done
  log "${count} station address(es) from ${STA_ADDR}"
}

status() {
  echo "--- ${NS} addresses ---"; nsx ip -br addr
  echo "--- ${NS} routes ---"; nsx ip route
  echo "--- link ---"; nsx iw dev "${STA_IF}" link 2>&1 | head -5
  echo "--- AP side (root) ---"; ip -br addr show "${AP_IF}"; sudo iw dev "${AP_IF}" station dump | head -3
}

teardown() {
  nsx pkill -x wpa_supplicant 2>/dev/null || true
  if [ "$(locate_sta)" = "ns" ]; then
    local phy
    phy=$(nsx cat "/sys/class/net/${STA_IF}/phy80211/name")
    sudo ip netns exec "${NS}" iw phy "${phy}" set netns 1 2>/dev/null || true
  fi
  sudo ip netns list | grep -qw "${NS}" && sudo ip netns del "${NS}" || true
  log "torn down"
}

case "${1:-}" in
  setup)     setup ;;
  associate) setup; associate; addresses "${2:-1}" ;;
  addresses) addresses "${2:-1}" ;;
  status)    status ;;
  teardown)  teardown ;;
  *) echo "usage: $0 {setup|associate [N]|addresses N|status|teardown}" >&2; exit 2 ;;
esac
