"""Tests for pending reset markers and bounded predecessor transcript sources."""

from __future__ import annotations

from pathlib import Path
import sys
import threading

PLUGIN_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_DIR))

from telegram_session_reset_handoff import (  # noqa: E402
    TranscriptSource,
    create_pending_marker,
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


class BlockingState(FakeState):
    """State double that holds the first read open until the test releases it."""

    def __init__(self) -> None:
        super().__init__()
        self.first_get_entered = threading.Event()
        self.second_get_entered = threading.Event()
        self.release_first_get = threading.Event()
        self.transaction_events: list[str] = []
        self._guard = threading.Lock()
        self._get_count = 0

    def get(self, key: str, default: object = None) -> object:
        with self._guard:
            self._get_count += 1
            get_count = self._get_count
            self.transaction_events.append("get")
            self.get_calls.append((key, default))
        if get_count == 1:
            self.first_get_entered.set()
            assert self.release_first_get.wait(timeout=2), "test did not release the first read"
        else:
            self.second_get_entered.set()
        return self.values.get(key, default)

    def set(self, key: str, value: object) -> None:
        with self._guard:
            self.transaction_events.append("set")
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


def test_concurrent_pending_marker_creation_serializes_get_set_transaction() -> None:
    state = BlockingState()
    results: list[bool | None] = [None, None]

    def create(index: int) -> None:
        results[index] = create_pending_marker(state, "shared-predecessor")

    first = threading.Thread(target=create, args=(0,))
    second = threading.Thread(target=create, args=(1,))
    first.start()
    assert state.first_get_entered.wait(timeout=2), "first call did not reach state.get"
    second.start()
    try:
        assert not state.second_get_entered.wait(timeout=0.2), (
            "second state.get interleaved before the first call completed its state.set"
        )
    finally:
        state.release_first_get.set()
        first.join(timeout=2)
        second.join(timeout=2)

    assert not first.is_alive()
    assert not second.is_alive()
    assert results == [True, True]
    assert state.transaction_events == ["get", "set", "get", "set"]
    assert read_pending_marker(state, "shared-predecessor") is not None
    assert len(state.values) == 1


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


def test_transcript_cap_never_skips_newest_oversized_entry_for_stale_messages() -> None:
    db = FakeDB(
        [
            {"role": "user", "content": "old initial request"},
            {"role": "assistant", "content": "stale but short"},
            {"role": "assistant", "content": "newest entry is too large"},
        ]
    )

    source = load_predecessor_transcript(db, "old-session", max_chars=len("assistant: stale but short"))

    assert source == TranscriptSource(text="", truncated=True, message_count=0)


def test_transcript_cap_keeps_only_a_contiguous_newest_suffix_before_initial_request() -> None:
    initial = "user: initial request"
    newest_suffix = "assistant: recent one\n\nassistant: recent two"
    db = FakeDB(
        [
            {"role": "user", "content": "initial request"},
            {"role": "assistant", "content": "stale entry that must not be retained"},
            {"role": "assistant", "content": "recent one"},
            {"role": "assistant", "content": "recent two"},
        ]
    )

    source = load_predecessor_transcript(db, "old-session", max_chars=len(initial + "\n\n" + newest_suffix))

    assert source == TranscriptSource(
        text=initial + "\n\n" + newest_suffix,
        truncated=True,
        message_count=3,
    )


def test_database_error_fails_open_without_transcript_content() -> None:
    db = FakeDB([], error=RuntimeError("database unavailable"))

    assert load_predecessor_transcript(db, "old-session", max_chars=1_000) == TranscriptSource(
        text="", truncated=False, message_count=0
    )
    assert db.calls == ["old-session"]
