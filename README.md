# Hermes Plugins

A public collection of native [Hermes Agent](https://hermes-agent.nousresearch.com/docs/developer-guide/plugins) plugins.

## Plugins

- `telegram-session-reset-handoff` — prepares concise handoffs for Telegram conversations that reset. It is scaffolding only in version 0.1.0 and is not enabled by this repository.

## Development

The plugin runtime uses only the Python standard library. Run its tests with:

```bash
uv run --with pytest python -m pytest plugins/telegram-session-reset-handoff/tests -q
```

See each plugin's `plugin.yaml` for its public configuration schema.
