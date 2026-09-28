"""Fast finalization marker tests."""

from __future__ import annotations

import json
import sys
import time
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


class FileState(State):
    def __init__(self, tmp_path):
        super().__init__(tmp_path)
        self.path = self.data_dir / "state.json"

    def get(self, key, default=None):
        try:
            return json.loads(self.path.read_text())[key]
        except (FileNotFoundError, KeyError):
            return default

    def set(self, key, value):
        data = json.loads(self.path.read_text()) if self.path.exists() else {}
        data[key] = value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data))


def test_normal_execution_purges_legacy_state_file_without_dropping_metadata(tmp_path):
    state = FileState(tmp_path)
    legacy_id = "legacy-session-id"
    metadata_key = handoff._digest("current")
    created_at = time.time()
    state.path.parent.mkdir(parents=True, exist_ok=True)
    state.path.write_text(
        json.dumps(
            {
                "pending:" + handoff._digest(legacy_id): {
                    "old_session_id": legacy_id,
                    "pending": True,
                },
                "handoff:" + handoff._digest(legacy_id): {
                    "old_session_id": legacy_id,
                    "rendered": "PRIVATE LEGACY SUMMARY",
                },
                STATE_INDEX_KEY: {
                    "schema_version": 2,
                    "records": {
                        metadata_key: {
                            "created_at": created_at,
                            "marker_expiry": True,
                            "attempted": False,
                            "handoff": {"objective": "PRIVATE LEGACY SUMMARY"},
                            "rendered": "PRIVATE LEGACY SUMMARY",
                        }
                    },
                },
            }
        )
    )
    ctx = Ctx(tmp_path)
    ctx.state = state

    on_session_finalize(
        ctx, platform="telegram", reason="session_expired", session_id="unrelated"
    )

    stored = state.path.read_text()
    parsed = json.loads(stored)
    assert legacy_id not in stored and "PRIVATE LEGACY SUMMARY" not in stored
    assert not any(key.startswith(("pending:", "handoff:")) for key in parsed)
    assert parsed[STATE_INDEX_KEY]["records"][metadata_key] == {
        "created_at": created_at,
        "marker_expiry": True,
        "attempted": False,
    }


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
