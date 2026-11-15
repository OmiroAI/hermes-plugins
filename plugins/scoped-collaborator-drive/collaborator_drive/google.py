"""Google API adapter. ADC is provisioned by the operator, never by a collaborator."""
from .registry import Uncertain
from .guard import DOC

FIELDS = ("id,name,mimeType,parents,trashed,driveId,inheritedPermissionsDisabled,"
          "copyRequiresWriterPermission,contentRestrictions,downloadRestrictions,clientEncryptionDetails")
PERMISSIONS = ("nextPageToken,permissions(id,type,emailAddress,role,deleted,expirationTime,"
               "pendingOwner,view,permissionDetails,inheritedPermissionsDisabled)")


class GoogleDrive:
    def __init__(self):
        import google.auth
        from googleapiclient.discovery import build
        credentials, _ = google.auth.default(scopes=[
            "https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/documents"])
        self.drive = build("drive", "v3", credentials=credentials, cache_discovery=False)
        self.docs = build("docs", "v1", credentials=credentials, cache_discovery=False)

    def metadata(self, target):
        return self.drive.files().get(fileId=target, fields=FIELDS, supportsAllDrives=True).execute()

    def permissions(self, target):
        result, token = [], None
        for _ in range(20):
            page = self.drive.permissions().list(fileId=target, fields=PERMISSIONS, pageSize=100,
                pageToken=token, includePermissionsForView="published", supportsAllDrives=True).execute()
            result.extend(page.get("permissions", []))
            token = page.get("nextPageToken")
            if not token:
                return result
        raise Uncertain("Permission pagination limit exceeded.")

    def list_children(self, target):
        # Bounded first page; do not expose unchecked child metadata.
        page = self.drive.files().list(q="'" + target + "' in parents and trashed = false",
                                      fields="files(id)", pageSize=100).execute()
        return [item["id"] for item in page.get("files", [])]

    def download_media(self, target, path, limit):
        from googleapiclient.http import MediaIoBaseDownload
        size = self.drive.files().get(fileId=target, fields="size").execute().get("size")
        if not size or int(size) > limit:
            raise Uncertain("Unknown or oversized media.")
        with path.open("wb") as handle:
            download = MediaIoBaseDownload(handle, self.drive.files().get_media(fileId=target), chunksize=1048576)
            done = False
            while not done:
                _, done = download.next_chunk()
                if handle.tell() > limit:
                    raise Uncertain("Media exceeds download limit.")

    def document(self, target):
        return self.docs.documents().get(documentId=target).execute()

    def read_text(self, target, mime):
        if mime != DOC:
            raise Uncertain("This reference adapter reads Google Docs only.")
        return document_text(self.document(target))

    def insert(self, target, text, revision, end=1):
        requests = []
        if end > 1:
            requests.append({"deleteContentRange": {"range": {"startIndex": 1, "endIndex": end}}})
        requests.append({"insertText": {"location": {"index": 1}, "text": text}})
        self.docs.documents().batchUpdate(documentId=target, body={"requests": requests,
            "writeControl": {"requiredRevisionId": revision}}).execute()

    def create(self, parent):
        return self.drive.files().create(body={"name": "Collaborator draft", "mimeType": DOC,
                                              "parents": [parent]}, fields="id").execute()["id"]


def document_text(document):
    if len(document.get("tabs", [])) > 1 or not document.get("body"):
        raise Uncertain("Unsupported document body/tabs.")
    chunks = []
    for node in document["body"].get("content", []):
        if "table" in node or "tableOfContents" in node:
            raise Uncertain("Rich structures need targeted editing.")
        for element in node.get("paragraph", {}).get("elements", []):
            if set(element) - {"startIndex", "endIndex", "textRun"}:
                raise Uncertain("Unsupported document element.")
            if set(element.get("textRun", {}).get("textStyle", {})) - {"bold", "italic", "underline"}:
                raise Uncertain("Styled documents need targeted editing.")
            chunks.append(element.get("textRun", {}).get("content", ""))
    return "".join(chunks)


def require_plain_document(document):
    """Whole-body replacement must not silently strip formatting or suggestions."""
    document_text(document)
    for node in document["body"].get("content", []):
        if "sectionBreak" in node and node.get("startIndex", 0) != 0:
            raise Uncertain("Multiple document sections need targeted editing.")
        paragraph = node.get("paragraph", {})
        if set(paragraph) - {"elements", "paragraphStyle"}:
            raise Uncertain("Lists/suggestions need targeted editing.")
        style = paragraph.get("paragraphStyle", {})
        if set(style) - {"namedStyleType", "direction"} or style.get("namedStyleType", "NORMAL_TEXT") != "NORMAL_TEXT":
            raise Uncertain("Paragraph formatting needs targeted editing.")
        for element in paragraph.get("elements", []):
            run = element.get("textRun", {})
            if run.get("textStyle") or set(run) - {"content", "textStyle"}:
                raise Uncertain("Formatted/suggested text needs targeted editing.")
