#!/usr/bin/env bash
# Bring up the Tier-2 WLAN path: mac80211_hwsim virtual radios with hostapd
# (WPA2-Enterprise, EAP-TLS) and wpa_supplicant.
#
# SOFTWARE-BASED. Real IEEE 802.11 association and real EAP-TLS through the Linux
# mac80211/cfg80211 stack; simulated PHY, so no RF propagation or interference.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TIER2="$(dirname "${HERE}")"
OUT="${OUT_DIR:-/var/lib/ca-ztcf/tier2}"
AP_IF="${AP_IF:-wlan0}"
STA_IF="${STA_IF:-wlan1}"
AP_ADDR="${AP_ADDR:-192.168.70.1/24}"
STA_ADDR="${STA_ADDR:-192.168.70.10/24}"
CERTS="/etc/hostapd/certs"

sudo install -d -m 0775 "${OUT}" /var/run/hostapd /var/run/wpa_supplicant
EVENTS="${OUT}/wlan-events.jsonl"

log() { echo "[tier2-wlan] $*"; }
now() { date -u +%Y-%m-%dT%H:%M:%S.%6NZ; }

emit() {
  # emit <event_type> <outcome> <sta_mac> <peer_address> [identity]
  local identity_field=""
  [ -n "${5:-}" ] && identity_field=",\"eap_identity\":\"$5\""
  sudo tee -a "${EVENTS}" >/dev/null <<JSON
{"event_type":"$1","outcome":"$2","sta_mac":"$3","peer_address":"$4","observed_at":"$(now)","source_mode":"live_testbed","access_implementation":"mac80211_hwsim","testbed_type":"software_based","wifi_radio_mode":"mac80211_hwsim","akm":"WPA2-EAP","eap_method":"TLS","ssid":"ca-ztcf-tier2","ap_bssid":"02:00:00:00:00:00"${identity_field}}
JSON
}

log "loading virtual radios"
sudo modprobe -r mac80211_hwsim 2>/dev/null || true
sleep 1
sudo modprobe mac80211_hwsim radios=2
sleep 2
ip link show "${AP_IF}" >/dev/null 2>&1 || { log "FATAL: ${AP_IF} not created"; exit 2; }
ip link show "${STA_IF}" >/dev/null 2>&1 || { log "FATAL: ${STA_IF} not created"; exit 2; }
log "virtual radios present: $(ls /sys/class/ieee80211/ | tr '\n' ' ')"

log "generating research certificates"
sudo bash "${TIER2}/scripts/gen_wlan_certs.sh" "${CERTS}" >/dev/null
sudo mkdir -p /etc/wpa_supplicant/certs
sudo cp -f "${CERTS}"/* /etc/wpa_supplicant/certs/
sudo cp -f "${TIER2}/wlan/hostapd-hwsim.conf" /etc/hostapd/hostapd-hwsim.conf
sudo cp -f "${TIER2}/wlan/wpa_supplicant-hwsim.conf" /etc/wpa_supplicant/wpa_supplicant-hwsim.conf
printf '*\tTLS\n' | sudo tee /etc/hostapd/hostapd.eap_user >/dev/null

log "starting hostapd on ${AP_IF}"
# -x matches the executable name exactly, so these cannot match this script.
sudo pkill -x hostapd 2>/dev/null || true
sudo pkill -x wpa_supplicant 2>/dev/null || true
sleep 1
sudo ip addr flush dev "${AP_IF}" 2>/dev/null || true
sudo ip link set "${AP_IF}" up
sudo setsid bash -c "exec hostapd -dd /etc/hostapd/hostapd-hwsim.conf \
  > ${OUT}/hostapd.log 2>&1" < /dev/null > /dev/null 2>&1 &
disown 2>/dev/null || true
sleep 4
grep -q "AP-ENABLED" "${OUT}/hostapd.log" \
  && log "access point enabled" \
  || { log "FATAL: hostapd did not enable the AP"; tail -25 "${OUT}/hostapd.log"; exit 3; }
sudo ip addr add "${AP_ADDR}" dev "${AP_IF}" 2>/dev/null || true

log "associating ${STA_IF} with EAP-TLS in the ca-ztcf-sta namespace"
# The station's PHY moves into its own namespace so that traffic between the
# station and the access point genuinely crosses the 802.11 link instead of being
# delivered locally. See testbed/tier2/network/sta_path.sh.
associated=0
if bash "${TIER2}/network/sta_path.sh" associate "${STA_COUNT:-1}"; then
  associated=1
fi

STA_MAC=$(sudo ip netns exec ca-ztcf-sta cat "/sys/class/net/${STA_IF}/address")
if [ "${associated}" != "1" ]; then
  log "FATAL: station did not associate"
  emit "EAP_FAILURE" "FAILURE" "${STA_MAC}" "" "device@lab.invalid"
  tail -25 "${OUT}/wpa_supplicant.log"
  exit 4
fi

# The station address is assigned inside its namespace by sta_path.sh.
STA_IP=$(sudo ip netns exec ca-ztcf-sta ip -4 addr show "${STA_IF}" \
  | awk '/inet /{print $2}' | head -1 | cut -d/ -f1)

log "station associated and authenticated: mac=${STA_MAC} ip=${STA_IP}"
emit "STA_ASSOCIATED" "SUCCESS" "${STA_MAC}" "${STA_IP}" "device@lab.invalid"
emit "EAP_SUCCESS" "SUCCESS" "${STA_MAC}" "${STA_IP}" "device@lab.invalid"
emit "STA_AUTHENTICATED" "SUCCESS" "${STA_MAC}" "${STA_IP}" "device@lab.invalid"

log "WLAN path ready. events -> ${EVENTS}"
echo "STA_IP=${STA_IP}"
echo "STA_MAC=${STA_MAC}"
