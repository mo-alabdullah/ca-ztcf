#!/usr/bin/env bash
# Run the Tier-1 portable 802.1X/EAP-TLS WLAN authentication-path emulation.
#
# Creates a veth pair, runs hostapd (driver=wired) as authenticator on one end and
# wpa_supplicant (-Dwired) as supplicant on the other, exercises the configured
# scenarios, and writes normalised authentication events as JSON Lines.
#
# This is NOT IEEE 802.11 radio access. Events carry
# source_mode=tier1_wlan_auth_emulation.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="${OUT_DIR:-/artifacts/tier1-wlan}"
CERTS="${CERTS_DIR:-/etc/hostapd/certs}"
AUTH_IF="${AUTH_IF:-eapauth0}"
STA_IF="${STA_IF:-eapsta0}"
STA_MAC="${STA_MAC:-02:00:00:00:00:11}"
SCENARIOS="${SCENARIOS:-valid reauth rogue expired no_cert disconnect}"
SETTLE="${SETTLE:-4}"

mkdir -p "${OUT}" /var/run/hostapd /var/run/wpa_supplicant
EVENTS="${OUT}/events.jsonl"
: > "${EVENTS}"
HOSTAPD_LOG="${OUT}/hostapd.log"
SUPPLICANT_LOG="${OUT}/wpa_supplicant.log"

log()  { echo "[tier1-wlan] $*"; }
now()  { date -u +%Y-%m-%dT%H:%M:%S.%6NZ; }

emit() {
  # emit <event_type> <scenario> <outcome> [identity]
  # Written with printf so the testbed container needs no interpreter at all.
  # source_mode is fixed here: this environment can only ever produce Tier-1
  # authentication-path evidence, never a live_testbed measurement.
  local identity_field=""
  [ -n "${4:-}" ] && identity_field=",\"eap_identity\":\"$4\""
  printf '{"event_type":"%s","scenario":"%s","outcome":"%s","sta_mac":"%s","observed_at":"%s","source_mode":"tier1_wlan_auth_emulation","authenticator":"hostapd-driver-wired","supplicant":"wpa_supplicant-Dwired","eap_method":"TLS"%s}\n' \
    "$1" "$2" "$3" "${STA_MAC}" "$(now)" "${identity_field}" >> "${EVENTS}"
}

cleanup() {
  pkill -f "wpa_supplicant .*${STA_IF}" 2>/dev/null || true
  pkill -f "hostapd .*hostapd.conf" 2>/dev/null || true
  ip link del "${AUTH_IF}" 2>/dev/null || true
}
trap cleanup EXIT

log "creating veth pair ${AUTH_IF} <-> ${STA_IF}"
ip link del "${AUTH_IF}" 2>/dev/null || true
if ! ip link add "${AUTH_IF}" type veth peer name "${STA_IF}"; then
  log "FATAL: cannot create a veth pair (needs CAP_NET_ADMIN)"
  emit "ENVIRONMENT_ERROR" "setup" "FAILURE" ""
  exit 2
fi
ip link set "${STA_IF}" address "${STA_MAC}" 2>/dev/null || true
ip link set "${AUTH_IF}" up
ip link set "${STA_IF}" up

log "starting hostapd (driver=wired) on ${AUTH_IF}"
hostapd -dd /etc/hostapd/hostapd.conf > "${HOSTAPD_LOG}" 2>&1 &
HOSTAPD_PID=$!
sleep 2
if ! kill -0 "${HOSTAPD_PID}" 2>/dev/null; then
  log "FATAL: hostapd exited immediately; see ${HOSTAPD_LOG}"
  tail -30 "${HOSTAPD_LOG}" || true
  emit "ENVIRONMENT_ERROR" "hostapd" "FAILURE" ""
  exit 3
fi
log "hostapd running (pid ${HOSTAPD_PID})"

run_supplicant() {
  # run_supplicant <scenario> <config> <expected: SUCCESS|FAILURE>
  local scenario="$1" config="$2" expected="$3"
  # Reset the 802.1X port state so each scenario starts from a clean
  # authenticator state rather than inheriting the previous scenario's outcome.
  ip link set "${STA_IF}" down 2>/dev/null || true
  sleep 0.5
  ip link set "${STA_IF}" up 2>/dev/null || true
  sleep 0.5

  local marker
  marker=$(wc -l < "${HOSTAPD_LOG}")

  log "scenario '${scenario}' (expecting ${expected})"
  timeout "${SETTLE}" wpa_supplicant -Dwired -i "${STA_IF}" -c "${config}" -dd \
    >> "${SUPPLICANT_LOG}" 2>&1
  local rc=$?

  local slice
  slice=$(tail -n +"${marker}" "${HOSTAPD_LOG}")
  # The EAP identity comes from the certificate subject, which the supplicant
  # config declares; hostapd's hexdump form is not worth parsing.
  local identity="${EXPECT_IDENTITY:-}"

  if printf '%s' "${slice}" | grep -q "CTRL-EVENT-EAP-SUCCESS\|IEEE 802.1X: authenticated"; then
    emit "EAP_SUCCESS" "${scenario}" "SUCCESS" "${identity}"
    emit "STA_AUTHENTICATED" "${scenario}" "SUCCESS" "${identity}"
    log "  -> EAP success"
    return 0
  fi
  # No successful authentication. Whether hostapd logged an explicit failure or
  # the exchange simply never completed, the authenticator did not authenticate
  # this station, and that is recorded as a failure rather than quietly dropped.
  emit "EAP_FAILURE" "${scenario}" "FAILURE" "${identity}"
  log "  -> EAP failure (supplicant rc=${rc})"
  return 1
}

for scenario in ${SCENARIOS}; do
  case "${scenario}" in
    valid)  EXPECT_IDENTITY="device@lab.invalid" run_supplicant valid  /etc/wpa_supplicant/wpa_supplicant.conf       SUCCESS ;;
    reauth) EXPECT_IDENTITY="device@lab.invalid" run_supplicant reauth /etc/wpa_supplicant/wpa_supplicant.conf       SUCCESS ;;
    rogue)  EXPECT_IDENTITY="rogue@lab.invalid"  run_supplicant rogue  /etc/wpa_supplicant/wpa_supplicant_rogue.conf FAILURE ;;
    expired)
      if [ -f "${CERTS}/expired-client.crt" ]; then
        EXPECT_IDENTITY="expired@lab.invalid" run_supplicant expired /etc/wpa_supplicant/wpa_supplicant_expired.conf FAILURE
      else
        log "scenario 'expired' skipped: no backdated certificate available"
        emit "SCENARIO_SKIPPED" expired "SKIPPED" ""
      fi ;;
    no_cert)
      cat > /tmp/wpa_no_cert.conf <<'CONF'
ctrl_interface=/var/run/wpa_supplicant
ap_scan=0
network={
    key_mgmt=IEEE8021X
    eap=TLS
    identity="nocert@lab.invalid"
    ca_cert="/etc/wpa_supplicant/certs/ca.crt"
    eapol_flags=0
}
CONF
      EXPECT_IDENTITY="nocert@lab.invalid" run_supplicant no_cert /tmp/wpa_no_cert.conf FAILURE ;;
    disconnect)
      ip link set "${STA_IF}" down
      sleep 1
      emit "STA_DISCONNECTED" disconnect "SUCCESS" ""
      ip link set "${STA_IF}" up
      log "  -> station disconnected" ;;
    *) log "unknown scenario '${scenario}', skipping" ;;
  esac
done

log "events written to ${EVENTS}"
wc -l "${EVENTS}"
