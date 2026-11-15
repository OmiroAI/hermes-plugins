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
from .outcomes import failure, WriteUncertain

PAUSED = "The scoped service did not return a verified result. Work is paused; check request status before retrying."


def handle(frame, loader, config, state_dir, adapter_factory=GoogleDrive, worker=respond):
    if not isinstance(frame, dict) or set(frame) != {"version", "kind", "source", "text", "message_id"} or frame["version"] != 1:
        raise registry.Denied("Invalid envelope.")
    current = loader()
    source = frame["source"]
    if not isinstance(source, dict) or not source.get("user_id"):
        raise registry.MissingGrant("Unknown transport identity.")
    if registry.founder_context(current, source):
        return {"decision": "allow"}
    if frame["kind"] != "message":
        return {"decision": "deny"}
    text = frame["text"]
    matches = [e for e in current["collaborators"] if e["platform"] == source.get("platform")
        and e["platform_user_id"] == source["user_id"] and e["status"] == "active"
        and registry.chat_matches(e, source)]
    if not matches:
        raise registry.MissingGrant("No active scoped grant for this account and chat.")
    if not isinstance(text, str) or not text.strip() or len(text) > 120000:
        raise registry.Denied("Missing or oversized request.")
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
        raise registry.AmbiguousVenture("Choose one approved venture explicitly.")
    entry = registry.grant_for(current, source, venture)
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
        try:
            request_config = dict(config, venture=venture, allowed_actions=entry["allowed_actions"], exclusions=entry["exclusions"])
            result = worker(text, executor, request_config)
            executor.recheck()
            if source.get("chat_type") not in {"private", "dm"}:
                links = ["https://docs.google.com/document/d/" + target for target, _ in executor.drafts]
                result = "\n".join(links) if links else ("Scoped read-only work completed. Private source text is withheld in this group." if executor.sources else "No verified Drive result is available. Provide a project link and an approved action.")
            if not isinstance(result, str) or not result.strip() or len(result) > 16000:
                raise registry.Uncertain("Invalid worker response.")
            return {"decision": "deny", "reply": result}
        except Exception as exc:
            if executor.write_attempted:
                raise WriteUncertain("Mutation attempted; request incomplete.") from exc
            raise


def dispatch(*args, **kwargs):
    """Return a bounded safe denial for every expected or unexpected failure."""
    try:
        return handle(*args, **kwargs)
    except Exception as exc:
        return failure(exc)



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
        verdict = dispatch(frame, lambda: registry.load(args.registry), config, args.state_dir)
    except Exception as exc:
        verdict = failure(exc)
    sys.stdout.write(json.dumps(verdict, allow_nan=False))


if __name__ == "__main__":
    main()
