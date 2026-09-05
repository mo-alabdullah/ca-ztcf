#!/usr/bin/env bash
# Generate the research CA and EAP-TLS certificates for the Tier-1 WLAN
# authentication path.
#
# Everything lands in testbed/wlan/certs/, which is git-ignored. None of this is
# a production credential; regenerate freely.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CERTS="${1:-${HERE}/certs}"
DAYS="${CERT_DAYS:-825}"

mkdir -p "${CERTS}"
cd "${CERTS}"

subject() { echo "/C=XX/ST=Research/L=Lab/O=CA-ZTCF Research/CN=$1"; }

if [ ! -f ca.key ]; then
  echo "generating research CA"
  openssl req -x509 -newkey rsa:2048 -nodes -keyout ca.key -out ca.crt \
    -days "${DAYS}" -subj "$(subject 'CA-ZTCF Research CA')" 2>/dev/null
  chmod 600 ca.key
fi

issue() {
  local name="$1" cn="$2" days="$3"
  [ -f "${name}.crt" ] && { echo "  ${name}: present"; return; }
  openssl req -newkey rsa:2048 -nodes -keyout "${name}.key" -out "${name}.csr" \
    -subj "$(subject "${cn}")" 2>/dev/null
  openssl x509 -req -in "${name}.csr" -CA ca.crt -CAkey ca.key -CAcreateserial \
    -out "${name}.crt" -days "${days}" 2>/dev/null
  rm -f "${name}.csr"
  chmod 600 "${name}.key"
  echo "  ${name}: issued (${days} days, CN=${cn})"
}

echo "issuing certificates"
issue server "tier1-eap-server" "${DAYS}"
issue client "device@lab.invalid" "${DAYS}"

# A certificate from an untrusted CA, for the invalid-certificate scenario.
if [ ! -f rogue-client.crt ]; then
  openssl req -x509 -newkey rsa:2048 -nodes -keyout rogue-ca.key -out rogue-ca.crt \
    -days "${DAYS}" -subj "$(subject 'CA-ZTCF Rogue CA')" 2>/dev/null
  openssl req -newkey rsa:2048 -nodes -keyout rogue-client.key -out rogue-client.csr \
    -subj "$(subject 'rogue@lab.invalid')" 2>/dev/null
  openssl x509 -req -in rogue-client.csr -CA rogue-ca.crt -CAkey rogue-ca.key \
    -CAcreateserial -out rogue-client.crt -days "${DAYS}" 2>/dev/null
  rm -f rogue-client.csr
  chmod 600 rogue-ca.key rogue-client.key
  echo "  rogue-client: issued from an untrusted CA (invalid-certificate scenario)"
fi

# An already-expired certificate, for the expired-chain scenario.
#
# OpenSSL 3.0 (Debian bookworm) has no -not_before/-not_after on `x509 -req`, so
# the certificate is signed under a backdated clock with faketime and given a
# one-day lifetime. It is therefore already expired the moment it exists,
# deterministically and without waiting for real time to pass.
if [ ! -f expired-client.crt ]; then
  openssl req -newkey rsa:2048 -nodes -keyout expired-client.key \
    -out expired-client.csr -subj "$(subject 'expired@lab.invalid')" 2>/dev/null
  if command -v faketime >/dev/null 2>&1; then
    faketime '10 days ago' openssl x509 -req -in expired-client.csr \
      -CA ca.crt -CAkey ca.key -CAcreateserial -out expired-client.crt -days 1 2>/dev/null
  fi
  rm -f expired-client.csr
  if [ -f expired-client.crt ]; then
    chmod 600 expired-client.key
    echo "  expired-client: already expired ($(openssl x509 -in expired-client.crt -noout -enddate))"
  else
    echo "  expired-client: faketime unavailable; expired-chain scenario will be skipped"
  fi
fi

# Diffie-Hellman parameters for the EAP server.
[ -f dh.pem ] || { openssl dhparam -out dh.pem 2048 2>/dev/null; echo "  dh.pem: generated"; }

cat > README.txt <<'TXT'
Generated research key material for the Tier-1 WLAN authentication path.

This directory is git-ignored and must stay that way. Nothing here is a
production credential; every key is disposable laboratory material and may be
regenerated at any time with testbed/wlan/gen_certs.sh.
TXT

echo "done. ${CERTS} is git-ignored; do not commit its contents."
