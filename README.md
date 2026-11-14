# Hermes Plugins

Native plugin collection. Compatibility is declared separately by each plugin.

## `telegram-session-reset-handoff`

Creates a one-time continuity summary for an automatic Telegram idle/daily reset (and watcher-first expiry case). It is **not auto-enabled** by this repository. See [its README](plugins/telegram-session-reset-handoff/README.md) for installation and enablement.

## `scoped-collaborator-drive`

Required external admission with a stateless Drive worker. See [installation, policy, SOUL template and limitations](plugins/scoped-collaborator-drive/README.md). Requires the companion core admission change; it does not patch Hermes.

## Development

```bash
uv run --with pytest python -m pytest plugins/telegram-session-reset-handoff/tests -q
```

The plugin is version-coupled to the tested Hermes runtime, rather than claiming broad compatibility.
