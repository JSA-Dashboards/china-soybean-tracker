"""Read/write tracker_data.json. With GITHUB_TOKEN set (env or st.secrets), reads the
live file and commits changes through the GitHub contents API (the Streamlit Cloud
filesystem is ephemeral, so the repo is the database). Without a token it falls
back to the local file for development."""
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


def configured():
    return bool(cfg("GITHUB_TOKEN"))


def _url():
    repo = cfg("GITHUB_REPO", "JSA-Dashboards/china-soybean-tracker")
    return f"https://api.github.com/repos/{repo}/contents/{cfg('GITHUB_DATA_PATH', 'tracker_data.json')}"


def _headers():
    return {"Authorization": f"Bearer {cfg('GITHUB_TOKEN')}", "Accept": "application/vnd.github+json"}


def load_fresh():
    """(data, sha). sha is None in local-file mode."""
    if not configured():
        return t.load(), None
    r = requests.get(_url(), headers=_headers(), params={"ref": cfg("GITHUB_BRANCH", "main")}, timeout=20)
    r.raise_for_status()
    j = r.json()
    return json.loads(base64.b64decode(j["content"]).decode("utf-8")), j["sha"]


def save(data, sha, message):
    if not configured():
        t.save(data)
        return
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
