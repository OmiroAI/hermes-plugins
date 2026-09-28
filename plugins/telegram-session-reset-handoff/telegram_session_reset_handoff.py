"""Pure helpers and lifecycle registration for Telegram reset handoffs."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

DEFAULT_CONFIG = {
    "enabled": True,
    "max_transcript_chars": 24_000,
    "max_handoff_chars": 4_500,
    "retention_days": 30,
    "max_records": 200,
}

MIN_TRANSCRIPT_CHARS = 1_000
MAX_TRANSCRIPT_CHARS = 50_000
MIN_HANDOFF_CHARS = 250
MAX_HANDOFF_CHARS = 4_500
MIN_RETENTION_DAYS = 1
MAX_RETENTION_DAYS = 3_650
MIN_RECORDS = 1
MAX_RECORDS = 200

_LIMITS = {
    "max_transcript_chars": (MIN_TRANSCRIPT_CHARS, MAX_TRANSCRIPT_CHARS),
    "max_handoff_chars": (MIN_HANDOFF_CHARS, MAX_HANDOFF_CHARS),
    "retention_days": (MIN_RETENTION_DAYS, MAX_RETENTION_DAYS),
    "max_records": (MIN_RECORDS, MAX_RECORDS),
}


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    """Return a bounded integer, falling back safely for malformed settings."""
    if isinstance(value, bool):
        return default
    try:
        candidate = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return max(minimum, min(candidate, maximum))


def normalize_config(settings: Mapping[str, Any] | None) -> dict[str, bool | int]:
    """Return complete, bounded plugin settings without mutating caller data."""
    values: Mapping[str, Any] = settings if isinstance(settings, Mapping) else {}
    enabled = values.get("enabled", DEFAULT_CONFIG["enabled"])
    normalized: dict[str, bool | int] = {
        "enabled": enabled if isinstance(enabled, bool) else DEFAULT_CONFIG["enabled"],
    }
    for key, (minimum, maximum) in _LIMITS.items():
        normalized[key] = _bounded_int(
            values.get(key, DEFAULT_CONFIG[key]),
            default=DEFAULT_CONFIG[key],
            minimum=minimum,
            maximum=maximum,
        )
    return normalized


def profile_storage_path(plugin_data_root: str | Path) -> Path:
    """Build this plugin's path below a caller-injected profile-scoped data root."""
    return Path(plugin_data_root) / "telegram-session-reset-handoff"


def on_pre_gateway_dispatch(event: Any, gateway: Any, session_store: Any, **kwargs: Any) -> None:
    """Placeholder for the reset-message rewrite implemented in a later task."""
    return None


def on_session_finalize(**kwargs: Any) -> None:
    """Placeholder lifecycle callback; later tasks register finalization work here."""
    return None


def register(ctx: Any) -> None:
    """Register public lifecycle integration points without reading runtime state."""
    ctx.register_hook("pre_gateway_dispatch", on_pre_gateway_dispatch)
    ctx.register_hook("on_session_finalize", on_session_finalize)
    ctx.register_auxiliary_task(
        "telegram_session_reset_handoff",
        display_name="Session Handoff",
        description="Create a concise handoff for a reset Telegram session.",
    )
