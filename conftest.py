"""Tests run against a frozen copy of the Oct 19 published state, never the live data file
(the droplet and the admin tab keep committing to tracker_data.json)."""
from pathlib import Path

import pytest

import tracker_logic as t

FIXTURE = Path(__file__).with_name("tests_fixtures") / "tracker_data_oct19.json"


@pytest.fixture(autouse=True)
def frozen_data(monkeypatch):
    monkeypatch.setattr(t, "DATA_PATH", FIXTURE)
