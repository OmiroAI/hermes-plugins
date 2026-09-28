"""Runtime-contract tests for the worker-side Telegram reset handoff."""

from __future__ import annotations

import sys
import threading
import time
import fcntl
from pathlib import Path
from types import SimpleNamespace

import pytest

PLUGIN_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_DIR))
import telegram_session_reset_handoff as handoff


@pytest.fixture(autouse=True)
def tested_runtime(monkeypatch):
    monkeypatch.setattr(handoff.importlib_metadata, "version", lambda _: "0.21.0")

VALID = {
    "objective": "Continue the implementation.",
    "status": "Tests remain.",
    "last_verified_action": "A check passed.",
    "next_action_owner": "Engineer.",
    "deadline_or_review": None,
    "blocker_or_decision": None,
    "source_note": "Prior Telegram session.",
}


class State:
    def __init__(self, tmp_path):
        self.values, self.data_dir = {}, tmp_path / "plugin-data"

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value


class Llm:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = (
            SimpleNamespace(parsed=VALID) if result is None else result,
            error,
            [],
        )

    def complete_structured(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.result


class Ctx:
    def __init__(self, tmp_path, llm=None):
        self.state, self.llm, self.hooks = State(tmp_path), llm or Llm(), []

    def get_config(self, key, default=None):
        return default

    def register_hook(self, name, callback):
        self.hooks.append((name, callback))

    def register_auxiliary_task(self, *args, **kwargs):
        pass


class DB:
    def __init__(self, rows, messages):
        self.rows, self.messages, self.closed = rows, messages, False

    def get_session(self, sid):
        return self.rows.get(sid)

    def get_messages_as_conversation(self, sid):
        return self.messages[sid]

    def close(self):
        self.closed = True


def row(
    sid,
    *,
    parent=None,
    end=None,
    source="telegram",
    session_key="key",
    chat_id="42",
    chat_type="group",
    thread_id="7",
):
    return {
        "id": sid,
        "parent_session_id": parent,
        "end_reason": end,
        "source": source,
        "session_key": session_key,
        "chat_id": chat_id,
        "chat_type": chat_type,
        "thread_id": thread_id,
    }


def setup(
    monkeypatch,
    tmp_path,
    *,
    end="idle",
    current_overrides=None,
    predecessor_overrides=None,
    llm=None,
):
    old, new = (
        row("old", end=end, **(predecessor_overrides or {})),
        row("new", parent="old", **(current_overrides or {})),
    )
    db = DB(
        {"old": old, "new": new},
        {"old": [{"role": "user", "content": "private predecessor request"}]},
    )
    monkeypatch.setattr(handoff, "open_session_db", lambda: db)
    return Ctx(tmp_path, llm), db


def test_idle_and_daily_successor_injects_context_without_rewriting_current_message(
    monkeypatch, tmp_path
):
    for end in ("idle", "daily"):
        ctx, db = setup(monkeypatch, tmp_path / end, end=end)
        result = handoff.on_pre_llm_call(
            ctx,
            session_id="new",
            user_message="ORIGINAL USER INPUT",
            conversation_history=[],
            is_first_turn=True,
            platform="telegram",
            sender_id="sender",
        )
        assert result and set(result) == {"context"}
        assert "ORIGINAL USER INPUT" not in result["context"]
        assert len(ctx.llm.calls) == 1 and db.closed


def test_route_isolation_requires_every_route_field(monkeypatch, tmp_path):
    for field, value in (
        ("thread_id", "other-topic"),
        ("chat_type", "private"),
        ("chat_id", "other-dm"),
        ("session_key", "other-key"),
    ):
        ctx, _ = setup(monkeypatch, tmp_path / field, current_overrides={field: value})
        assert (
            handoff.on_pre_llm_call(
                ctx,
                session_id="new",
                user_message="x",
                conversation_history=[],
                is_first_turn=True,
                platform="telegram",
            )
            is None
        )
        assert not ctx.llm.calls


def test_watcher_marker_allows_expired_predecessor_but_manual_marker_overrides(
    monkeypatch, tmp_path
):
    ctx, _ = setup(monkeypatch, tmp_path, end="session_expired")
    handoff.on_session_finalize(
        ctx, platform="telegram", reason="session_expired", session_id="old"
    )
    assert handoff.on_pre_llm_call(
        ctx,
        session_id="new",
        user_message="x",
        conversation_history=[],
        is_first_turn=True,
        platform="telegram",
    )
    ctx, _ = setup(monkeypatch, tmp_path / "manual", end="session_expired")
    handoff.on_session_finalize(
        ctx, platform="telegram", reason="session_expired", session_id="old"
    )
    handoff.on_session_finalize(
        ctx, platform="telegram", reason="new_session", session_id="old"
    )
    assert (
        handoff.on_pre_llm_call(
            ctx,
            session_id="new",
            user_message="x",
            conversation_history=[],
            is_first_turn=True,
            platform="telegram",
        )
        is None
    )


def test_bad_boundary_nonfirst_and_nontelegram_fail_open(monkeypatch, tmp_path):
    for end, first, platform in (
        ("compression", True, "telegram"),
        ("suspended", True, "telegram"),
        ("idle", False, "telegram"),
        ("idle", True, "discord"),
    ):
        ctx, _ = setup(monkeypatch, tmp_path / f"{end}-{first}-{platform}", end=end)
        assert (
            handoff.on_pre_llm_call(
                ctx,
                session_id="new",
                user_message="x",
                conversation_history=[{"role": "user"}] if not first else [],
                is_first_turn=first,
                platform=platform,
            )
            is None
        )
        assert not ctx.llm.calls


def test_session_db_adapter_failure_fails_open(monkeypatch, tmp_path):
    ctx, _ = setup(monkeypatch, tmp_path)
    monkeypatch.setattr(
        handoff,
        "open_session_db",
        lambda: (_ for _ in ()).throw(RuntimeError("active profile database unavailable")),
    )
    assert handoff.on_pre_llm_call(
        ctx,
        session_id="new",
        user_message="x",
        conversation_history=[],
        is_first_turn=True,
        platform="telegram",
    ) is None
    assert not ctx.llm.calls


def test_no_gateway_hook_and_manifest_runtime_contract(tmp_path):
    ctx = Ctx(tmp_path)
    handoff.register(ctx)
    assert [name for name, _ in ctx.hooks] == ["on_session_finalize", "pre_llm_call"]
    assert not hasattr(handoff, "on_pre_gateway_dispatch")
    manifest = (PLUGIN_DIR / "plugin.yaml").read_text()
    assert (
        "pre_gateway_dispatch" not in manifest
        and "pre_llm_call" in manifest
        and 'requires_hermes: "==0.21.0"' in manifest
        and "\nrequires:\n" not in manifest
    )


def test_register_skips_handoffs_when_posix_locks_are_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr(handoff, "_fcntl", None)
    ctx = Ctx(tmp_path)

    handoff.register(ctx)

    assert ctx.hooks == []


def test_concurrent_calls_attempt_once_and_model_failure_is_terminal(
    monkeypatch, tmp_path
):
    ctx, _ = setup(monkeypatch, tmp_path, llm=Llm(error=RuntimeError("down")))
    results = []
    threads = [
        threading.Thread(
            target=lambda: results.append(
                handoff.on_pre_llm_call(
                    ctx,
                    session_id="new",
                    user_message="x",
                    conversation_history=[],
                    is_first_turn=True,
                    platform="telegram",
                )
            )
        )
        for _ in range(2)
    ]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results == [None, None] and len(ctx.llm.calls) == 1
    assert "private predecessor request" not in repr(ctx.state.values)


def test_pruning_enforces_retention_and_record_count_without_raw_transcript(
    monkeypatch, tmp_path
):
    ctx, _ = setup(monkeypatch, tmp_path)
    settings = {"max_records": 1, "retention_days": 1}
    index = {
        "schema_version": 2,
        "records": {"a" * 64: {"created_at": 0}, "b" * 64: {"created_at": 100_000}},
    }
    handoff._prune(index, settings, now=100_001)
    assert index["records"] == {"b" * 64: {"created_at": 100_000}}
    ctx.get_config = lambda key, default=None: settings.get(key, default)
    handoff.on_session_finalize(
        ctx, platform="telegram", reason="session_expired", session_id="old"
    )
    assert handoff.on_pre_llm_call(
        ctx,
        session_id="new",
        user_message="x",
        conversation_history=[],
        is_first_turn=True,
        platform="telegram",
    )
    index = ctx.state.values[handoff.STATE_INDEX_KEY]
    assert len(index["records"]) == 1 and "private predecessor request" not in repr(
        index
    )


def test_index_write_prunes_only_old_unused_lock_files(tmp_path):
    state = State(tmp_path)
    settings = {"max_records": 1, "retention_days": 1}
    retained = handoff._digest("retained")
    old_unused = handoff._lock_path(state, "old-unused")
    recent_unused = handoff._lock_path(state, "recent-unused")
    active_unused = handoff._lock_path(state, "active-unused")
    retained_lock = handoff._lock_path(state, "retained")
    assert all((old_unused, recent_unused, active_unused, retained_lock))
    for path in (old_unused, recent_unused, active_unused, retained_lock):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    old = time.time() - 2 * 86400
    for path in (old_unused, active_unused, retained_lock):
        path.touch()
        import os

        os.utime(path, (old, old))
    with active_unused.open("a+b") as handle:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        index = {"schema_version": 2, "records": {retained: {"created_at": time.time()}}}
        assert handoff._write_index(state, index, settings)
        assert not old_unused.exists()
        assert recent_unused.exists() and active_unused.exists() and retained_lock.exists()


def test_pre_llm_held_predecessor_lock_fails_open_without_waiting_or_state(
    monkeypatch, tmp_path
):
    ctx, _ = setup(monkeypatch, tmp_path)
    lock_path = handoff._lock_path(ctx.state, "old")
    assert lock_path is not None
    lock_path.parent.mkdir(parents=True)
    with lock_path.open("a+b") as owner:
        fcntl.flock(owner.fileno(), fcntl.LOCK_EX)
        started = time.monotonic()
        assert handoff.on_pre_llm_call(
            ctx,
            session_id="new",
            user_message="x",
            conversation_history=[],
            is_first_turn=True,
            platform="telegram",
        ) is None
        assert time.monotonic() - started < 0.25
        assert not ctx.llm.calls and ctx.state.values == {}

    assert handoff.on_pre_llm_call(
        ctx,
        session_id="new",
        user_message="x",
        conversation_history=[],
        is_first_turn=True,
        platform="telegram",
    )
    assert len(ctx.llm.calls) == 1


def test_pre_llm_path_rewrites_legacy_record_to_allowlisted_metadata(monkeypatch, tmp_path):
    ctx, _ = setup(monkeypatch, tmp_path)
    key = handoff._digest("old")
    ctx.state.values[handoff.STATE_INDEX_KEY] = {
        "schema_version": 2,
        "records": {
            key: {
                "created_at": 1.0,
                "marker_expiry": True,
                "attempted": False,
                "consumed": False,
                "handoff": "PRIVATE LEGACY SUMMARY",
                "rendered": "PRIVATE LEGACY RENDERING",
                "arbitrary": ["stale"],
            }
        },
    }

    assert handoff.on_pre_llm_call(
        ctx,
        session_id="new",
        user_message="x",
        conversation_history=[],
        is_first_turn=True,
        platform="telegram",
    )

    record = ctx.state.values[handoff.STATE_INDEX_KEY]["records"][key]
    assert record == {
        "created_at": record["created_at"],
        "marker_expiry": True,
        "attempted": True,
        "consumed": True,
    }
    assert "PRIVATE LEGACY" not in repr(ctx.state.values)


@pytest.mark.parametrize(
    ("installed_version", "expected_calls"),
    (("0.21.0", 1), ("0.21.1", 0)),
)
def test_runtime_version_gate_runs_before_database_or_model_work(
    monkeypatch, tmp_path, installed_version, expected_calls
):
    ctx, _ = setup(monkeypatch, tmp_path)
    monkeypatch.setattr(handoff.importlib_metadata, "version", lambda _: installed_version)
    if expected_calls == 0:
        monkeypatch.setattr(
            handoff,
            "open_session_db",
            lambda: (_ for _ in ()).throw(AssertionError("version gate must precede DB")),
        )
    assert bool(
        handoff.on_pre_llm_call(
            ctx,
            session_id="new",
            user_message="x",
            conversation_history=[],
            is_first_turn=True,
            platform="telegram",
        )
    ) is (installed_version == "0.21.0")
    assert len(ctx.llm.calls) == expected_calls
    if expected_calls == 0:
        assert ctx.state.values == {}


def test_unavailable_runtime_version_fails_open_before_database_or_model_work(
    monkeypatch, tmp_path
):
    ctx, _ = setup(monkeypatch, tmp_path)
    monkeypatch.setattr(
        handoff.importlib_metadata,
        "version",
        lambda _: (_ for _ in ()).throw(handoff.importlib_metadata.PackageNotFoundError),
    )
    monkeypatch.setattr(
        handoff,
        "open_session_db",
        lambda: (_ for _ in ()).throw(AssertionError("version gate must precede DB")),
    )
    assert handoff.on_pre_llm_call(
        ctx,
        session_id="new",
        user_message="x",
        conversation_history=[],
        is_first_turn=True,
        platform="telegram",
    ) is None
    assert not ctx.llm.calls and ctx.state.values == {}


def test_finalize_version_gate_precedes_state_work(monkeypatch, tmp_path):
    ctx = Ctx(tmp_path)
    monkeypatch.setattr(handoff.importlib_metadata, "version", lambda _: "0.21.1")
    handoff.on_session_finalize(
        ctx, platform="telegram", reason="session_expired", session_id="old"
    )
    assert ctx.state.values == {}
