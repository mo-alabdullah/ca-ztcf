#!/usr/bin/env bash
# Generate research key material for CA-ZTCF development and experiments.
#
# Ed25519 key pairs are written to secrets/, which is git-ignored. Nothing this
# script produces may ever be committed. Regenerate freely; no key here has any
# meaning outside the laboratory.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:-${ROOT}/secrets}"
COUNT="${2:-3}"

mkdir -p "${OUT}"
chmod 700 "${OUT}"

if ! command -v openssl >/dev/null 2>&1; then
  echo "error: openssl is required" >&2
  exit 1
fi

echo "Generating ${COUNT} Ed25519 research device key pair(s) into ${OUT}"
for i in $(seq 1 "${COUNT}"); do
  id=$(printf "dev-%03d" "${i}")
  key="${OUT}/${id}.key.pem"
  pub="${OUT}/${id}.pub.pem"
  if [ -f "${key}" ]; then
    echo "  ${id}: already present, skipping"
    continue
  fi
  openssl genpkey -algorithm ed25519 -out "${key}" >/dev/null 2>&1
  chmod 600 "${key}"
  openssl pkey -in "${key}" -pubout -out "${pub}" >/dev/null 2>&1
  chmod 644 "${pub}"
  echo "  ${id}: ${key} (private, never commit) / ${pub} (public)"
done

cat > "${OUT}/README.txt" <<'TXT'
This directory holds generated research key material.

It is git-ignored and must stay that way. Nothing here is a production
credential; every key is disposable laboratory material and may be regenerated
at any time with scripts/gen_certs.sh.
TXT

echo "Done. secrets/ is git-ignored; do not commit its contents."
