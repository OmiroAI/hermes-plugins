# Hermes Plugins

Native plugin collection for **Hermes 0.21.0**.

## `telegram-session-reset-handoff`

Creates a one-time continuity summary for an automatic Telegram idle/daily reset (and watcher-first expiry case). It is **not auto-enabled** by this repository. See [its README](plugins/telegram-session-reset-handoff/README.md) for installation and enablement.

## Development

```bash
uv run --with pytest python -m pytest plugins/telegram-session-reset-handoff/tests -q
```

The plugin is version-coupled to the tested Hermes runtime, rather than claiming broad compatibility.
