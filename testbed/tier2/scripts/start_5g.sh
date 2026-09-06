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

sudo install -d -m 0775 "${OUT}"
EVENTS="${OUT}/nr-events.jsonl"

log() { echo "[tier2-5g] $*"; }
now() { date -u +%Y-%m-%dT%H:%M:%S.%6NZ; }

emit() {
  # emit <event_type> <supi> <peer_address> <extra_json_fields>
  # Provenance is fixed at the point of emission: this path can only ever be a
  # live software testbed observation, never a physical-radio measurement.
  sudo tee -a "${EVENTS}" >/dev/null <<JSON
{"event_type":"$1","supi":"$2","peer_address":"$3","observed_at":"$(now)","source_mode":"live_testbed","access_implementation":"ueransim","testbed_type":"software_based","5g_access_mode":"ueransim","dnn":"internet","serving_node":"10.200.0.1","pdu_session_id":"1","registration_state":"${4:-REGISTERED}","pdu_session_active":${5:-true}}
JSON
}

log "checking the 5G core"
for svc in nrfd scpd udrd udmd ausfd pcfd nssfd bsfd amfd smfd upfd; do
  state=$(systemctl is-active "open5gs-${svc}.service" 2>/dev/null || echo inactive)
  [ "${state}" = "active" ] || { log "FATAL: open5gs-${svc} is ${state}"; exit 2; }
done
log "all 5G network functions active"

log "starting UERANSIM gNB"
# -x matches the executable name exactly; `pkill -f nr-gnb` would also match this
# script's own command line and kill the shell running it.
sudo pkill -x nr-gnb 2>/dev/null || true
sudo pkill -x nr-ue 2>/dev/null || true
sleep 1
# The gNB stays in the root namespace: NGAP and GTP-U terminate on the co-located
# AMF and UPF. Only its Radio Link Simulation endpoint faces the UE namespace.
sudo setsid bash -c "exec ${UERANSIM}/nr-gnb -c ${TIER2}/ueransim/gnb.yaml \
  > ${OUT}/gnb.log 2>&1" < /dev/null > /dev/null 2>&1 &
disown 2>/dev/null || true
sleep 5
grep -q "NG Setup procedure is successful" "${OUT}/gnb.log" \
  && log "gNB registered with the AMF" \
  || { log "FATAL: NG setup did not complete"; tail -20 "${OUT}/gnb.log"; exit 3; }

log "starting UERANSIM UE (count=${UE_COUNT}) in the ca-ztcf-ue namespace"
# The UE runs in its own network namespace so that application traffic can only
# reach the service through the UE tunnel. See testbed/tier2/network/ue_path.sh.
bash "${TIER2}/network/ue_path.sh" ensure "${UE_COUNT}" || {
  log "FATAL: the UE path did not come up"; exit 4; }

UE_IP=$(sudo ip netns exec ca-ztcf-ue ip -4 addr show uesimtun0 \
  | awk '/inet /{print $2}' | cut -d/ -f1)
SUPI=$(sudo grep -oE "imsi-[0-9]+" "${OUT}/ue.log" | head -1)
log "UE registered: supi=${SUPI} uesimtun0=${UE_IP}"

emit "REGISTERED" "${SUPI}" "${UE_IP}" "REGISTERED" "true"
emit "SESSION_ESTABLISHED" "${SUPI}" "${UE_IP}" "REGISTERED" "true"

log "5G path ready. events -> ${EVENTS}"
echo "UE_IP=${UE_IP}"
echo "SUPI=${SUPI}"
