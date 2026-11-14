"""One operator-managed authority for routing and collaborator grants.

Recorded approval is not proof of human identity. Only a verified founder's
out-of-band operator may write this file; do not give the worker write access.
"""
import json
import os
import stat


class Denied(Exception):
    """An operation is outside the recorded grant."""


class Uncertain(Exception):
    """Evidence is insufficient; pause without fallback."""


def load(path):
    with open(path, encoding="utf-8") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o022:
            raise Uncertain("Registry must be a regular file without group/world write access.")
        raw = handle.read(262145)
    if len(raw) > 262144:
        raise Uncertain("Registry exceeds size limit.")
    registry = json.loads(raw)
    validate(registry)
    return registry


def validate(registry):
    if not isinstance(registry, dict) or registry.get("version") != 1:
        raise Uncertain("Unknown registry schema.")
    if registry.get("activation") not in {"active", "paused"}:
        raise Uncertain("Missing activation state.")
    founders = registry.get("founders")
    if not isinstance(founders, dict) or not founders:
        raise Uncertain("Verified founder mapping is missing.")
    for founder in founders.values():
        identities = founder.get("identities", [])
        if not identities or not founder.get("verification_source"):
            raise Uncertain("Founder identity provenance is required.")
        for identity in identities:
            if not all(isinstance(identity.get(k), str) and identity[k] for k in ("platform", "user_id")):
                raise Uncertain("Invalid founder identity.")
    if not isinstance(registry.get("trusted_chats"), list):
        raise Uncertain("Trusted chat list must be explicit.")
    keys = set()
    for entry in registry.get("collaborators", []):
        fields = ("platform", "platform_user_id", "google_email", "venture", "approving_founder", "approval_source")
        if not all(isinstance(entry.get(k), str) and entry[k] for k in fields):
            raise Uncertain("Incomplete collaborator identity/approval.")
        key = tuple(entry[k] for k in ("platform", "platform_user_id", "venture"))
        if key in keys:
            raise Uncertain("Duplicate collaborator grant.")
        keys.add(key)
        if entry["approving_founder"] not in founders or entry.get("status") not in {"active", "revoked"}:
            raise Uncertain("Invalid approving founder or status.")
        for field in ("approved_drive_folder_ids", "allowed_actions", "exclusions"):
            values = entry.get(field)
            if not isinstance(values, list) or not values or any(not isinstance(v, str) or not v for v in values):
                raise Uncertain("Incomplete collaborator scope.")
        if entry.get("resource_scope") != "venture_current_access":
            raise Uncertain("Unsupported resource rule.")


def founder_context(registry, source):
    identity = {"platform": source.get("platform"), "user_id": source.get("user_id")}
    known = any(identity in f["identities"] for f in registry["founders"].values())
    private = source.get("chat_type") in {"private", "dm"}
    trusted = {"platform": source.get("platform"), "chat_id": source.get("chat_id")} in registry["trusted_chats"]
    return known and (private or trusted)


def grant_for(registry, source, venture):
    if registry.get("activation") != "active":
        raise Uncertain("Collaborator work is paused.")
    found = [e for e in registry["collaborators"] if e["platform"] == source.get("platform")
             and e["platform_user_id"] == source.get("user_id") and e["venture"] == venture]
    if len(found) != 1 or found[0]["status"] != "active":
        raise Denied("No unique active grant.")
    return found[0]
