"""Egress canary: try to reach a few external hosts from the current process.

Used as a startup check by the mock device and the demo runner when they run
under scripts/offline-run (or a --network none container). `blocked` is True
only if every connection attempt failed.
"""
from __future__ import annotations

import os
import socket

TARGETS = [
    ('1.1.1.1', 443),
    ('generativelanguage.googleapis.com', 443),
    ('api.openai.com', 443),
    ('huggingface.co', 443),
]


def check_egress(targets=TARGETS, timeout: float = 3.0) -> dict:
    opened, errors = [], {}
    for host, port in targets:
        try:
            socket.create_connection((host, port), timeout=timeout).close()
            opened.append(f'{host}:{port}')
        except OSError as e:
            errors[f'{host}:{port}'] = f'{type(e).__name__}: {e}'
    return {'ran': True, 'pid': os.getpid(), 'blocked': not opened, 'open': opened, 'errors': errors}


if __name__ == '__main__':
    import json
    import sys
    result = check_egress()
    print(json.dumps(result, indent=2))
    sys.exit(0 if result['blocked'] else 1)
