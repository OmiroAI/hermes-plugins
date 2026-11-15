"""Safe public outcomes. Exception text and private resource details never leave here."""
from .registry import Denied, Uncertain, MissingGrant, AmbiguousVenture, PermissionUncertain


class WriteUncertain(Uncertain):
    """A mutation API was invoked but the request did not finish successfully."""


class PriorMutation(Uncertain):
    """A persistent prior mutation record blocks automatic replay."""


def failure(exc):
    if isinstance(exc, WriteUncertain):
        text = "A Drive write was attempted, but its final result could not be verified. Work is paused; verify the destination before retrying."
    elif isinstance(exc, PriorMutation):
        text = "This message has a prior mutation record and was not replayed. Check that record before submitting another request."
    elif isinstance(exc, MissingGrant):
        text = "No active scoped grant matches your account and this chat. Ask a verified founder to approve the venture scope."
    elif isinstance(exc, AmbiguousVenture):
        text = "More than one approved venture matches. Specify one approved venture explicitly."
    elif isinstance(exc, Denied):
        text = "The requested action or resource is outside your approved scope or Drive access. No Drive write was attempted."
    elif isinstance(exc, PermissionUncertain):
        text = "Scoped permission evidence could not be verified. Work is paused. No Drive write was attempted."
    else:
        text = "The scoped request could not be completed. Work is paused. No Drive write was attempted."
    return {"decision": "deny", "reply": text}
