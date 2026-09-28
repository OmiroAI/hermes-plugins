"""Fast finalization marker tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PLUGIN_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_DIR))
from telegram_session_reset_handoff import (
    STATE_INDEX_KEY,
    on_session_finalize,
    read_pending_marker,
)
import telegram_session_reset_handoff as handoff


@pytest.fixture(autouse=True)
def tested_runtime(monkeypatch):
    monkeypatch.setattr(handoff.importlib_metadata, "version", lambda _: "0.21.0")


class State:
    def __init__(self, tmp_path):
        self.values = {}
        self.data_dir = tmp_path

    def get(self, k, d=None):
        return self.values.get(k, d)

    def set(self, k, v):
        self.values[k] = v


class Ctx:
    def __init__(self, tmp_path):
        self.state = State(tmp_path)

    def get_config(self, k, d=None):
        return d


def test_read_index_allowlists_only_finite_metadata(tmp_path):
    state = State(tmp_path)
    key = handoff._digest("old")
    state.values[STATE_INDEX_KEY] = {
        "schema_version": 2,
        "records": {
            key: {
                "created_at": float("nan"),
                "marker_expiry": True,
                "marker_manual": "false",
                "attempted": False,
                "consumed": 1,
                "handoff": "PRIVATE LEGACY SUMMARY",
                "rendered": "PRIVATE LEGACY RENDERING",
                "freeform": "stale",
            }
        },
    }

    assert handoff._read_index(state) == {
        "schema_version": 2,
        "records": {key: {"marker_expiry": True, "attempted": False}},
    }


def test_only_telegram_expiry_and_manual_finalize_markers_are_written(tmp_path):
    ctx = Ctx(tmp_path)
    on_session_finalize(
        ctx, platform="discord", reason="session_expired", session_id="old"
    )
    assert not ctx.state.values
    on_session_finalize(
        ctx, platform="telegram", reason="session_expired", session_id="old"
    )
    assert read_pending_marker(ctx.state, "old") == {"pending": True}
    on_session_finalize(
        ctx, platform="telegram", reason="new_session", session_id="old"
    )
    assert read_pending_marker(ctx.state, "old") is None
    record = ctx.state.values[STATE_INDEX_KEY]["records"]
    assert len(record) == 1 and all("old" not in key for key in record)


def test_finalization_rewrites_legacy_record_to_allowlisted_metadata(tmp_path):
    ctx = Ctx(tmp_path)
    key = handoff._digest("old")
    ctx.state.values[STATE_INDEX_KEY] = {
        "schema_version": 2,
        "records": {
            key: {
                "created_at": 1.0,
                "marker_expiry": "yes",
                "marker_manual": False,
                "attempted": True,
                "consumed": False,
                "handoff": "PRIVATE LEGACY SUMMARY",
                "rendered": "PRIVATE LEGACY RENDERING",
                "arbitrary": {"nested": "stale"},
            }
        },
    }

    on_session_finalize(
        ctx, platform="telegram", reason="session_expired", session_id="old"
    )

    record = ctx.state.values[STATE_INDEX_KEY]["records"][key]
    assert record == {
        "created_at": record["created_at"],
        "marker_expiry": True,
        "marker_manual": False,
        "attempted": True,
        "consumed": False,
    }
    assert "PRIVATE LEGACY" not in repr(ctx.state.values)
