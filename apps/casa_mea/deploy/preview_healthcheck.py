"""Probe the actual catalogue reader, without source credentials or DB writes."""

import os
from urllib.request import urlopen

port = int(os.environ.get('PORT', '8000'))
with urlopen(f'http://127.0.0.1:{port}/?county=Cluj&locality=54984', timeout=4) as response:
    if response.status != 200:
        raise SystemExit('Preview catalogue is unavailable')
