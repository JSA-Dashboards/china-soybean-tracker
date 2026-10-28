"""Read/write tracker_data.json. With GITHUB_TOKEN set (env or st.secrets), reads the
live file and commits changes through the GitHub contents API (the Streamlit Cloud
filesystem is ephemeral, so the repo is the database). The public tabs read the repo's
raw data file (cached 60 s) so a mirror inside another app never goes stale. Without a
token nothing is ever written, except in dev with ALLOW_LOCAL_STORE=1."""
import base64
import json
import os
import time

import requests

import tracker_logic as t


class Conflict(Exception):
    pass


def cfg(name, default=None):
    v = os.environ.get(name)
    if v:
        return v
    try:
        import streamlit as st
        return st.secrets.get(name, default)
    except Exception:
        return default


def secret_names_like(*needles):
    """NAMES only (never values) of app secrets containing any needle, one level into [sections] too,
    so a token pasted under a heading shows up as 'section.NAME'."""
    try:
        import streamlit as st
        out = []
        for k in st.secrets.keys():
            v = st.secrets[k]
            if any(n in str(k).upper() for n in needles):
                out.append(str(k))
            if hasattr(v, "keys"):
                out += [f"{k}.{kk}" for kk in v.keys() if any(n in str(kk).upper() for n in needles)]
        return sorted(out)
    except Exception:
        return []


def _token():
    """CHINA_TRACKER_GITHUB_TOKEN wins so a host app (the admin portal) can keep its own GITHUB_TOKEN."""
    return cfg("CHINA_TRACKER_GITHUB_TOKEN") or cfg("GITHUB_TOKEN")


def configured():
    return bool(_token())


def _url():
    repo = cfg("GITHUB_REPO", "JSA-Dashboards/china-soybean-tracker")
    return f"https://api.github.com/repos/{repo}/contents/{cfg('GITHUB_DATA_PATH', 'tracker_data.json')}"


def _headers():
    return {"Authorization": f"Bearer {_token()}", "Accept": "application/vnd.github+json"}


def load_public():
    """The live data file from the repo's main branch (no token needed for a public repo), else the local copy."""
    repo = cfg("GITHUB_REPO", "JSA-Dashboards/china-soybean-tracker")
    url = f"https://raw.githubusercontent.com/{repo}/{cfg('GITHUB_BRANCH', 'main')}/{cfg('GITHUB_DATA_PATH', 'tracker_data.json')}"
    try:
        r = requests.get(url, headers={"Authorization": f"token {_token()}"} if configured() else {}, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception:
        return t.load()


_cached = None


def public_data():
    """load_public() cached for 60 s (Streamlit). refresh_public() clears only this cache."""
    global _cached
    if _cached is None:
        import streamlit as st
        _cached = st.cache_data(ttl=60, show_spinner=False)(load_public)
    return _cached()


def refresh_public():
    if _cached is not None:
        _cached.clear()


def load_fresh():
    """(data, sha). sha is None when there is no token (read-only)."""
    if not configured():
        return load_public(), None
    r = requests.get(_url(), headers=_headers(), params={"ref": cfg("GITHUB_BRANCH", "main")}, timeout=20)
    r.raise_for_status()
    j = r.json()
    return json.loads(base64.b64decode(j["content"]).decode("utf-8")), j["sha"]


def save(data, sha, message):
    if not configured():
        if os.environ.get("ALLOW_LOCAL_STORE"):  # dev only
            t.save(data)
            return
        raise RuntimeError("Saving is off: no GitHub token is configured (CHINA_TRACKER_GITHUB_TOKEN or GITHUB_TOKEN).")
    body = {
        "message": message,
        "content": base64.b64encode((json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")).decode(),
        "sha": sha,
        "branch": cfg("GITHUB_BRANCH", "main"),
        "committer": {"name": "koltenpostin93-blip", "email": "275148418+koltenpostin93-blip@users.noreply.github.com"},
    }
    r = requests.put(_url(), headers=_headers(), json=body, timeout=30)
    if r.status_code in (409, 422):
        raise Conflict(r.text[:200])
    r.raise_for_status()


def update(fn, message, retries=3):
    """Load the live data, apply fn(data) (which mutates it), commit. Retries on a
    concurrent write. fn may raise ValueError to abort without saving."""
    for attempt in range(retries):
        data, sha = load_fresh()
        fn(data)
        try:
            save(data, sha, message)
            return data
        except Conflict:
            if attempt == retries - 1:
                raise
            time.sleep(1.5)
