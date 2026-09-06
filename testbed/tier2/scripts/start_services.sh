#!/usr/bin/env bash
# Start the CA-ZTCF service stack inside the Tier-2 VM.
#
# Runs as host processes rather than containers: the VM already is the isolation
# boundary, and the device agent has to reach the service through the UE tunnel
# and the WLAN interface, which is simpler without a second network namespace
# layer in the way.
set -euo pipefail

REPO="${REPO:-/opt/ca-ztcf}"
VENV="${VENV:-/opt/ca-ztcf-venv}"
OUT="${OUT_DIR:-/var/lib/ca-ztcf/tier2}"
sudo mkdir -p "${OUT}"

if [ ! -x "${VENV}/bin/python" ]; then
  echo "[tier2-services] creating the virtual environment"
  sudo python3 -m venv "${VENV}"
  sudo "${VENV}/bin/pip" -q install --upgrade pip
  sudo "${VENV}/bin/pip" -q install fastapi "uvicorn[standard]" pydantic pydantic-settings \
    prometheus-client cryptography PyYAML httpx
fi

echo "[tier2-services] starting the CA-ZTCF core"
sudo pkill -f "uvicorn ca_ztcf" 2>/dev/null || true
sudo pkill -f "ca_ztcf.enforcement.service" 2>/dev/null || true
sudo pkill -f "mosquitto -c" 2>/dev/null || true
sleep 1

cd "${REPO}"
sudo env PYTHONPATH="${REPO}/src" CA_ZTCF_CONFIG_DIR="${REPO}/config" \
  "${VENV}/bin/python" -m uvicorn ca_ztcf.api.app:get_app --factory \
  --host 0.0.0.0 --port 8080 --no-access-log > "${OUT}/ca-ztcf-core.log" 2>&1 &

for _ in $(seq 1 30); do
  curl -fsS http://127.0.0.1:8080/healthz >/dev/null 2>&1 && break
  sleep 1
done
curl -fsS http://127.0.0.1:8080/healthz >/dev/null || { echo "core did not start"; tail -20 "${OUT}/ca-ztcf-core.log"; exit 2; }
echo "[tier2-services] core healthy"

if command -v mosquitto >/dev/null 2>&1; then
  echo "[tier2-services] starting Mosquitto"
  printf 'listener 1883\nallow_anonymous true\npersistence false\n' | sudo tee /etc/mosquitto/ca-ztcf.conf >/dev/null
  sudo mosquitto -c /etc/mosquitto/ca-ztcf.conf > "${OUT}/mosquitto.log" 2>&1 &
  sleep 2
fi

echo "[tier2-services] starting the MQTT enforcement point"
sudo env PYTHONPATH="${REPO}/src" CA_ZTCF_CORE_URL=http://127.0.0.1:8080 \
  CA_ZTCF_BROKER_HOST=127.0.0.1 CA_ZTCF_BROKER_PORT=1883 CA_ZTCF_PEP_PORT=1884 \
  "${VENV}/bin/python" -m ca_ztcf.enforcement.service > "${OUT}/ca-ztcf-pep.log" 2>&1 &
sleep 3

echo "[tier2-services] status"
curl -fsS http://127.0.0.1:8080/readyz | head -c 200; echo
ss -lntp 2>/dev/null | grep -E ":8080|:1883|:1884" | sed 's/^/  /'
