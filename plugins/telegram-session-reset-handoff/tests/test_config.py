"""Tests for pure session-reset-handoff configuration and path helpers."""

from __future__ import annotations

from pathlib import Path
import sys

PLUGIN_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_DIR))

from telegram_session_reset_handoff import (  # noqa: E402
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
    register,
)
import telegram_session_reset_handoff as handoff  # noqa: E402


def _manifest_config_schema() -> dict[str, dict[str, bool | int | str]]:
    """Parse this simple manifest schema using only the standard library."""
    schema: dict[str, dict[str, bool | int | str]] = {}
    current_key: str | None = None
    in_schema = False
    manifest = PLUGIN_DIR / "plugin.yaml"

    for line in manifest.read_text(encoding="utf-8").splitlines():
        if line == "config_schema:":
            in_schema = True
            continue
        if not in_schema:
            continue
        if line and not line.startswith(" "):
            break
        if line.startswith("  ") and not line.startswith("    ") and line.endswith(":"):
            current_key = line.strip()[:-1]
            schema[current_key] = {}
            continue
        if line.startswith("    ") and current_key is not None and ":" in line:
            field, raw_value = line.strip().split(":", 1)
            value = raw_value.strip()
            if value in {"true", "false"}:
                schema[current_key][field] = value == "true"
            elif value.lstrip("-").isdigit():
                schema[current_key][field] = int(value)
            else:
                schema[current_key][field] = value.removeprefix('"').removesuffix('"')

    return schema


def test_manifest_schema_matches_runtime_defaults_and_bounds() -> None:
    assert MAX_HANDOFF_CHARS * MAX_RECORDS <= 900_000
    assert _manifest_config_schema() == {
        "enabled": {
            "type": "bool",
            "default": DEFAULT_CONFIG["enabled"],
            "description": "Enable Telegram reset handoff processing.",
        },
        "max_transcript_chars": {
            "type": "int",
            "default": DEFAULT_CONFIG["max_transcript_chars"],
            "minimum": MIN_TRANSCRIPT_CHARS,
            "maximum": MAX_TRANSCRIPT_CHARS,
            "description": "Maximum source transcript characters considered for a handoff.",
        },
        "max_handoff_chars": {
            "type": "int",
            "default": DEFAULT_CONFIG["max_handoff_chars"],
            "minimum": MIN_HANDOFF_CHARS,
            "maximum": MAX_HANDOFF_CHARS,
            "description": "Maximum generated handoff characters retained per record.",
        },
        "retention_days": {
            "type": "int",
            "default": DEFAULT_CONFIG["retention_days"],
            "minimum": MIN_RETENTION_DAYS,
            "maximum": MAX_RETENTION_DAYS,
            "description": "Number of days to retain generated handoff records.",
        },
        "max_records": {
            "type": "int",
            "default": DEFAULT_CONFIG["max_records"],
            "minimum": MIN_RECORDS,
            "maximum": MAX_RECORDS,
            "description": "Maximum handoff records retained for the active profile.",
        },
    }


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
        "max_transcript_chars": MIN_TRANSCRIPT_CHARS,
        "max_handoff_chars": 4500,
        "retention_days": MAX_RETENTION_DAYS,
        "max_records": MIN_RECORDS,
    }


def test_normalize_config_caps_character_limits() -> None:
    assert normalize_config(
        {
            "enabled": False,
            "max_transcript_chars": 999_999,
            "max_handoff_chars": 99_999,
            "retention_days": "45",
            "max_records": 999_999,
        }
    ) == {
        "enabled": False,
        "max_transcript_chars": MAX_TRANSCRIPT_CHARS,
        "max_handoff_chars": MAX_HANDOFF_CHARS,
        "retention_days": 45,
        "max_records": MAX_RECORDS,
    }


def test_profile_storage_path_is_injected_and_never_hardcodes_a_home() -> None:
    assert profile_storage_path(Path("/tmp/profile-a/plugin-data")) == Path(
        "/tmp/profile-a/plugin-data/telegram-session-reset-handoff"
    )
    assert profile_storage_path("relative-state") == Path(
        "relative-state/telegram-session-reset-handoff"
    )


def test_registers_gateway_dispatch_finalize_and_namespaced_auxiliary_task() -> None:
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
            "telegram_session_reset_handoff",
            {
                "display_name": "Session Handoff",
                "description": "Create a concise handoff for a reset Telegram session.",
            },
        )
    ]


def test_registered_gateway_dispatch_callback_propagates_rewrite_directive(monkeypatch: object) -> None:
    class Context:
        def __init__(self) -> None:
            self.hooks: list[tuple[str, object]] = []

        def register_hook(self, name: str, callback: object) -> None:
            self.hooks.append((name, callback))

        def register_auxiliary_task(self, name: str, **kwargs: str) -> None:
            pass

    ctx = Context()
    directive = {"replace_event": {"text": "rewritten"}}

    def fake_pre_gateway_dispatch(*args: object, **kwargs: object) -> object:
        assert args == (ctx, "event", "gateway", "session-store")
        assert kwargs == {"trace_id": "trace"}
        return directive

    monkeypatch.setattr(handoff, "on_pre_gateway_dispatch", fake_pre_gateway_dispatch)
    register(ctx)

    callbacks = dict(ctx.hooks)
    assert callbacks["pre_gateway_dispatch"](
        "event", "gateway", "session-store", trace_id="trace"
    ) is directive
