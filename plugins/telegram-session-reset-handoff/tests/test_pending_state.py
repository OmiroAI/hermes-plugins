"""Fast finalization marker tests."""

from __future__ import annotations

import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_DIR))
from telegram_session_reset_handoff import (
    STATE_INDEX_KEY,
    on_session_finalize,
    read_pending_marker,
)


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
