"""Conservative intersection of venture roots and current exact-target user ACLs."""
import re
from datetime import datetime, timezone
from .registry import Denied, PermissionUncertain, grant_for

READ = {"reader", "commenter", "writer", "owner"}
EDIT = {"writer", "owner"}
EXCLUDED = {"deletion", "sharing_changes", "publishing", "external_sends", "unrelated_private_sources"}
FOLDER = "application/vnd.google-apps.folder"
DOC = "application/vnd.google-apps.document"


def ancestry(adapter, target):
    chain, seen = [], set()
    for _ in range(32):
        if target in seen:
            raise PermissionUncertain("Ambiguous ancestry.")
        seen.add(target)
        try:
            item = adapter.metadata(target)
        except Exception as exc:
            raise PermissionUncertain("Drive metadata could not be established.") from exc
        if item.get("id") != target:
            raise PermissionUncertain("Metadata identity mismatch.")
        if item.get("trashed"):
            raise Denied("Trashed resource.")
        if item.get("driveId") or item.get("mimeType") == "application/vnd.google-apps.shortcut":
            raise PermissionUncertain("Shared drives and shortcuts need separate verification.")
        chain.append(item)
        parents = item.get("parents", [])
        if not parents:
            return chain
        if not isinstance(parents, list) or len(parents) != 1:
            raise PermissionUncertain("Ambiguous parent path.")
        target = parents[0]
    raise PermissionUncertain("Ancestry limit exceeded.")


def user_roles(acl, email):
    roles, direct = set(), False
    for permission in acl:
        if permission.get("type") != "user" or permission.get("emailAddress", "").casefold() != email.casefold():
            continue
        if permission.get("deleted") or permission.get("view"):
            continue
        if permission.get("inheritedPermissionsDisabled") or permission.get("pendingOwner"):
            raise PermissionUncertain("Uncertain collaborator permission.")
        expiry = permission.get("expirationTime")
        if expiry:
            try:
                if datetime.fromisoformat(expiry.replace("Z", "+00:00")) <= datetime.now(timezone.utc):
                    continue
            except (ValueError, TypeError):
                raise PermissionUncertain("Unknown permission expiry.") from None
        roles.add(permission.get("role"))
        direct |= permission.get("role") == "owner" or any(
            detail.get("inherited") is False for detail in permission.get("permissionDetails", []))
    if not roles:
        raise PermissionUncertain("Current exact-target user access cannot be established.")
    return roles, direct


def authorize(registry, adapter, source, venture, action, target, operation):
    entry = grant_for(registry, source, venture)
    if action in EXCLUDED or action in entry["exclusions"] or action not in entry["allowed_actions"]:
        raise Denied("Action is excluded or unapproved.")
    if operation not in {"read", "edit", "create"}:
        raise Denied("Unsupported operation.")
    if not isinstance(target, str) or not re.fullmatch(r"[A-Za-z0-9_-]{10,200}", target):
        raise Denied("Invalid resource ID.")
    chain = ancestry(adapter, target)
    if not any(m["id"] in entry["approved_drive_folder_ids"] for m in chain):
        raise Denied("Resource is outside the approved venture.")
    try:
        acl = adapter.permissions(target)
    except Exception as exc:
        raise PermissionUncertain("Drive permissions could not be established.") from exc
    roles, direct = user_roles(acl, entry["google_email"])
    if any(m.get("inheritedPermissionsDisabled") for m in chain) and not direct:
        raise PermissionUncertain("Limited-access ancestry needs direct permission evidence.")
    if not roles & (READ if operation == "read" else EDIT):
        raise Denied("Collaborator lacks the required role.")
    if operation != "read" and any(p.get("type") in {"group", "domain", "anyone"} or p.get("view") for p in acl):
        raise PermissionUncertain("Broad or published write audiences need separate approval.")
    item = chain[0]
    if operation == "create" and item.get("mimeType") != FOLDER:
        raise Denied("Draft destination must be a folder.")
    if item.get("clientEncryptionDetails", {}).get("encryptionState") not in (None, "unencrypted"):
        raise PermissionUncertain("Encrypted content.")
    if operation != "read" and any(r.get("readOnly") for r in item.get("contentRestrictions", [])):
        raise Denied("Content is read-only.")
    for restrictions in item.get("downloadRestrictions", {}).values():
        if not isinstance(restrictions, dict) or any(restrictions.values()):
            raise PermissionUncertain("Download restrictions need effective capability verification.")
    if operation == "read" and item.get("copyRequiresWriterPermission") and not roles & EDIT:
        raise Denied("Copy/download restricted.")
    return item
