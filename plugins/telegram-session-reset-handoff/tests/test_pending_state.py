"""Tests for pending reset markers and bounded predecessor transcript sources."""

from __future__ import annotations

from pathlib import Path
import sys

PLUGIN_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_DIR))

from telegram_session_reset_handoff import (  # noqa: E402
    TranscriptSource,
    load_predecessor_transcript,
    on_session_finalize,
    pending_marker_key,
    read_pending_marker,
    register,
)


class FakeState:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}
        self.get_calls: list[tuple[str, object]] = []
        self.set_calls: list[tuple[str, object]] = []

    def get(self, key: str, default: object = None) -> object:
        self.get_calls.append((key, default))
        return self.values.get(key, default)

    def set(self, key: str, value: object) -> None:
        self.set_calls.append((key, value))
        self.values[key] = value


class Context:
    def __init__(self) -> None:
        self.state = FakeState()
        self.hooks: list[tuple[str, object]] = []
        self.auxiliary_tasks: list[tuple[str, dict[str, str]]] = []

    def register_hook(self, name: str, callback: object) -> None:
        self.hooks.append((name, callback))

    def register_auxiliary_task(self, name: str, **kwargs: str) -> None:
        self.auxiliary_tasks.append((name, kwargs))


def test_non_telegram_wrong_reason_and_missing_session_are_ignored() -> None:
    ctx = Context()

    on_session_finalize(ctx, platform="discord", reason="session_expired", session_id="old")
    on_session_finalize(ctx, platform="telegram", reason="new_session", session_id="old")
    on_session_finalize(ctx, platform="telegram", reason="session_expired", session_id="")

    assert ctx.state.get_calls == []
    assert ctx.state.set_calls == []


def test_valid_finalization_creates_an_idempotent_pending_marker() -> None:
    ctx = Context()

    on_session_finalize(
        ctx,
        platform="telegram",
        reason="session_expired",
        session_id="old-session-1",
    )
    marker = read_pending_marker(ctx.state, "old-session-1")
    on_session_finalize(
        ctx,
        platform="telegram",
        reason="session_expired",
        session_id="old-session-1",
    )

    key = pending_marker_key("old-session-1")
    assert list(ctx.state.values) == [key]
    assert marker is not None
    assert ctx.state.values[key] == marker
    assert marker["schema_version"] == 1
    assert marker["old_session_id"] == "old-session-1"
    assert isinstance(marker["created_at"], float)
    assert marker["pending"] is True


def test_registers_context_bound_finalize_callback() -> None:
    ctx = Context()
    register(ctx)
    callbacks = dict(ctx.hooks)

    callbacks["on_session_finalize"](
        platform="telegram", reason="session_expired", session_id="predecessor", created_at=1.0
    )

    assert read_pending_marker(ctx.state, "predecessor") is not None


def test_malformed_foreign_or_mismatched_pending_state_is_rejected() -> None:
    state = FakeState()
    key = pending_marker_key("expected")
    malformed_records = [
        "not-an-object",
        {"schema_version": 99, "old_session_id": "expected", "created_at": 1.0, "pending": True},
        {"schema_version": 1, "old_session_id": "other", "created_at": 1.0, "pending": True},
        {"schema_version": 1, "old_session_id": "expected", "created_at": "later", "pending": True},
        {"schema_version": 1, "old_session_id": "expected", "created_at": 1.0, "pending": False},
        {
            "schema_version": 1,
            "old_session_id": "expected",
            "created_at": 1.0,
            "pending": True,
            "transcript": "must not be accepted",
        },
    ]

    for record in malformed_records:
        state.values[key] = record
        assert read_pending_marker(state, "expected") is None


def test_malformed_existing_state_is_not_overwritten() -> None:
    ctx = Context()
    key = pending_marker_key("old-session")
    ctx.state.values[key] = {"foreign": "record"}

    on_session_finalize(ctx, platform="telegram", reason="session_expired", session_id="old-session")

    assert ctx.state.values[key] == {"foreign": "record"}


class FakeDB:
    def __init__(self, messages: list[dict[str, object]], error: Exception | None = None) -> None:
        self.messages = messages
        self.error = error
        self.calls: list[str] = []

    def get_messages_as_conversation(self, session_id: str) -> list[dict[str, object]]:
        self.calls.append(session_id)
        if self.error is not None:
            raise self.error
        return self.messages


def test_transcript_source_strips_nontext_tool_system_and_meta_payloads() -> None:
    db = FakeDB(
        [
            {"role": "system", "content": "system instructions"},
            {"role": "user", "content": "Initial request"},
            {"role": "assistant", "content": "First answer"},
            {"role": "tool", "content": "tool output"},
            {"role": "assistant", "content": [{"type": "text", "text": "not plain text"}]},
            {"role": "session_meta", "content": "metadata"},
            {"role": "assistant", "content": "Final answer"},
        ]
    )

    source = load_predecessor_transcript(db, "old-session", max_chars=1_000)

    assert source == TranscriptSource(
        text="user: Initial request\n\nassistant: First answer\n\nassistant: Final answer",
        truncated=False,
        message_count=3,
    )
    assert db.calls == ["old-session"]


def test_transcript_cap_keeps_initial_request_when_it_fits_and_preserves_order() -> None:
    initial = "user: initial question"
    newest = "assistant: newest update"
    db = FakeDB(
        [
            {"role": "user", "content": "initial question"},
            {"role": "assistant", "content": "middle context that does not fit"},
            {"role": "assistant", "content": "newest update"},
        ]
    )

    source = load_predecessor_transcript(db, "old-session", max_chars=len(initial + "\n\n" + newest))

    assert source == TranscriptSource(
        text=initial + "\n\n" + newest,
        truncated=True,
        message_count=2,
    )


def test_database_error_fails_open_without_transcript_content() -> None:
    db = FakeDB([], error=RuntimeError("database unavailable"))

    assert load_predecessor_transcript(db, "old-session", max_chars=1_000) == TranscriptSource(
        text="", truncated=False, message_count=0
    )
    assert db.calls == ["old-session"]
