"""Optional real Hermes discovery and admission-command integration.

Set HERMES_AGENT_SOURCE to the companion source checkout. No live credentials.
"""
import asyncio
import json
import os
from pathlib import Path
import sys
import pytest

CORE = os.environ.get("HERMES_AGENT_SOURCE")
pytestmark = pytest.mark.skipif(not CORE, reason="companion Hermes checkout not selected")
PLUGIN = Path(__file__).resolve().parents[1]


def test_real_core_command_and_missing_worker_fail_closed(registry, source, tmp_path, monkeypatch):
    sys.path.insert(0, CORE)
    from gateway import admission_policy
    reg = tmp_path / "registry.json"
    reg.write_text(json.dumps(registry))
    reg.chmod(0o600)
    config = tmp_path / "worker.json"
    config.write_text('{}')
    worker_command = [sys.executable, "-m", "collaborator_drive.gate", "--registry", str(reg),
        "--worker-config", str(config), "--state-dir", str(tmp_path)]
    monkeypatch.setenv("PYTHONPATH", str(PLUGIN))
    monkeypatch.setattr(admission_policy, "_settings", lambda: {"command": worker_command, "timeout_seconds": 5})
    owner = dict(source, user_id="owner-test")
    assert asyncio.run(admission_policy.admit_gateway_event("message", owner)).allow
    assert not asyncio.run(admission_policy.admit_gateway_event("callback", source)).allow
    unknown = dict(source, user_id="unknown-test")
    result = asyncio.run(admission_policy.admit_gateway_event("message", unknown))
    assert not result.allow and "No active scoped grant" in result.reply
    # Inactive collaborator is denied before any Google/model credential lookup.
    registry["collaborators"][0]["status"] = "revoked"
    reg.write_text(json.dumps(registry))
    assert not asyncio.run(admission_policy.admit_gateway_event("message", source)).allow
    missing = worker_command.copy()
    missing[0] = "/missing-collaborator-worker"
    monkeypatch.setattr(admission_policy, "_settings", lambda: {"command": missing})
    assert not asyncio.run(admission_policy.admit_gateway_event("message", owner)).allow


def test_native_discovery_uses_public_context_only(tmp_path, monkeypatch):
    sys.path.insert(0, CORE)
    home = tmp_path / "home"
    (home / "plugins").mkdir(parents=True)
    (home / "plugins" / "scoped-collaborator-drive").symlink_to(PLUGIN, target_is_directory=True)
    (home / "config.yaml").write_text('plugins:\n  enabled: [scoped-collaborator-drive]\n')
    monkeypatch.setenv("HERMES_HOME", str(home))
    from hermes_cli.plugins import PluginManager
    manager = PluginManager(scope_key=str(home))
    manager.discover_and_load()
    assert "collaborator-check" in manager._cli_commands
    command = manager._cli_commands["collaborator-check"]
    import argparse
    parser = argparse.ArgumentParser()
    command["setup_fn"](parser)
    assert parser.parse_args(["test-registry"]).registry == "test-registry"
