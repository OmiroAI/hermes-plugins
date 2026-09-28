"""Tests for pure session-reset-handoff configuration and path helpers."""

from __future__ import annotations

from pathlib import Path
import sys

PLUGIN_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_DIR))

from telegram_session_reset_handoff import (  # noqa: E402
    DEFAULT_CONFIG,
    normalize_config,
    profile_storage_path,
    register,
)


def test_normalize_config_uses_documented_defaults() -> None:
    assert DEFAULT_CONFIG == {
        "enabled": True,
        "max_transcript_chars": 24000,
        "max_handoff_chars": 4500,
        "retention_days": 30,
        "max_records": 200,
    }
    assert normalize_config({}) == DEFAULT_CONFIG


def test_normalize_config_rejects_invalid_values_and_clamps_bounds() -> None:
    assert normalize_config(
        {
            "enabled": "yes",
            "max_transcript_chars": -1,
            "max_handoff_chars": "not-a-number",
            "retention_days": 100_000,
            "max_records": 0,
        }
    ) == {
        "enabled": True,
        "max_transcript_chars": 1000,
        "max_handoff_chars": 4500,
        "retention_days": 3650,
        "max_records": 1,
    }


def test_normalize_config_caps_character_limits() -> None:
    assert normalize_config(
        {
            "enabled": False,
            "max_transcript_chars": 999_999,
            "max_handoff_chars": 99_999,
            "retention_days": "45",
            "max_records": "12",
        }
    ) == {
        "enabled": False,
        "max_transcript_chars": 200_000,
        "max_handoff_chars": 50_000,
        "retention_days": 45,
        "max_records": 12,
    }


def test_profile_storage_path_is_injected_and_never_hardcodes_a_home() -> None:
    assert profile_storage_path(Path("/tmp/profile-a/plugin-data")) == Path(
        "/tmp/profile-a/plugin-data/telegram-session-reset-handoff"
    )
    assert profile_storage_path("relative-state") == Path(
        "relative-state/telegram-session-reset-handoff"
    )


def test_registers_gateway_dispatch_finalize_and_handoff_auxiliary_task() -> None:
    class Context:
        def __init__(self) -> None:
            self.hooks: list[tuple[str, object]] = []
            self.auxiliary_tasks: list[tuple[str, dict[str, str]]] = []

        def register_hook(self, name: str, callback: object) -> None:
            self.hooks.append((name, callback))

        def register_auxiliary_task(self, name: str, **kwargs: str) -> None:
            self.auxiliary_tasks.append((name, kwargs))

    ctx = Context()
    register(ctx)

    assert [name for name, _ in ctx.hooks] == [
        "pre_gateway_dispatch",
        "on_session_finalize",
    ]
    assert ctx.auxiliary_tasks == [
        (
            "session-handoff",
            {
                "display_name": "Session Handoff",
                "description": "Create a concise handoff for a reset Telegram session.",
            },
        )
    ]
