"""Safe state and transcript helpers for Telegram reset handoffs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import math
from pathlib import Path
import threading
import time
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
PENDING_MARKER_SCHEMA_VERSION = 1
_PENDING_MARKER_PREFIX = "pending:"
_PENDING_MARKER_FIELDS = frozenset({"schema_version", "old_session_id", "created_at", "pending"})
_MISSING = object()
# Serializes same-gateway-process callbacks; ctx.state.set supplies the atomic durable write.
# Hermes exposes no cross-process transaction for the get/validate/set sequence.
_PENDING_MARKER_TRANSACTION_LOCK = threading.RLock()

_LIMITS = {
    "max_transcript_chars": (MIN_TRANSCRIPT_CHARS, MAX_TRANSCRIPT_CHARS),
    "max_handoff_chars": (MIN_HANDOFF_CHARS, MAX_HANDOFF_CHARS),
    "retention_days": (MIN_RETENTION_DAYS, MAX_RETENTION_DAYS),
    "max_records": (MIN_RECORDS, MAX_RECORDS),
}


@dataclass(frozen=True)
class TranscriptSource:
    """A bounded, text-only predecessor transcript suitable for later processing."""

    text: str
    truncated: bool
    message_count: int


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


def pending_marker_key(predecessor_session_id: str) -> str:
    """Return a state-safe key deterministically bound to one predecessor session."""
    digest = hashlib.sha256(predecessor_session_id.encode("utf-8")).hexdigest()
    return f"{_PENDING_MARKER_PREFIX}{digest}"


def _valid_pending_marker(record: Any, predecessor_session_id: str) -> dict[str, Any] | None:
    """Validate the complete minimal marker schema without attempting repair."""
    if not isinstance(record, Mapping) or set(record) != _PENDING_MARKER_FIELDS:
        return None
    created_at = record.get("created_at")
    if (
        record.get("schema_version") != PENDING_MARKER_SCHEMA_VERSION
        or record.get("old_session_id") != predecessor_session_id
        or record.get("pending") is not True
        or isinstance(created_at, bool)
        or not isinstance(created_at, (int, float))
        or not math.isfinite(created_at)
    ):
        return None
    return {
        "schema_version": PENDING_MARKER_SCHEMA_VERSION,
        "old_session_id": predecessor_session_id,
        "created_at": float(created_at),
        "pending": True,
    }


def read_pending_marker(state: Any, predecessor_session_id: str) -> dict[str, Any] | None:
    """Return a validated pending marker, or nothing when state is unsafe to use."""
    if not isinstance(predecessor_session_id, str) or not predecessor_session_id:
        return None
    try:
        record = state.get(pending_marker_key(predecessor_session_id), None)
    except Exception:
        return None
    return _valid_pending_marker(record, predecessor_session_id)


def create_pending_marker(state: Any, predecessor_session_id: str) -> bool:
    """Create or validate-and-refresh a pending marker without raising."""
    if not isinstance(predecessor_session_id, str) or not predecessor_session_id:
        return False
    try:
        # Keep validation and the durable write in one process-local transaction.
        with _PENDING_MARKER_TRANSACTION_LOCK:
            key = pending_marker_key(predecessor_session_id)
            existing = state.get(key, _MISSING)
            if existing is _MISSING:
                marker = {
                    "schema_version": PENDING_MARKER_SCHEMA_VERSION,
                    "old_session_id": predecessor_session_id,
                    "created_at": time.time(),
                    "pending": True,
                }
            else:
                marker = _valid_pending_marker(existing, predecessor_session_id)
                if marker is None:
                    return False
            state.set(key, marker)
    except Exception:
        return False
    return True


def on_session_finalize(ctx: Any, **kwargs: Any) -> None:
    """Mark only expired Telegram predecessors as pending, without raising."""
    session_id = kwargs.get("session_id")
    if (
        kwargs.get("platform") != "telegram"
        or kwargs.get("reason") != "session_expired"
        or not isinstance(session_id, str)
        or not session_id
    ):
        return None
    try:
        create_pending_marker(ctx.state, session_id)
    except Exception:
        pass
    return None


def _text_entries(messages: Sequence[Any]) -> list[tuple[str, str]]:
    """Extract only user/assistant messages with plain textual content in source order."""
    entries: list[tuple[str, str]] = []
    for message in messages:
        if not isinstance(message, Mapping):
            continue
        role = message.get("role")
        content = message.get("content")
        if role in {"user", "assistant"} and isinstance(content, str) and content:
            entries.append((role, f"{role}: {content}"))
    return entries


def load_predecessor_transcript(
    session_db: Any, predecessor_session_id: str, *, max_chars: int
) -> TranscriptSource:
    """Read and shape a bounded text-only source transcript; failures are empty."""
    if (
        not isinstance(predecessor_session_id, str)
        or not predecessor_session_id
        or isinstance(max_chars, bool)
        or not isinstance(max_chars, int)
        or max_chars <= 0
    ):
        return TranscriptSource(text="", truncated=False, message_count=0)
    try:
        messages = session_db.get_messages_as_conversation(predecessor_session_id)
    except Exception:
        return TranscriptSource(text="", truncated=False, message_count=0)
    if not isinstance(messages, Sequence) or isinstance(messages, (str, bytes, bytearray)):
        return TranscriptSource(text="", truncated=False, message_count=0)

    entries = _text_entries(messages)
    selected: set[int] = set()

    def rendered(indices: set[int]) -> str:
        return "\n\n".join(entries[index][1] for index in sorted(indices))

    initial_user_index = next(
        (index for index, (role, _) in enumerate(entries) if role == "user"), None
    )
    if initial_user_index is not None and len(entries[initial_user_index][1]) <= max_chars:
        selected.add(initial_user_index)

    for index in range(len(entries) - 1, -1, -1):
        if index in selected:
            continue
        candidate = selected | {index}
        if len(rendered(candidate)) <= max_chars:
            selected = candidate

    text = rendered(selected)
    return TranscriptSource(
        text=text,
        truncated=len(selected) < len(entries),
        message_count=len(selected),
    )


def on_pre_gateway_dispatch(ctx: Any, event: Any, gateway: Any, session_store: Any, **kwargs: Any) -> None:
    """Placeholder for the reset-message rewrite implemented in a later task."""
    return None


def register(ctx: Any) -> None:
    """Register context-bound public lifecycle integration points."""
    def pre_gateway_dispatch_callback(*args: Any, **kwargs: Any) -> None:
        on_pre_gateway_dispatch(ctx, *args, **kwargs)

    def session_finalize_callback(**kwargs: Any) -> None:
        on_session_finalize(ctx, **kwargs)

    ctx.register_hook("pre_gateway_dispatch", pre_gateway_dispatch_callback)
    ctx.register_hook("on_session_finalize", session_finalize_callback)
    ctx.register_auxiliary_task(
        "telegram_session_reset_handoff",
        display_name="Session Handoff",
        description="Create a concise handoff for a reset Telegram session.",
    )
