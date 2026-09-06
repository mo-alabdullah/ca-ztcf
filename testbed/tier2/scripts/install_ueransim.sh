#!/usr/bin/env bash
# Build UERANSIM at a pinned tag.
#
# UERANSIM is a SOFTWARE UE and gNB. It speaks real 5G NAS, NGAP and GTP-U to
# Open5GS and creates a real TUN interface for user-plane traffic, but it
# synthesises the radio: there is no physical RF anywhere.
set -euo pipefail

UERANSIM_VERSION="${UERANSIM_VERSION:-v3.2.6}"
PREFIX="${PREFIX:-/opt/UERANSIM}"

if [ -x "${PREFIX}/build/nr-gnb" ] && [ -x "${PREFIX}/build/nr-ue" ]; then
  echo "UERANSIM already built at ${PREFIX}"
  "${PREFIX}/build/nr-gnb" --version 2>/dev/null | head -2 || true
  exit 0
fi

echo "building UERANSIM ${UERANSIM_VERSION}"
sudo mkdir -p "$(dirname "${PREFIX}")"
if [ ! -d "${PREFIX}/.git" ]; then
  sudo git clone --depth 1 --branch "${UERANSIM_VERSION}" \
    https://github.com/aligungr/UERANSIM.git "${PREFIX}"
fi
cd "${PREFIX}"
sudo git fetch --depth 1 origin tag "${UERANSIM_VERSION}" 2>/dev/null || true
sudo git checkout -q "${UERANSIM_VERSION}"

# GCC 13 compatibility.
#
# UERANSIM v3.2.6 predates GCC 13, whose standard headers no longer pull in
# <cstring>, <cstdio>, <string> or <cstdint> transitively. On Ubuntu 24.04 that
# leaves memset, strlen, snprintf, std::string and the fixed-width integer types
# undeclared across several translation units.
#
# The fix is a compiler flag rather than a set of source patches: it covers every
# affected file at once, changes no behaviour, and leaves the pinned upstream
# source untouched, so the build stays reproducible and the tag still means what
# it says.
export CXXFLAGS="${CXXFLAGS:-} -include cstring -include cstdio -include string -include cstdint"
export CFLAGS="${CFLAGS:-} -include string.h -include stdio.h -include stdint.h"
echo "  building with CXXFLAGS='${CXXFLAGS}' for GCC 13 compatibility"

sudo --preserve-env=CXXFLAGS,CFLAGS make -j"$(nproc)"

# nr-binder ships without the executable bit. It is the supported way to force an
# application's traffic through the UE tunnel, which matters here because the UE
# and the core are co-located: without it the kernel routes 10.45.0.0/16 straight
# out of ogstun and the traffic never traverses GTP-U at all.
sudo chmod +x "${PREFIX}/build/nr-binder" 2>/dev/null || true

echo "built:"
ls -1 "${PREFIX}/build" | sed 's/^/  /'
git -C "${PREFIX}" describe --tags --always | sed 's/^/  version: /'
