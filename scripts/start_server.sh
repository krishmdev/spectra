#!/usr/bin/env bash
# Start the Spectra WebSocket server on port 8765.
cd "$(dirname "$0")/.."
exec uvicorn server.ws_server:app --host 0.0.0.0 --port 8765
