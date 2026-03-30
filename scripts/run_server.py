"""Start the Spectra WebSocket server with pings disabled."""
import os
import sys

# Ensure print() output is visible immediately (not buffered)
os.environ['PYTHONUNBUFFERED'] = '1'

# Load .env file
env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, _, value = line.partition('=')
                os.environ[key.strip()] = value.strip()

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import uvicorn

if __name__ == '__main__':
    uvicorn.run(
        'server.ws_server:app',
        host='0.0.0.0',
        port=8765,
        ws_ping_interval=None,
        ws_ping_timeout=None,
        log_level='info',
    )
