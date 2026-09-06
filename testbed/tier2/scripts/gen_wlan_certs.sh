#!/usr/bin/env bash
# Research CA and EAP-TLS certificates for the Tier-2 WLAN.
# Everything is disposable laboratory material and is git-ignored.
set -euo pipefail
CERTS="${1:-/etc/hostapd/certs}"
DAYS="${CERT_DAYS:-825}"
mkdir -p "${CERTS}"; cd "${CERTS}"
subject() { echo "/C=XX/ST=Research/L=Lab/O=CA-ZTCF Research/CN=$1"; }

[ -f ca.crt ] || { openssl req -x509 -newkey rsa:2048 -nodes -keyout ca.key -out ca.crt \
  -days "${DAYS}" -subj "$(subject 'CA-ZTCF Tier2 Research CA')" 2>/dev/null; chmod 600 ca.key; }

issue() {
  [ -f "$1.crt" ] && return 0
  openssl req -newkey rsa:2048 -nodes -keyout "$1.key" -out "$1.csr" \
    -subj "$(subject "$2")" 2>/dev/null
  openssl x509 -req -in "$1.csr" -CA ca.crt -CAkey ca.key -CAcreateserial \
    -out "$1.crt" -days "${DAYS}" 2>/dev/null
  rm -f "$1.csr"; chmod 600 "$1.key"
}
issue server "tier2-eap-server"
issue client "device@lab.invalid"
[ -f dh.pem ] || openssl dhparam -out dh.pem 2048 2>/dev/null
echo "certificates ready in ${CERTS}"
