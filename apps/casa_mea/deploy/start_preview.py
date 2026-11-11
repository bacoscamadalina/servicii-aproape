"""Start the bundled read-only viewer on the private cloud's assigned PORT."""

import os

port = os.environ.get('PORT', '8000')
if not port.isascii() or not port.isdigit() or not 1 <= int(port) <= 65535:
    raise SystemExit('PORT must be an integer from 1 to 65535')
# A cloud environment must not switch this image into mutable/full-app settings.
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.preview'
os.execvp('gunicorn', [
    'gunicorn', 'config.wsgi:application', '--bind', f'0.0.0.0:{port}',
    '--workers', '2', '--timeout', '60', '--worker-tmp-dir', '/tmp', '--error-logfile', '-',
])
