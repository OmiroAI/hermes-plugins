import copy
from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def source():
    return {"platform": "test-platform", "user_id": "collaborator-test", "chat_id": "dm-test", "chat_type": "private"}


@pytest.fixture
def registry():
    return {"version": 1, "activation": "active", "founders": {
        "founder-test": {"identities": [{"platform": "test-platform", "user_id": "owner-test"}],
                         "verification_source": "Synthetic test only"}},
        "trusted_chats": [{"platform": "test-platform", "chat_id": "trusted-test"}],
        "collaborators": [{"platform": "test-platform", "platform_user_id": "collaborator-test",
            "google_email": "collaborator@example.invalid", "venture": "test-project",
            "approved_drive_folder_ids": ["project_root_test"], "allowed_actions": ["footage_review", "transcription", "paper_edit", "draft"],
            "exclusions": ["deletion", "sharing_changes", "publishing", "external_sends", "unrelated_private_sources"],
            "approving_founder": "founder-test", "approval_source": "Synthetic approval fixture",
            "status": "active", "resource_scope": "venture_current_access", "task_approvals": []}]}


class FakeDrive:
    def __init__(self):
        self.items = {"project_root_test": {"id": "project_root_test", "mimeType": "application/vnd.google-apps.folder", "name": "Project"},
            "document_test_id": {"id": "document_test_id", "mimeType": "application/vnd.google-apps.document", "name": "Document", "parents": ["project_root_test"]},
            "private_test_id": {"id": "private_test_id", "mimeType": "application/vnd.google-apps.document", "name": "Private"}}
        self.acl = [{"type": "user", "emailAddress": "collaborator@example.invalid", "role": "writer"}]
        self.calls = []
        self.text = "original\n"

    def metadata(self, target):
        return copy.deepcopy(self.items[target])

    def permissions(self, target):
        return copy.deepcopy(self.acl)

    def read_text(self, target, mime):
        self.calls.append("read")
        return self.text

    def document(self, target):
        return {"revisionId": "test-revision", "body": {"content": [
            {"endIndex": len(self.text) + 1, "paragraph": {"elements": [{"textRun": {"content": self.text}}]}}]}}

    def insert(self, target, text, revision, end=1):
        self.calls.append("write")
        self.text = text + "\n"

    def create(self, parent):
        self.calls.append("create")
        self.items["new_document_test"] = {"id": "new_document_test", "mimeType": "application/vnd.google-apps.document",
            "name": "Draft", "parents": [parent]}
        return "new_document_test"


@pytest.fixture
def drive():
    return FakeDrive()
