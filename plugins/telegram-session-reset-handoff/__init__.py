"""Telegram session reset handoff Hermes plugin."""

try:  # Native Hermes loads this module as a package.
    from .telegram_session_reset_handoff import register
except ImportError:  # Allow direct-file test collection from a hyphenated plugin directory.
    from telegram_session_reset_handoff import register

__all__ = ["register"]
