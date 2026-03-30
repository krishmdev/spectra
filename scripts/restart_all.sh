#!/usr/bin/env bash
# restart_all.sh — Full restart: simulator boot → WDA → Spectra app build → backend server
set -e

SIM_UDID="92AE937B-E99E-4B16-BC42-0200DB1C3FDB"
SPECTRA_PROJ="/Users/vsangireddy/spectra/spectra/ios/Spectra/Spectra.xcodeproj"
WDA_PROJ="/Users/vsangireddy/yhack/WebDriverAgent/WebDriverAgent.xcodeproj"
SPECTRA_ROOT="/Users/vsangireddy/spectra/spectra"
BUNDLE_ID="com.spectra.agent"

echo "==> [1/5] Killing existing server and WDA processes..."
lsof -ti:8765 | xargs kill -9 2>/dev/null || true
lsof -ti:8100 | xargs kill -9 2>/dev/null || true
pkill -f "WebDriverAgentRunner" 2>/dev/null || true
pkill -f "uvicorn" 2>/dev/null || true
sleep 1

echo "==> [2/5] Booting simulator ($SIM_UDID)..."
xcrun simctl boot "$SIM_UDID" 2>/dev/null || true   # no-op if already booted
sleep 3

echo "==> [3/5] Launching WDA on simulator (port 8100)..."
xcodebuild \
  -project "$WDA_PROJ" \
  -scheme WebDriverAgentRunner \
  -destination "id=$SIM_UDID" \
  test \
  USE_PORT=8100 \
  > /tmp/wda.log 2>&1 &
WDA_PID=$!
echo "    WDA PID: $WDA_PID (log: /tmp/wda.log)"

# Wait for WDA to be ready
echo -n "    Waiting for WDA on :8100 "
for i in $(seq 1 30); do
  if curl -sf http://localhost:8100/status >/dev/null 2>&1; then
    echo " ready."
    break
  fi
  echo -n "."
  sleep 2
done

echo "==> [4/5] Building and installing Spectra.app..."
xcodebuild \
  -project "$SPECTRA_PROJ" \
  -scheme Spectra \
  -destination "id=$SIM_UDID" \
  -configuration Debug \
  build install \
  DSTROOT=/tmp/spectra_install \
  > /tmp/spectra_build.log 2>&1
echo "    Installing app on simulator..."
APP_PATH=$(find /tmp/spectra_install -name "*.app" | head -1)
xcrun simctl install "$SIM_UDID" "$APP_PATH"
echo "    Launching Spectra..."
xcrun simctl launch "$SIM_UDID" "$BUNDLE_ID"
sleep 2

echo "==> [5/5] Starting Spectra backend server (port 8765)..."
cd "$SPECTRA_ROOT"
source .venv/bin/activate
uvicorn server.ws_server:app --host 0.0.0.0 --port 8765 > /tmp/spectra_server.log 2>&1 &
SERVER_PID=$!
sleep 2
if lsof -ti:8765 >/dev/null 2>&1; then
  echo "    Backend running (PID $SERVER_PID, log: /tmp/spectra_server.log)"
else
  echo "    ERROR: Backend failed to start. Check /tmp/spectra_server.log"
  exit 1
fi

echo ""
echo "✓ All systems up:"
echo "  Simulator : $SIM_UDID"
echo "  WDA       : http://localhost:8100  (log: /tmp/wda.log)"
echo "  Backend   : http://localhost:8765  (log: /tmp/spectra_server.log)"
echo "  App       : $BUNDLE_ID"
