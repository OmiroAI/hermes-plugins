import copy
import pytest
from collaborator_drive.executor import Executor
from collaborator_drive.gate import handle
from collaborator_drive.registry import Denied, Uncertain
from collaborator_drive.outcomes import PriorMutation


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
    with pytest.raises(PriorMutation):
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


def frame(source, kind="message"):
    return {"version": 1, "kind": kind, "source": source, "text": "review my document", "message_id": "test-message"}


def test_founder_private_and_trusted_group_only(registry, source, tmp_path):
    source["user_id"] = "owner-test"
    assert handle(frame(source), lambda: registry, {}, tmp_path) == {"decision": "allow"}
    source.update(chat_type="supergroup", chat_id="trusted-test")
    assert handle(frame(source), lambda: registry, {}, tmp_path)["decision"] == "allow"
    source["chat_id"] = "external-test"
    with pytest.raises(Denied):
        handle(frame(source), lambda: registry, {}, tmp_path)


def test_group_output_and_controls_do_not_expose_source(registry, source, drive, tmp_path):
    tmp_path.chmod(0o700)
    source["chat_type"] = "group"
    worker = lambda text, executor, config: "private source text"
    result = handle(frame(source), lambda: registry, {}, tmp_path, lambda: drive, worker)
    assert result["decision"] == "deny" and "private source text" not in result["reply"]
    for kind in ("reaction", "platform_event", "callback"):
        assert handle(frame(source, kind), lambda: registry, {}, tmp_path) == {"decision": "deny"}


def test_source_identity_unknown_and_policy_paused(registry, source, drive, tmp_path):
    tmp_path.chmod(0o700)
    source["user_id"] = None
    with pytest.raises(Denied):
        handle(frame(source), lambda: registry, {}, tmp_path)
    source["user_id"] = "collaborator-test"
    registry["activation"] = "paused"
    with pytest.raises(Uncertain):
        handle(frame(source), lambda: registry, {}, tmp_path)


def test_multiple_ventures_require_explicit_selection(registry, source, tmp_path):
    other = copy.deepcopy(registry["collaborators"][0])
    other["venture"] = "other-project"
    registry["collaborators"].append(other)
    with pytest.raises(Denied):
        handle(frame(source), lambda: registry, {}, tmp_path)


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
    with pytest.raises(PriorMutation):
        run.execute(arguments("replace_doc"))
    assert drive.calls == ["write"]


def test_permission_failure_pauses_entire_worker_before_delivery(registry, source, drive, tmp_path):
    from collaborator_drive.worker import respond
    from types import SimpleNamespace
    run = executor(registry, drive, source, tmp_path)
    call = SimpleNamespace(id="test-tool", function=SimpleNamespace(name="scoped_drive", arguments='{"operation":"inspect","target":"private_test_id","action":"draft","body":""}'))
    class Message:
        tool_calls = [call]
        def model_dump(self, **kwargs):
            return {"role": "assistant", "content": None}
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: SimpleNamespace(choices=[SimpleNamespace(message=Message())]))))
    with pytest.raises(Denied):
        respond("review", run, {"model": "synthetic-model"}, client=client)
    assert drive.calls == []


def test_group_delivery_contains_only_verified_draft_link(registry, source, drive, tmp_path):
    tmp_path.chmod(0o700)
    source["chat_type"] = "group"
    def worker(text, executor, config):
        executor.execute(arguments("create_draft", target="project_root_test"))
        return "private draft body"
    result = handle(frame(source), lambda: registry, {}, tmp_path, lambda: drive, worker)
    assert result == {"decision": "deny", "reply": "https://docs.google.com/document/d/new_document_test"}


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


def test_worker_receives_recorded_scope_without_identity_details(registry, source, drive, tmp_path):
    tmp_path.chmod(0o700)
    seen = []
    def worker(text, executor, config):
        seen.append(config)
        return "ready"
    handle(frame(source), lambda: registry, {}, tmp_path, lambda: drive, worker)
    assert seen[0]["venture"] == "test-project"
    assert seen[0]["allowed_actions"] == registry["collaborators"][0]["allowed_actions"]
    assert "google_email" not in seen[0] and "platform_user_id" not in seen[0]
