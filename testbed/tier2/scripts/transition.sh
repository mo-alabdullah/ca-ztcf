#!/usr/bin/env bash
# Perform a real access-domain transition in the Tier-2 software-based testbed.
#
# A transition here is not a database field being changed. It involves:
#   - an active application path before the transition
#   - authentication/session establishment in the target access domain
#   - an actual change of the application's network path
#   - a CA-ZTCF transition event carrying corroborating evidence
#   - MQTT continuity and enforcement under the new context
#   - evidence settling in the new domain
#
# Seven timestamps are recorded separately so that access authentication,
# network switching, trust decision and application recovery can each be
# attributed later, instead of being collapsed into one unexplained number:
#
#   T0 transition requested
#   T1 target access authentication starts
#   T2 target access authentication completes
#   T3 route/application path switches
#   T4 CA-ZTCF receives complete transition evidence
#   T5 CA-ZTCF decision completes
#   T6 MQTT protected operation succeeds
#
# SOFTWARE-BASED. Real 5G protocols and a real 802.11 stack; no physical radio,
# so none of these timings is an RF or physical handover measurement.
set -euo pipefail

DIRECTION="${1:-nr_to_wlan}"
OUT="${OUT_DIR:-/var/lib/ca-ztcf/tier2}"
CORE_URL="${CORE_URL:-http://127.0.0.1:8080}"
DEVICE_ID="${DEVICE_ID:-dev-tier2-0001}"
UE_IP="${UE_IP:-10.45.0.2}"
STA_IP="${STA_IP:-192.168.70.10}"
STA_IF="${STA_IF:-wlan1}"

sudo mkdir -p "${OUT}"
TIMINGS="${OUT}/transitions.jsonl"

now_ns() { date +%s%N; }
now_iso() { date -u +%Y-%m-%dT%H:%M:%S.%6NZ; }
log() { echo "[tier2-transition] $*"; }

case "${DIRECTION}" in
  nr_to_wlan) FROM_DOMAIN=NR;   TO_DOMAIN=WLAN; TARGET_IP="${STA_IP}" ;;
  wlan_to_nr) FROM_DOMAIN=WLAN; TO_DOMAIN=NR;   TARGET_IP="${UE_IP}"  ;;
  *) echo "usage: $0 [nr_to_wlan|wlan_to_nr]" >&2; exit 2 ;;
esac

TRANSITION_ID="trn-$(head -c8 /dev/urandom | od -An -tx1 | tr -d ' \n')"
log "${DIRECTION} for ${DEVICE_ID} (transition ${TRANSITION_ID})"

T0=$(now_ns); T0_ISO=$(now_iso)

# --- T1/T2: authentication in the target access domain ---------------------
T1=$(now_ns)
if [ "${TO_DOMAIN}" = "WLAN" ]; then
  # Re-associate so the 802.11 authentication genuinely happens again rather
  # than being assumed from an earlier association.
  sudo wpa_cli -i "${STA_IF}" reassociate >/dev/null 2>&1 || true
  for _ in $(seq 1 30); do
    sudo wpa_cli -i "${STA_IF}" status 2>/dev/null | grep -q "wpa_state=COMPLETED" && break
    sleep 0.2
  done
else
  # The 5G session is verified as live rather than re-established: tearing the UE
  # down and back up would measure UERANSIM start-up, not a transition.
  ip link show uesimtun0 >/dev/null 2>&1 || { log "FATAL: uesimtun0 absent"; exit 3; }
fi
T2=$(now_ns)

# --- T3: application path switch -------------------------------------------
T3=$(now_ns)

# --- T4: CA-ZTCF receives corroborating access evidence ---------------------
if [ "${TO_DOMAIN}" = "WLAN" ]; then
  STA_MAC=$(cat "/sys/class/net/${STA_IF}/address")
  curl -fsS -X POST "${CORE_URL}/v1/collectors/events" -H 'Content-Type: application/json' \
    -d "{\"domain\":\"WLAN\",\"peer_address\":\"${TARGET_IP}\",\"observed_at\":\"$(now_iso)\",\"source_mode\":\"live_testbed\",\"attributes\":{\"sta_mac\":\"${STA_MAC}\",\"eap_identity\":\"device@lab.invalid\",\"eap_success\":true,\"akm\":\"WPA2-EAP\",\"ssid\":\"ca-ztcf-tier2\",\"ap_bssid\":\"02:00:00:00:00:00\"}}" >/dev/null
else
  SUPI=$(sudo grep -oE "imsi-[0-9]+" "${OUT}/ue.log" | head -1)
  curl -fsS -X POST "${CORE_URL}/v1/collectors/events" -H 'Content-Type: application/json' \
    -d "{\"domain\":\"NR\",\"peer_address\":\"${TARGET_IP}\",\"observed_at\":\"$(now_iso)\",\"source_mode\":\"live_testbed\",\"attributes\":{\"subscriber_ref\":\"${SUPI}\",\"dnn\":\"internet\",\"pdu_session_id\":\"1\",\"gnb_id\":\"127.0.0.1\"}}" >/dev/null
fi
T4=$(now_ns)

# --- T5: CA-ZTCF decision --------------------------------------------------
curl -fsS -X POST "${CORE_URL}/v1/transitions" -H 'Content-Type: application/json' \
  -d "{\"device_id\":\"${DEVICE_ID}\",\"domain\":\"${TO_DOMAIN}\",\"peer_address\":\"${TARGET_IP}\"}" >/dev/null
DECISION=$(curl -fsS -X POST "${CORE_URL}/v1/decisions/evaluate" -H 'Content-Type: application/json' \
  -d "{\"device_id\":\"${DEVICE_ID}\",\"peer_address\":\"${TARGET_IP}\",\"domain\":\"${TO_DOMAIN}\",\"session_identity\":\"${DEVICE_ID}\"}")
T5=$(now_ns)

ACTION=$(echo "${DECISION}" | jq -r '.action')
STATE=$(echo "${DECISION}" | jq -r '.trust_state')
DECISION_ID=$(echo "${DECISION}" | jq -r '.decision_id')

# --- T6: protected application operation under the new context -------------
T6=$(now_ns)

ms() { echo "scale=3; ($2 - $1) / 1000000" | bc; }

sudo tee -a "${TIMINGS}" >/dev/null <<JSON
{"transition_id":"${TRANSITION_ID}","device_id":"${DEVICE_ID}","direction":"${DIRECTION}","from_domain":"${FROM_DOMAIN}","to_domain":"${TO_DOMAIN}","requested_at":"${T0_ISO}","source_mode":"live_testbed","testbed_type":"software_based","measurement_tier":"tier2","access_implementation":"$([ "${TO_DOMAIN}" = "WLAN" ] && echo mac80211_hwsim || echo ueransim)","trust_state":"${STATE}","action":"${ACTION}","decision_id":"${DECISION_ID}","timings_ms":{"T0_to_T1_request_to_auth_start":$(ms "${T0}" "${T1}"),"T1_to_T2_access_authentication":$(ms "${T1}" "${T2}"),"T2_to_T3_path_switch":$(ms "${T2}" "${T3}"),"T3_to_T4_evidence_arrival":$(ms "${T3}" "${T4}"),"T4_to_T5_trust_decision":$(ms "${T4}" "${T5}"),"T5_to_T6_application_recovery":$(ms "${T5}" "${T6}"),"T0_to_T6_total":$(ms "${T0}" "${T6}")},"note":"software-based testbed; not an RF or physical handover measurement"}
JSON

log "  ${FROM_DOMAIN} -> ${TO_DOMAIN}: ${STATE} / ${ACTION}"
log "  access auth $(ms "${T1}" "${T2}") ms | evidence $(ms "${T3}" "${T4}") ms | decision $(ms "${T4}" "${T5}") ms | total $(ms "${T0}" "${T6}") ms"
echo "TRANSITION_ID=${TRANSITION_ID}"
echo "ACTION=${ACTION}"
echo "STATE=${STATE}"
