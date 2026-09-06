#!/usr/bin/env bash
# Deterministic 5G application path for the Tier-2 software-based testbed.
#
# THE PROBLEM THIS SOLVES
# -----------------------
# The UERANSIM UE and the Open5GS core are co-located in one VM. When the UE and
# the CA-ZTCF service share a network namespace, every service address is also a
# local address, so the kernel answers from the local table and the connection
# never reaches GTP-U at all. The enforcement point then observes the VM's own
# address (192.168.5.15) instead of the UE tunnel address, and the live 5G access
# binding can never be correlated with the application connection.
#
# LD_PRELOAD (UERANSIM's nr-binder) does not fix this: it can force SO_BINDTODEVICE
# onto a socket, but a locally-routed destination still short-circuits, and the
# interception is not reliable for sockets created by CPython's asyncio.
#
# THE FIX
# -------
# Run the UE in its own network namespace and put the service on an address that
# is only reachable from that namespace through the UE tunnel.
#
#   root namespace                       ca-ztcf-ue namespace
#   ------------------------------       -----------------------------
#   nr-gnb   RLS on 10.200.0.1  <--veth--> 10.200.0.2  (uectl1)
#            NGAP -> 127.0.0.5
#            GTP-U <-> 127.0.0.7
#   open5gs-upfd -> ogstun 10.45.0.1/16
#   ztcfsvc0 (dummy) 10.99.0.1/32        uesimtunN 10.45.0.N/32
#   CA-ZTCF PEP / core / broker           route 10.99.0.0/24 dev uesimtunN
#
# Uplink:   agent -> uesimtunN -> RLS -> gNB -> GTP-U -> UPF -> ogstun
#           -> destination 10.99.0.1 is local -> delivered with source 10.45.0.N
# Downlink: reply from 10.99.0.1 -> route 10.45.0.0/16 dev ogstun -> UPF -> GTP-U -> UE
#
# 10.99.0.1 is delivered locally, so it never traverses nat POSTROUTING and is
# never masqueraded. A RETURN rule ahead of the Open5GS MASQUERADE rule states
# that invariant explicitly so it survives any future routing change.
#
# The control veth carries the Radio Link Simulation protocol only. Everything
# else leaving it is rejected inside the namespace, so there is no quiet fallback
# path to a service that also listens on 0.0.0.0.
#
# SOFTWARE-BASED TESTBED. Real 5G NAS/NGAP/GTP-U over a synthesised radio. No
# physical RF, and nothing here is an RF or physical-handover measurement.
#
# All subcommands are idempotent.
set -euo pipefail

NS="${UE_NETNS:-ca-ztcf-ue}"
VETH_ROOT="${VETH_ROOT:-uectl0}"
VETH_NS="${VETH_NS:-uectl1}"
VETH_ROOT_ADDR="${VETH_ROOT_ADDR:-10.200.0.1}"
VETH_NS_ADDR="${VETH_NS_ADDR:-10.200.0.2}"
VETH_PREFIX="${VETH_PREFIX:-30}"
SVC_IF="${SVC_IF:-ztcfsvc0}"
SVC_ADDR="${SVC_ADDR:-10.99.0.1}"
SVC_NET="${SVC_NET:-10.99.0.0/24}"
UE_NET="${UE_NET:-10.45.0.0/16}"
UERANSIM="${UERANSIM:-/opt/UERANSIM/build}"
TIER2="${TIER2:-/opt/ca-ztcf/testbed/tier2}"
OUT="${OUT_DIR:-/var/lib/ca-ztcf/tier2}"
TABLE_BASE="${TABLE_BASE:-5000}"

log() { echo "[ue-path] $*"; }
nsx() { sudo ip netns exec "${NS}" "$@"; }

setup() {
  sudo install -d -m 0775 "${OUT}"

  sudo ip netns list | grep -qw "${NS}" || sudo ip netns add "${NS}"

  if ! sudo ip link show "${VETH_ROOT}" >/dev/null 2>&1 \
     && ! nsx ip link show "${VETH_NS}" >/dev/null 2>&1; then
    sudo ip link add "${VETH_ROOT}" type veth peer name "${VETH_NS}"
  fi
  if sudo ip link show "${VETH_NS}" >/dev/null 2>&1; then
    sudo ip link set "${VETH_NS}" netns "${NS}"
  fi
  sudo ip addr replace "${VETH_ROOT_ADDR}/${VETH_PREFIX}" dev "${VETH_ROOT}"
  sudo ip link set "${VETH_ROOT}" up
  nsx ip addr replace "${VETH_NS_ADDR}/${VETH_PREFIX}" dev "${VETH_NS}"
  nsx ip link set "${VETH_NS}" up
  nsx ip link set lo up

  # The CA-ZTCF service address. A dummy interface, so it belongs to the host but
  # to no physical or virtual link the UE namespace can reach directly.
  sudo ip link show "${SVC_IF}" >/dev/null 2>&1 || sudo ip link add "${SVC_IF}" type dummy
  sudo ip addr replace "${SVC_ADDR}/32" dev "${SVC_IF}"
  sudo ip link set "${SVC_IF}" up

  # Never rewrite a UE source address on its way to a CA-ZTCF service address.
  sudo iptables -t nat -C POSTROUTING -s "${UE_NET}" -d "${SVC_NET}" -j RETURN 2>/dev/null \
    || sudo iptables -t nat -I POSTROUTING 1 -s "${UE_NET}" -d "${SVC_NET}" -j RETURN

  # The control link carries UERANSIM's Radio Link Simulation, which is UDP. The
  # CA-ZTCF services are TCP and listen on 0.0.0.0, so without this rule an agent
  # in the namespace could reach the PEP across the control veth and bypass the
  # tunnel entirely. Rejecting TCP on that link closes the bypass and leaves every
  # UERANSIM signalling path untouched.
  #
  # A blanket REJECT here does NOT work: it destabilises RLS and the UE drops into
  # repeated radio-link failure. Keep this restricted to TCP.
  nsx iptables -C OUTPUT -o "${VETH_NS}" -p tcp -j REJECT 2>/dev/null \
    || nsx iptables -A OUTPUT -o "${VETH_NS}" -p tcp -j REJECT

  log "namespace ${NS} ready; service address ${SVC_ADDR} on ${SVC_IF}"
}

start_ue() {
  local count="${1:-1}"
  # -x matches the executable name exactly. -f would also match this script's own
  # command line and kill the shell running it.
  sudo pkill -x nr-ue 2>/dev/null || true
  sleep 1
  # The redirection has to happen inside the privileged shell: ${OUT} is
  # root-owned, so a redirect written by the calling shell is refused.
  # setsid detaches it from the controlling terminal: without that an ssh session
  # into the VM stays open for as long as the UE runs.
  sudo setsid bash -c "exec ip netns exec ${NS} ${UERANSIM}/nr-ue \
    -c ${TIER2}/ueransim/ue.yaml -n ${count} > ${OUT}/ue.log 2>&1" \
    < /dev/null > /dev/null 2>&1 &
  disown 2>/dev/null || true
  local last=$((count - 1))
  for _ in $(seq 1 60); do
    if nsx ip link show "uesimtun${last}" >/dev/null 2>&1; then break; fi
    sleep 1
  done
  nsx ip link show "uesimtun${last}" >/dev/null 2>&1 || {
    log "FATAL: uesimtun${last} never appeared"
    tail -30 "${OUT}/ue.log"
    return 4
  }
  routes "${count}"
}

routes() {
  local count="${1:-1}"
  # The service network is reachable only through a UE tunnel. Each UE gets a
  # source-based rule so that a socket bound to a given UE address always leaves
  # through that UE's own tunnel; multiple devices therefore cannot collapse onto
  # one observed source identity.
  local i addr table
  for i in $(seq 0 $((count - 1))); do
    nsx ip link show "uesimtun${i}" >/dev/null 2>&1 || continue
    addr=$(nsx ip -4 addr show "uesimtun${i}" | awk '/inet /{print $2}' | cut -d/ -f1)
    [ -n "${addr}" ] || continue
    table=$((TABLE_BASE + i))
    nsx ip rule del from "${addr}" lookup "${table}" 2>/dev/null || true
    nsx ip rule add from "${addr}" lookup "${table}"
    nsx ip route replace "${SVC_NET}" dev "uesimtun${i}" table "${table}"
    log "uesimtun${i} = ${addr} -> table ${table}"
  done
  # An unbound socket in the namespace uses the first UE.
  nsx ip route replace "${SVC_NET}" dev uesimtun0
}

keepalive() {
  # UERANSIM's UE drops to RRC idle after a few minutes without user-plane
  # traffic. Resuming from idle fails in this testbed: the gNB still holds the UE
  # context, answers the RRC Setup Request with "UE context already exists", and
  # the Service Request times out, leaving a tunnel interface that is up but
  # carries nothing. A scenario that begins in that state fails for a reason that
  # has nothing to do with CA-ZTCF.
  #
  # A slow keepalive keeps the session active. An IoT device sending periodic
  # telemetry behaves the same way, and it touches no evidence, no trust logic and
  # no measured path.
  local period="${1:-5}"
  stop_keepalive
  sudo setsid bash -c "exec ip netns exec ${NS} ping -i ${period} -q ${SVC_ADDR} \
    > ${OUT}/ue-keepalive.log 2>&1" < /dev/null > /dev/null 2>&1 &
  disown 2>/dev/null || true
  sleep 1
  log "keepalive every ${period}s to ${SVC_ADDR}"
}

stop_keepalive() {
  sudo pkill -f "ping -i [0-9]* -q ${SVC_ADDR}" 2>/dev/null || true
}

verify() {
  # The tunnel interface can be up while the user plane is dead, so reachability
  # is what is checked, not the presence of uesimtun0.
  nsx ping -c2 -W2 -q "${SVC_ADDR}" >/dev/null 2>&1
}

ensure() {
  local count="${1:-1}"
  if verify; then
    log "5G user plane healthy"
  else
    log "5G user plane not passing traffic; re-establishing"
    # A stale gNB UE context is what blocks the UE from resuming, so the gNB is
    # restarted with it.
    sudo pkill -x nr-gnb 2>/dev/null || true
    sleep 2
    sudo setsid bash -c "exec ${UERANSIM}/nr-gnb -c ${TIER2}/ueransim/gnb.yaml \
      > ${OUT}/gnb.log 2>&1" < /dev/null > /dev/null 2>&1 &
    disown 2>/dev/null || true
    for _ in $(seq 1 30); do
      grep -q "NG Setup procedure is successful" "${OUT}/gnb.log" 2>/dev/null && break
      sleep 1
    done
    start_ue "${count}"
    for _ in $(seq 1 20); do verify && break; sleep 1; done
    verify || { log "FATAL: 5G user plane still not passing traffic"; return 5; }
    log "5G user plane re-established"
  fi
  keepalive 5
}

status() {
  echo "--- ${NS} addresses ---"; nsx ip -br addr
  echo "--- ${NS} routes (main) ---"; nsx ip route
  echo "--- ${NS} rules ---"; nsx ip rule
  echo "--- ${NS} per-UE tables ---"
  nsx ip rule | grep -oE "lookup [0-9]+" | awk '{print $2}' | sort -u | while read -r t; do
    [ "${t}" -ge "${TABLE_BASE}" ] 2>/dev/null || continue
    echo "  table ${t}: $(nsx ip route show table "${t}" | tr '\n' ';')"
  done
  echo "--- root service address ---"; ip -br addr show "${SVC_IF}"
  echo "--- nat POSTROUTING ---"; sudo iptables -t nat -S POSTROUTING
  echo "--- ${NS} OUTPUT filter ---"; nsx iptables -S OUTPUT
}

teardown() {
  stop_keepalive
  sudo pkill -x nr-ue 2>/dev/null || true
  sudo ip netns list | grep -qw "${NS}" && sudo ip netns del "${NS}" || true
  sudo ip link del "${VETH_ROOT}" 2>/dev/null || true
  sudo ip link del "${SVC_IF}" 2>/dev/null || true
  sudo iptables -t nat -D POSTROUTING -s "${UE_NET}" -d "${SVC_NET}" -j RETURN 2>/dev/null || true
  log "torn down"
}

case "${1:-}" in
  setup)     setup ;;
  start-ue)  setup; start_ue "${2:-1}"; keepalive 5 ;;
  routes)    routes "${2:-1}" ;;
  ensure)    setup; ensure "${2:-1}" ;;
  verify)    verify && echo "5G user plane OK" || { echo "5G user plane DOWN"; exit 1; } ;;
  keepalive) keepalive "${2:-5}" ;;
  status)    status ;;
  teardown)  stop_keepalive; teardown ;;
  *) echo "usage: $0 {setup|start-ue [N]|ensure [N]|verify|keepalive [s]|routes [N]|status|teardown}" >&2; exit 2 ;;
esac
