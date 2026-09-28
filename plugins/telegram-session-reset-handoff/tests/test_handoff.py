"""Privacy regression tests for the worker-side handoff."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

PLUGIN_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_DIR))
import telegram_session_reset_handoff as h

VALID = {
    "objective": "summary",
    "status": "status",
    "last_verified_action": None,
    "next_action_owner": None,
    "deadline_or_review": None,
    "blocker_or_decision": None,
    "source_note": None,
}


class State:
    def __init__(self, root):
        self.values = {}
        self.data_dir = root

    def get(self, k, d=None):
        return self.values.get(k, d)

    def set(self, k, v):
        self.values[k] = v


class DB:
    def __init__(self):
        self.rows = {
            "old": {
                "id": "old",
                "source": "telegram",
                "session_key": "k",
                "chat_id": "c",
                "chat_type": "group",
                "thread_id": "t",
                "end_reason": "idle",
            },
            "new": {
                "id": "new",
                "parent_session_id": "old",
                "source": "telegram",
                "session_key": "k",
                "chat_id": "c",
                "chat_type": "group",
                "thread_id": "t",
            },
        }

    def get_session(self, s):
        return self.rows[s]

    def get_messages_as_conversation(self, s):
        return [
            {"role": "user", "content": "PRIVATE RAW SOURCE"},
            {"role": "assistant", "content": "PRIVATE RESPONSE"},
        ]

    def close(self):
        pass


class Llm:
    def __init__(self, parsed):
        self.parsed = parsed
        self.calls = []

    def complete_structured(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(parsed=self.parsed)


def test_raw_transcript_copy_is_rejected_and_never_persisted(monkeypatch, tmp_path):
    db = DB()
    monkeypatch.setattr(h, "open_session_db", lambda: db)
    llm = Llm(dict(VALID, objective="user: PRIVATE RAW SOURCE"))
    ctx = SimpleNamespace(
        state=State(tmp_path), llm=llm, get_config=lambda k, d=None: d
    )
    assert (
        h.on_pre_llm_call(
            ctx,
            session_id="new",
            user_message="real current input",
            conversation_history=[],
            is_first_turn=True,
            platform="telegram",
        )
        is None
    )
    record = ctx.state.values[h.STATE_INDEX_KEY]["records"][h._digest("old")]
    assert (
        record["attempted"] is True
        and "handoff" not in record
        and "PRIVATE RAW SOURCE" not in repr(ctx.state.values)
    )


def test_unprefixed_long_raw_content_is_rejected_across_handoff_fields(monkeypatch, tmp_path):
    raw = "UNIQUE UNPREFIXED PREDECESSOR CONTENT THAT MUST NEVER SURVIVE"
    db = DB()
    db.get_messages_as_conversation = lambda _: [{"role": "user", "content": raw}]
    monkeypatch.setattr(h, "open_session_db", lambda: db)
    llm = Llm(
        dict(
            VALID,
            objective=raw[:31],
            status=raw[31:],
        )
    )
    ctx = SimpleNamespace(
        state=State(tmp_path), llm=llm, get_config=lambda k, d=None: d
    )
    assert h.on_pre_llm_call(
        ctx,
        session_id="new",
        user_message="real current input",
        conversation_history=[],
        is_first_turn=True,
        platform="telegram",
    ) is None
    record = ctx.state.values[h.STATE_INDEX_KEY]["records"][h._digest("old")]
    assert record["attempted"] is True and "handoff" not in record
    assert raw not in repr(ctx.state.values)


def test_unprefixed_long_raw_content_is_rejected_within_one_handoff_field(
    monkeypatch, tmp_path
):
    raw = "UNIQUE UNPREFIXED PREDECESSOR CONTENT THAT MUST NEVER SURVIVE"
    db = DB()
    db.get_messages_as_conversation = lambda _: [{"role": "assistant", "content": raw}]
    monkeypatch.setattr(h, "open_session_db", lambda: db)
    ctx = SimpleNamespace(
        state=State(tmp_path),
        llm=Llm(dict(VALID, objective=raw)),
        get_config=lambda k, d=None: d,
    )
    assert h.on_pre_llm_call(
        ctx,
        session_id="new",
        user_message="real current input",
        conversation_history=[],
        is_first_turn=True,
        platform="telegram",
    ) is None
    record = ctx.state.values[h.STATE_INDEX_KEY]["records"][h._digest("old")]
    assert "handoff" not in record and raw not in repr(ctx.state.values)


def test_transcript_loads_only_user_assistant_and_caps_newest_suffix():
    db = SimpleNamespace(
        get_messages_as_conversation=lambda _: [
            {"role": "system", "content": "skip"},
            {"role": "user", "content": "first"},
            {"role": "tool", "content": "skip"},
            {"role": "assistant", "content": "newest"},
        ]
    )
    source = h.load_predecessor_transcript(
        db, "old", max_chars=len("assistant: newest")
    )
    assert source.entries == ("assistant: newest",) and source.truncated
    assert source.contents == ("newest",)
