# Telegram Session Reset Handoff

A plugin for **Hermes 0.21.0 only**. It adds a concise continuity handoff to the actual first LLM turn after a qualifying Telegram session reset. It is not auto-enabled.

## Install and enable

1. Copy or install this plugin directory into the active Hermes profile's plugin location using the Hermes plugin workflow for your installation.
2. Enable the plugin through Hermes's plugin configuration/UI; do not edit `config.yaml` by hand.
3. Keep `enabled: true` (the manifest default) or disable it through the plugin setting. Restart/reload only if Hermes asks.

No configuration has been changed by this repository.

## Runtime behavior

The plugin registers `on_session_finalize` and `pre_llm_call`, not `pre_gateway_dispatch`. Finalization only writes a compact marker. The summary generation and SessionDB read happen in the agent worker immediately before the first LLM request, so inbound gateway event-loop dispatch is not blocked. Errors, malformed state, incompatible runtime behavior, database failures, and model failures fail open: the current user message proceeds normally with no handoff.

Eligibility requires Telegram, a first turn, an explicit `parent_session_id`, exact equality of `source`, `session_key`, `chat_id`, `chat_type`, and `thread_id`, plus predecessor reason `idle`/`daily` or a watcher expiry marker. A `/new` or `/reset` (`new_session`) marker overrides expiry and rejects the handoff. Compression, suspension, resume-pending, and other end reasons do not qualify.

A predecessor-specific `fcntl.flock` plus a durable terminal attempt record gives at-most-once behavior across processes. The attempt is consumed before model work. A crash or model failure can therefore lose a handoff, intentionally avoiding duplicate model calls.

## Privacy and cleanup

Only bounded predecessor **user and assistant text** is sent to the currently configured model to make the summary. Nothing is externally messaged. The raw transcript is never persisted in plugin state; model output is rejected if it copies role-prefixed raw entries (including cross-field copies), or an unprefixed source-content entry of 24 or more characters. The threshold avoids rejecting short commonplace overlap.

State is a compact index plus a bounded dedicated lock directory. The index contains only hashes of predecessor session IDs, timestamps, markers, terminal status, and accepted summary data—never chat IDs or topic IDs. On marker and terminal writes the index is pruned by `retention_days` and `max_records`; old unreferenced lock files are then removed only after a nonblocking exclusive lock succeeds. Remove the plugin's profile `plugin-data` directory to erase this state on uninstall (after disabling/removing the plugin); deleting it also removes retained handoffs, markers, and locks.

## Settings

`max_transcript_chars`, `max_handoff_chars`, `retention_days`, and `max_records` are bounded in `plugin.yaml`. The defaults are 24,000 transcript characters, 4,500 handoff characters, 30 days, and 200 records.
