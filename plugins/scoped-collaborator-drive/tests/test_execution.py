import pytest
from collaborator_drive.executor import Executor
from collaborator_drive.registry import Denied, Uncertain


def arguments(operation="inspect", action="draft", target="document_test_id", body="draft body"):
    return dict(operation=operation, action=action, target=target, body=body)


def executor(registry, drive, source, tmp_path):
    return Executor(lambda: registry, drive, source, "test-project", tmp_path, "test-message")


def test_read_rechecks_revocation(registry, drive, source, tmp_path):
    run = executor(registry, drive, source, tmp_path)
    run.execute(arguments("read_text"))
    drive.acl.clear()
    with pytest.raises(Uncertain):
        run.recheck()


def test_write_revision_readback_and_deduplication(registry, drive, source, tmp_path):
    run = executor(registry, drive, source, tmp_path)
    assert run.execute(arguments("replace_doc"))["status"] == "verified"
    with pytest.raises(FileExistsError):
        run.execute(arguments("replace_doc", body="retry changed text"))
    assert drive.calls.count("write") == 1


def test_draft_checks_new_target_acl_and_readback(registry, drive, source, tmp_path):
    run = executor(registry, drive, source, tmp_path)
    assert run.execute(arguments("create_draft", target="project_root_test"))["document_id"] == "new_document_test"
    assert drive.calls == ["create", "write"]


def test_model_identity_and_unavailable_operations_denied(registry, drive, source, tmp_path):
    run = executor(registry, drive, source, tmp_path)
    bad = arguments()
    bad["user_id"] = "owner-test"
    with pytest.raises(Denied):
        run.execute(bad)
    for op in ("delete", "shell", "share", "send", "publish"):
        with pytest.raises(Denied):
            run.execute(arguments(op))
    assert drive.calls == []












def test_formatted_document_replacement_pauses_without_mutation(registry, source, drive, tmp_path):
    document = drive.document("document_test_id")
    document["body"]["content"][0]["paragraph"]["elements"][0]["textRun"]["textStyle"] = {"bold": True}
    drive.document = lambda target: document
    with pytest.raises(Uncertain):
        executor(registry, drive, source, tmp_path).execute(arguments("replace_doc"))
    assert drive.calls == []


def test_source_revocation_prevents_derived_write(registry, source, drive, tmp_path):
    run = executor(registry, drive, source, tmp_path)
    run.execute(arguments("read_text"))
    original = drive.permissions
    drive.permissions = lambda target: [] if target == "document_test_id" else original(target)
    with pytest.raises(Uncertain):
        run.execute(arguments("create_draft", target="project_root_test"))
    assert "create" not in drive.calls


def test_write_readback_failure_cannot_be_blindly_retried(registry, source, drive, tmp_path):
    run = executor(registry, drive, source, tmp_path)
    drive.insert = lambda *args: drive.calls.append("write")
    with pytest.raises(Uncertain):
        run.execute(arguments("replace_doc"))
    with pytest.raises(FileExistsError):
        run.execute(arguments("replace_doc"))
    assert drive.calls == ["write"]






def test_folder_listing_filters_inaccessible_children(registry, source, drive, tmp_path):
    drive.list_children = lambda target: ["document_test_id", "private_test_id"]
    run = executor(registry, drive, source, tmp_path)
    result = run.execute(arguments("list_folder", target="project_root_test"))
    assert [item["id"] for item in result["files"]] == ["document_test_id"]


def test_transcription_requires_recorded_action_and_configured_adapter(registry, source, drive, tmp_path):
    drive.items["document_test_id"]["mimeType"] = "video/mp4"
    run = executor(registry, drive, source, tmp_path)
    with pytest.raises(Denied):
        run.execute(arguments("transcribe", action="footage_review"))
    with pytest.raises(Uncertain):
        run.execute(arguments("transcribe", action="transcription"))
    assert drive.calls == []
