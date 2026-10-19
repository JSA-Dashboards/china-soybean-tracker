#!/usr/bin/env python3
"""Run ONCE, interactively, on the droplet:  .venv/bin/python deploy/setup_auth.py

Device-code login (as the mailbox owner, kpostin@jpsi.com) with the basis tracker's
AZURE_CLIENT_ID and the delegated Mail.Read scope -- the same login the Southport poller
uses -- then saves a token cache that ingest.py refreshes silently. Reads
GRAPH_ENV_FILE (default /opt/basis-tracker/.env)."""
import os
import sys
from pathlib import Path

import msal

HERE = Path(__file__).resolve().parent.parent
ENV_FILE = Path(os.environ.get("GRAPH_ENV_FILE", "/opt/basis-tracker/.env"))
CACHE = Path(os.environ.get("GRAPH_TOKEN_CACHE", HERE / ".token_cache.json"))

env = {}
for raw in ENV_FILE.read_text(errors="replace").splitlines():
    line = raw.strip().lstrip("﻿")
    if line.startswith("export "):
        line = line[7:]
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip().strip('"').strip("'")

cache = msal.SerializableTokenCache()
app = msal.PublicClientApplication(env["AZURE_CLIENT_ID"], authority="https://login.microsoftonline.com/" + env["GRAPH_TENANT_ID"],
                                   token_cache=cache)
flow = app.initiate_device_flow(scopes=["Mail.Read"])
if "user_code" not in flow:
    sys.exit(f"Device flow failed: {flow}")
print("\n" + flow["message"] + "\n")
res = app.acquire_token_by_device_flow(flow)
if "access_token" not in res:
    sys.exit(f"Login failed: {res.get('error_description') or res}")
CACHE.write_text(cache.serialize())
CACHE.chmod(0o600)
print(f"Saved token cache to {CACHE} (signed in as {res.get('id_token_claims', {}).get('preferred_username')})")
