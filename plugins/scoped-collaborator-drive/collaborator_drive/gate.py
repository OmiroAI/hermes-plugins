"""Admission-command protocol. A non-founder NEVER receives an allow verdict."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from . import registry
from .executor import Executor
from .google import GoogleDrive
from .worker import respond

PAUSED = "Scoped access or execution could not be verified. Work is paused; verify any attempted Drive changes before retrying."


def handle(frame, loader, config, state_dir, adapter_factory=GoogleDrive, worker=respond):
    if not isinstance(frame, dict) or set(frame) != {"version", "kind", "source", "text", "message_id"} or frame["version"] != 1:
        raise registry.Denied("Invalid envelope.")
    current = loader()
    source = frame["source"]
    if not isinstance(source, dict) or not source.get("user_id"):
        raise registry.Denied("Unknown transport identity.")
    if registry.founder_context(current, source):
        return {"decision": "allow"}
    if frame["kind"] != "message":
        return {"decision": "deny"}
    text = frame["text"]
    if not isinstance(text, str) or not text.strip() or len(text) > 120000:
        raise registry.Denied("Missing or oversized request.")
    matches = [e for e in current["collaborators"] if e["platform"] == source.get("platform")
        and e["platform_user_id"] == source["user_id"] and e["status"] == "active"]
    # A collaborator with several ventures explicitly chooses one using a JSON envelope.
    # Its identity always comes from the gateway, never that envelope.
    if text.lstrip().startswith('{"venture"'):
        request = json.loads(text)
        if set(request) != {"venture", "request"}:
            raise registry.Denied("Invalid venture request.")
        venture, text = request["venture"], request["request"]
    elif len(matches) == 1:
        venture = matches[0]["venture"]
    else:
        raise registry.Denied("Choose one approved venture explicitly.")
    registry.grant_for(current, source, venture)
    if not isinstance(text, str) or not text.strip() or len(text) > 120000:
        raise registry.Denied("Invalid request text.")
    info = os.stat(state_dir)
    if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o077:
        raise registry.Uncertain("Worker state directory must be private.")
    import fcntl  # POSIX reference worker; no unsupported locking fallback
    key = hashlib.sha256(json.dumps([source.get("platform"), source["user_id"]]).encode()).hexdigest()
    with (Path(state_dir) / ("lock-" + key)).open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        executor = Executor(loader, adapter_factory(), source, venture, state_dir, frame["message_id"], config)
        result = worker(text, executor, config)
        executor.recheck()
        if source.get("chat_type") not in {"private", "dm"}:
            links = ["https://docs.google.com/document/d/" + target for target, _ in executor.drafts]
            result = "\n".join(links) if links else "Scoped request completed. Private source text is withheld in groups."
        if not isinstance(result, str) or not result.strip() or len(result) > 16000:
            raise registry.Uncertain("Invalid worker response.")
        return {"decision": "deny", "reply": result}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", required=True)
    parser.add_argument("--worker-config", required=True)
    parser.add_argument("--state-dir", required=True)
    args = parser.parse_args()
    try:
        raw = sys.stdin.buffer.read(262145)
        if len(raw) > 262144:
            raise registry.Denied("Oversized request.")
        frame = json.loads(raw)
        # No credentials/model client are loaded for founder passthrough or denied controls.
        with open(args.worker_config, encoding="utf-8") as handle_config:
            config = json.load(handle_config)
        verdict = handle(frame, lambda: registry.load(args.registry), config, args.state_dir)
    except Exception:
        verdict = {"decision": "deny", "reply": PAUSED}
    sys.stdout.write(json.dumps(verdict, allow_nan=False))


if __name__ == "__main__":
    main()
