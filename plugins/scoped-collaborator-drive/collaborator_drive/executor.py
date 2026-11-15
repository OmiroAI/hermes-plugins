"""Fixed operations; immutable transport identity and venture stay outside model arguments."""
import hashlib
import json
import os
from pathlib import Path
from .guard import DOC, FOLDER, authorize
from .google import document_text, require_plain_document
from .registry import Denied, Uncertain

OPERATIONS = {"inspect": "read", "read_text": "read", "list_folder": "read", "transcribe": "read", "create_draft": "create", "replace_doc": "edit"}


class Executor:
    def __init__(self, loader, adapter, source, venture, state_dir, message_id, config=None):
        self.loader, self.adapter, self.source, self.venture = loader, adapter, source, venture
        self.state_dir, self.message_id = Path(state_dir), message_id
        self.sources, self.drafts = {}, []
        self.config = config or {}

    def check(self, target, action, operation):
        return authorize(self.loader(), self.adapter, self.source, self.venture, action, target, operation)

    def recheck(self):
        for target, action in self.sources.items():
            self.check(target, action, "read")
        for target, action in self.drafts:
            self.check(target, action, "read")

    def _mark_write(self):
        if not self.message_id:
            raise Uncertain("Writes require a stable transport message ID.")
        identity = [self.source, self.venture, self.message_id]
        key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        # One mutation per inbound message; an attempt is durable before the API call.
        # Never delete automatically: timeout may have committed an unknown result.
        with (self.state_dir / ("write-" + key)).open("x") as marker:
            marker.write("attempted\n")
            marker.flush()
            os.fsync(marker.fileno())

    def execute(self, arguments):
        if not isinstance(arguments, dict) or set(arguments) != {"operation", "target", "action", "body"}:
            raise Denied("Unknown operation arguments.")
        op, target, action, body = (arguments[k] for k in ("operation", "target", "action", "body"))
        if op not in OPERATIONS or not isinstance(action, str):
            raise Denied("Unsupported operation.")
        if not isinstance(body, str) or len(body) > 120000:
            raise Denied("Invalid body.")
        if op in {"create_draft", "replace_doc"} and action not in {"paper_edit", "draft"}:
            raise Denied("Document writes require paper_edit or draft approval.")
        if op == "transcribe" and action != "transcription":
            raise Denied("Transcription approval is required.")
        item = self.check(target, action, OPERATIONS[op])
        if op == "inspect":
            self.sources[target] = action
            return {k: item[k] for k in ("id", "name", "mimeType")}
        if op == "list_folder":
            if item["mimeType"] != FOLDER:
                raise Denied("Not a folder.")
            self.sources[target] = action
            visible = []
            for child in self.adapter.list_children(target):
                try:
                    metadata = self.check(child, action, "read")
                except (Denied, Uncertain):
                    continue
                self.sources[child] = action
                visible.append({key: metadata[key] for key in ("id", "name", "mimeType")})
            self.recheck()
            return {"files": visible, "limit": "First 100 children; unauthorized items omitted."}
        if op == "transcribe":
            if not item["mimeType"].startswith(("audio/", "video/")):
                raise Denied("Not audio/video.")
            from .media import transcribe
            self.sources[target] = action
            result = transcribe(self.adapter, target, self.config.get("transcriber_command"),
                                self.config.get("ffmpeg_path", "/usr/bin/ffmpeg"))
            self.recheck()
            return result
        if op == "read_text":
            text = self.adapter.read_text(target, item["mimeType"])
            if len(text) > 120000:
                raise Uncertain("Document exceeds text limit.")
            self.sources[target] = action
            self.recheck()
            return {"text": text}
        if not body:
            raise Denied("Empty writes are not allowed.")
        self.recheck()
        if op == "replace_doc":
            if item["mimeType"] != DOC:
                raise Denied("Only plain Google Docs can be replaced.")
            document = self.adapter.document(target)
            require_plain_document(document)
            revision = document.get("revisionId")
            end = max((n.get("endIndex", 1) for n in document["body"].get("content", [])), default=1) - 1
            self.check(target, action, "edit")
            self._mark_write()
        else:
            self.check(target, action, "create")
            self._mark_write()
            target = self.adapter.create(target)
            self.check(target, action, "edit")
            document = self.adapter.document(target)
            revision, end = document.get("revisionId"), 1
        if not revision:
            raise Uncertain("Document revision is missing; verify any created draft before retrying.")
        self.recheck()
        self.check(target, action, "edit")
        self.adapter.insert(target, body, revision, max(end, 1))
        self.check(target, action, "read")
        if document_text(self.adapter.document(target)) != body + "\n":
            raise Uncertain("Write readback mismatch; verify destination before retrying.")
        self.drafts.append((target, action))
        self.recheck()
        return {"document_id": target, "status": "verified"}
