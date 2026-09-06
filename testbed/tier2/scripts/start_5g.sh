#!/usr/bin/env bash
# Bring up the Tier-2 5G path: Open5GS core plus a UERANSIM gNB and UE.
#
# SOFTWARE-BASED. Real 5G NAS/NGAP/GTP-U, synthesised radio, no physical RF.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TIER2="$(dirname "${HERE}")"
UERANSIM="${UERANSIM:-/opt/UERANSIM/build}"
OUT="${OUT_DIR:-/var/lib/ca-ztcf/tier2}"
UE_COUNT="${UE_COUNT:-1}"

sudo mkdir -p "${OUT}"
EVENTS="${OUT}/nr-events.jsonl"

log() { echo "[tier2-5g] $*"; }
now() { date -u +%Y-%m-%dT%H:%M:%S.%6NZ; }

emit() {
  # emit <event_type> <supi> <peer_address> <extra_json_fields>
  # Provenance is fixed at the point of emission: this path can only ever be a
  # live software testbed observation, never a physical-radio measurement.
  sudo tee -a "${EVENTS}" >/dev/null <<JSON
{"event_type":"$1","supi":"$2","peer_address":"$3","observed_at":"$(now)","source_mode":"live_testbed","access_implementation":"ueransim","testbed_type":"software_based","5g_access_mode":"ueransim","dnn":"internet","gnb_id":"ueransim-gnb","pdu_session_id":"1","registration_state":"${4:-REGISTERED}","pdu_session_active":${5:-true}}
JSON
}

log "checking the 5G core"
for svc in nrfd scpd udrd udmd ausfd pcfd nssfd bsfd amfd smfd upfd; do
  state=$(systemctl is-active "open5gs-${svc}.service" 2>/dev/null || echo inactive)
  [ "${state}" = "active" ] || { log "FATAL: open5gs-${svc} is ${state}"; exit 2; }
done
log "all 5G network functions active"

log "starting UERANSIM gNB"
sudo pkill -f "nr-gnb" 2>/dev/null || true
sudo pkill -f "nr-ue" 2>/dev/null || true
sleep 1
sudo "${UERANSIM}/nr-gnb" -c "${TIER2}/ueransim/gnb.yaml" > "${OUT}/gnb.log" 2>&1 &
sleep 4
grep -q "NG Setup procedure is successful" "${OUT}/gnb.log" \
  && log "gNB registered with the AMF" \
  || { log "FATAL: NG setup did not complete"; tail -20 "${OUT}/gnb.log"; exit 3; }

log "starting UERANSIM UE (count=${UE_COUNT})"
sudo "${UERANSIM}/nr-ue" -c "${TIER2}/ueransim/ue.yaml" -n "${UE_COUNT}" \
  > "${OUT}/ue.log" 2>&1 &

for attempt in $(seq 1 30); do
  if ip link show uesimtun0 >/dev/null 2>&1; then break; fi
  sleep 1
done

if ! ip link show uesimtun0 >/dev/null 2>&1; then
  log "FATAL: uesimtun0 never appeared"
  tail -30 "${OUT}/ue.log"
  exit 4
fi

UE_IP=$(ip -4 addr show uesimtun0 | awk '/inet /{print $2}' | cut -d/ -f1)
SUPI=$(grep -oE "imsi-[0-9]+" "${OUT}/ue.log" | head -1)
log "UE registered: supi=${SUPI} uesimtun0=${UE_IP}"

emit "REGISTERED" "${SUPI}" "${UE_IP}" "REGISTERED" "true"
emit "SESSION_ESTABLISHED" "${SUPI}" "${UE_IP}" "REGISTERED" "true"

log "5G path ready. events -> ${EVENTS}"
echo "UE_IP=${UE_IP}"
echo "SUPI=${SUPI}"
