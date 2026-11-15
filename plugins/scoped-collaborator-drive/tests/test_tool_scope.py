from types import SimpleNamespace
import pytest
from collaborator_drive.worker import respond, scoped_tool
from collaborator_drive.registry import Uncertain


def test_chat_transport_exposes_only_current_grant_actions():
    tools=[]
    def create(**kwargs):
        tools.append(kwargs['tools'][0]['function'])
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[],content='clarify'))])
    client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    executor=SimpleNamespace(recheck=lambda:None)
    for actions in (['transcription','paper_edit'],['footage_review']):
        respond('continue',executor,{'model':'synthetic','allowed_actions':actions},client)
    assert [t['parameters']['properties']['action']['enum'] for t in tools]==[['transcription','paper_edit'],['footage_review']]
    assert all(t['strict'] is True for t in tools)


@pytest.mark.parametrize('actions',[None,[], 'draft', [1]])
def test_missing_or_invalid_scope_never_reaches_model(actions):
    with pytest.raises(Uncertain):
        scoped_tool({'allowed_actions':actions})
