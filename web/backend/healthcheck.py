"""Docker healthcheck: authenticated request to /apiv2/health."""
import base64
import os
import urllib.request

user = os.environ["AGROVISION_BASIC_USER"]
password = os.environ["AGROVISION_BASIC_PASSWORD"]
token = base64.b64encode(f"{user}:{password}".encode()).decode()
request = urllib.request.Request(
    "http://127.0.0.1:8000/apiv2/health",
    headers={"Authorization": f"Basic {token}"},
)
with urllib.request.urlopen(request, timeout=3) as response:
    if response.status != 200:
        raise SystemExit(1)
