"""One operator-managed authority for routing and collaborator grants.

Recorded approval is not proof of human identity. Only a verified founder's
out-of-band operator may write this file; do not give the worker write access.
"""

import json
import os
import stat


class Denied(Exception):
    """An operation is outside the recorded grant."""


class MissingGrant(Denied):
    """No active grant applies to this immutable identity and chat."""


class AmbiguousVenture(Denied):
    """Several active ventures apply and none was explicitly selected."""


class Uncertain(Exception):
    """Evidence is insufficient; pause without fallback."""


class PermissionUncertain(Uncertain):
    """Current resource/permission evidence cannot establish access."""


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


def _strings(record, fields):
    if not all(isinstance(record.get(key), str) and record[key] for key in fields):
        raise Uncertain("Incomplete identity or authorization record.")


def _chats(chats):
    if not isinstance(chats, list) or not chats:
        raise Uncertain("An explicit chat list is required.")
    for chat in chats:
        if not isinstance(chat, dict) or set(chat) != {"platform", "chat_id"}:
            raise Uncertain("Invalid scoped chat mapping.")
        _strings(chat, ("platform", "chat_id"))


def _scope(entry, founders):
    _strings(entry, ("venture", "approving_founder", "approval_source"))
    if entry["approving_founder"] not in founders or entry.get("status") not in {
        "active",
        "revoked",
    }:
        raise Uncertain("Invalid approving founder or status.")
    if entry.get("resource_scope") != "venture_current_access":
        raise Uncertain("Unsupported resource rule.")
    for key in ("approved_drive_folder_ids", "allowed_actions", "exclusions"):
        values = entry.get(key)
        if (
            not isinstance(values, list)
            or not values
            or any(not isinstance(v, str) or not v for v in values)
        ):
            raise Uncertain("Incomplete venture scope.")
    if "approved_chats" in entry:
        _chats(entry["approved_chats"])


def validate(registry):
    if not isinstance(registry, dict) or registry.get("version") != 1:
        raise Uncertain("Unknown registry schema.")
    if registry.get("activation") not in {"active", "paused"}:
        raise Uncertain("Missing activation state.")
    founders = registry.get("founders")
    if not isinstance(founders, dict) or not founders:
        raise Uncertain("Verified founder mapping is missing.")
    for founder in founders.values():
        if not founder.get("identities") or not founder.get("verification_source"):
            raise Uncertain("Founder identity provenance is required.")
        for identity in founder["identities"]:
            _strings(identity, ("platform", "user_id"))
    if not isinstance(registry.get("trusted_chats"), list):
        raise Uncertain("Trusted chat list must be explicit.")
    keys = set()
    for entry in registry.get("collaborators", []):
        _strings(entry, ("platform", "platform_user_id", "google_email"))
        _scope(entry, founders)
        key = tuple(entry[k] for k in ("platform", "platform_user_id", "venture"))
        if key in keys:
            raise Uncertain("Duplicate collaborator grant.")
        keys.add(key)
    keys = set()
    for route in registry.get("scoped_founder_routes", []):
        _scope(route, founders)
        if route.get("founder") not in founders:
            raise Uncertain("Scoped founder authority is unverified.")
        _chats(route.get("approved_chats"))
        key = (route["founder"], route["venture"])
        if key in keys:
            raise Uncertain("Duplicate scoped founder route.")
        keys.add(key)


def founder_context(registry, source):
    identity = {"platform": source.get("platform"), "user_id": source.get("user_id")}
    known = any(identity in f["identities"] for f in registry["founders"].values())
    private = source.get("chat_type") in {"private", "dm"}
    trusted = {"platform": source.get("platform"), "chat_id": source.get("chat_id")} in registry["trusted_chats"]
    return known and (private or trusted)


def chat_matches(entry, source):
    return "approved_chats" not in entry or {
        "platform": source.get("platform"), "chat_id": source.get("chat_id")
    } in entry["approved_chats"]


def effective_grants(registry, source):
    """Authority stays in protected records; an ordinary grant cannot select service access."""
    identity={"platform":source.get("platform"),"user_id":source.get("user_id")}
    ordinary=[dict(e,_scope_kind="collaborator") for e in registry["collaborators"]
        if e["platform"]==identity["platform"] and e["platform_user_id"]==identity["user_id"]
        and e["status"]=="active" and chat_matches(e,source)]
    founders=registry["founders"]
    delegated=[dict(route,_scope_kind="founder_service") for route in registry.get("scoped_founder_routes",[])
        if route["status"]=="active" and route.get("approving_founder") in founders and route.get("approval_source")
        and identity in founders[route["founder"]]["identities"] and chat_matches(route,source)]
    return ordinary+delegated


def grant_for(registry, source, venture):
    if registry.get("activation") != "active":
        raise Uncertain("Scoped work is paused.")
    found = [e for e in effective_grants(registry,source) if e["venture"]==venture]
    if len(found) != 1:
        raise MissingGrant("No unique active scoped grant.")
    return found[0]
