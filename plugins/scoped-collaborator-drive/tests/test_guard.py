import copy
import pytest
from collaborator_drive.guard import authorize
from collaborator_drive.registry import Denied, Uncertain, load, validate


def check(registry, drive, source, **kwargs):
    return authorize(registry, drive, source, "test-project", kwargs.get("action", "draft"),
                     kwargs.get("target", "document_test_id"), kwargs.get("operation", "read"))


def test_allowed_current_permission_inside_venture(registry, drive, source):
    assert check(registry, drive, source)["id"] == "document_test_id"
    drive.acl[0]["role"] = "reader"
    assert check(registry, drive, source)["id"] == "document_test_id"
    with pytest.raises(Denied):
        check(registry, drive, source, operation="edit")


@pytest.mark.parametrize("action", ["deletion", "sharing_changes", "publishing", "external_sends", "unrelated_private_sources", "unknown"])
def test_excluded_actions(registry, drive, source, action):
    with pytest.raises(Denied):
        check(registry, drive, source, action=action)


def test_private_resource_and_unknown_identity(registry, drive, source):
    with pytest.raises(Denied):
        check(registry, drive, source, target="private_test_id")
    source["user_id"] = "unknown-test"
    with pytest.raises(Denied):
        check(registry, drive, source)


@pytest.mark.parametrize("acl", [[], [{"type": "group", "role": "writer"}],
    [{"type": "anyone", "role": "reader"}], [{"type": "user", "emailAddress": "agent@example.invalid", "role": "owner"}]])
def test_agent_access_never_substitutes_for_collaborator(registry, drive, source, acl):
    drive.acl = acl
    with pytest.raises(Uncertain):
        check(registry, drive, source)


@pytest.mark.parametrize("change", [{"expirationTime": "2000-01-01T00:00:00Z"}, {"expirationTime": "bad"},
    {"deleted": True}, {"view": "published"}, {"pendingOwner": True}, {"inheritedPermissionsDisabled": True}])
def test_uncertain_or_expired_permission_pauses(registry, drive, source, change):
    drive.acl[0].update(change)
    with pytest.raises(Uncertain):
        check(registry, drive, source)


@pytest.mark.parametrize("change", [{"driveId": "shared-test"}, {"mimeType": "application/vnd.google-apps.shortcut"},
    {"inheritedPermissionsDisabled": True}, {"downloadRestrictions": {"itemDownloadRestriction": {"restrictedForReaders": True}}},
    {"clientEncryptionDetails": {"encryptionState": "encrypted"}}])
def test_unsupported_resource_evidence_pauses(registry, drive, source, change):
    drive.items["document_test_id"].update(change)
    with pytest.raises(Uncertain):
        check(registry, drive, source)


def test_permission_checker_error_propagates_without_read(registry, drive, source):
    def unavailable(_):
        raise TimeoutError()
    drive.permissions = unavailable
    with pytest.raises(Uncertain):
        check(registry, drive, source)
    assert drive.calls == []


def test_revocation_and_venture_do_not_merge(registry, drive, source):
    registry["collaborators"][0]["status"] = "revoked"
    with pytest.raises(Denied):
        check(registry, drive, source)
    other = copy.deepcopy(registry["collaborators"][0])
    other.update(status="active", venture="other-project")
    registry["collaborators"].append(other)
    with pytest.raises(Denied):
        check(registry, drive, source)


def test_registry_duplicate_and_unknown_approver(registry, tmp_path):
    validate(registry)
    registry["collaborators"].append(copy.deepcopy(registry["collaborators"][0]))
    with pytest.raises(Uncertain):
        validate(registry)
    registry["collaborators"].pop()
    registry["collaborators"][0]["approving_founder"] = "unverified"
    with pytest.raises(Uncertain):
        validate(registry)
    path = tmp_path / "registry.json"
    path.write_text("{}")
    path.chmod(0o666)
    with pytest.raises(Uncertain):
        load(path)
