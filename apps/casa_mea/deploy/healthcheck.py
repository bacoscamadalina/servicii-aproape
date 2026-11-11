"""Check PostgreSQL and the configured HTTP stack without a public health route."""

import os
import urllib.request

import psycopg

with psycopg.connect(
    dbname=os.environ["CASAMEA_POSTGRES_DB"], user=os.environ["CASAMEA_POSTGRES_USER"],
    password=os.environ["CASAMEA_POSTGRES_PASSWORD"], host=os.environ["CASAMEA_POSTGRES_HOST"],
    connect_timeout=3,
) as database:
    database.execute("SELECT 1")

domain = os.environ.get("CASAMEA_DOMAIN")
headers = {"Host": domain, "X-Forwarded-Proto": "https"} if domain else {}
request = urllib.request.Request("http://127.0.0.1:8000/admin/login/", headers=headers)
with urllib.request.urlopen(request, timeout=5) as response:
    if response.status != 200:
        raise SystemExit("HTTP health check failed")
