"""Configuration and manifest compatibility contract."""

from __future__ import annotations

import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_DIR))
from telegram_session_reset_handoff import (
    DEFAULT_CONFIG,
    MAX_HANDOFF_CHARS,
    MAX_RECORDS,
    MAX_RETENTION_DAYS,
    MAX_TRANSCRIPT_CHARS,
    MIN_HANDOFF_CHARS,
    MIN_RECORDS,
    MIN_RETENTION_DAYS,
    MIN_TRANSCRIPT_CHARS,
    normalize_config,
    profile_storage_path,
)


def test_defaults_bounds_and_profile_path():
    assert normalize_config({}) == DEFAULT_CONFIG
    assert normalize_config(
        {
            "enabled": "bad",
            "max_transcript_chars": 0,
            "max_handoff_chars": 99999,
            "retention_days": 0,
            "max_records": 99999,
        }
    ) == {
        "enabled": True,
        "max_transcript_chars": MIN_TRANSCRIPT_CHARS,
        "max_handoff_chars": MAX_HANDOFF_CHARS,
        "retention_days": MIN_RETENTION_DAYS,
        "max_records": MAX_RECORDS,
    }
    assert profile_storage_path("data") == Path("data/telegram-session-reset-handoff")


def test_manifest_pins_exact_tested_runtime_and_worker_hooks():
    manifest = (PLUGIN_DIR / "plugin.yaml").read_text()
    assert 'hermes: "==0.21.0"' in manifest
    assert "  - on_session_finalize" in manifest and "  - pre_llm_call" in manifest
    assert "pre_gateway_dispatch" not in manifest
    for value in (
        MIN_TRANSCRIPT_CHARS,
        MAX_TRANSCRIPT_CHARS,
        MIN_HANDOFF_CHARS,
        MAX_HANDOFF_CHARS,
        MIN_RETENTION_DAYS,
        MAX_RETENTION_DAYS,
        MIN_RECORDS,
        MAX_RECORDS,
    ):
        assert str(value) in manifest
