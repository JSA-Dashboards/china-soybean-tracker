import pytest

import store
import tracker_logic as t


def _no_token(monkeypatch):
    monkeypatch.delenv("ALLOW_LOCAL_STORE", raising=False)
    monkeypatch.setattr(store, "cfg", lambda name, default=None: default)


def test_save_refuses_without_a_token(monkeypatch):
    _no_token(monkeypatch)
    with pytest.raises(RuntimeError):
        store.save(t.load(), None, "x")


def test_dev_flag_allows_local_write(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "cfg", lambda name, default=None: default)
    monkeypatch.setenv("ALLOW_LOCAL_STORE", "1")
    monkeypatch.setattr(t, "DATA_PATH", tmp_path / "d.json")
    store.save({"a": 1}, None, "x")
    assert (tmp_path / "d.json").exists()


def test_load_public_falls_back_to_the_local_file(monkeypatch):
    _no_token(monkeypatch)

    def boom(*a, **k):
        raise OSError("offline")

    monkeypatch.setattr(store.requests, "get", boom)
    assert store.load_public()["marketing_year"] == "2026/27"


def test_portal_token_name_wins(monkeypatch):
    vals = {"CHINA_TRACKER_GITHUB_TOKEN": "portal", "GITHUB_TOKEN": "other"}
    monkeypatch.setattr(store, "cfg", lambda name, default=None: vals.get(name, default))
    assert store._token() == "portal" and store.configured()


def test_load_fresh_is_read_only_without_a_token(monkeypatch):
    _no_token(monkeypatch)
    monkeypatch.setattr(store, "load_public", lambda: {"x": 1})
    assert store.load_fresh() == ({"x": 1}, None)


def test_secret_names_like_returns_names_only(monkeypatch):
    import streamlit as st

    fake = {"CHINA_TRACKER_GITHUB_TOKEN": "supersecret", "other": {"GITHUB_TOKEN": "x"}, "SNOWFLAKE_ACCOUNT": "a"}
    monkeypatch.setattr(st, "secrets", fake)
    names = store.secret_names_like("GITHUB", "CHINA")
    assert names == ["CHINA_TRACKER_GITHUB_TOKEN", "other.GITHUB_TOKEN"]
    assert "supersecret" not in " ".join(names)
