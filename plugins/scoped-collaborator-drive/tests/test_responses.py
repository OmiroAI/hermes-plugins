from types import SimpleNamespace
import pytest
from collaborator_drive.responses import respond_responses
from collaborator_drive.registry import Denied


class Item:
    def __init__(self, value): self.value = value
    def model_dump(self, **kwargs): return self.value


class Stream:
    def __init__(self, output): self.output, self.closed = output, False
    def __iter__(self):
        yield SimpleNamespace(type="response.completed", response=SimpleNamespace(output=[Item(x) for x in self.output]))
    def close(self): self.closed = True


def test_responses_tool_loop_and_recheck():
    streams = [Stream([{"type":"function_call","name":"scoped_drive","arguments":"{}","call_id":"synthetic"}]),
               Stream([{"type":"message","content":[{"type":"output_text","text":"done"}]}])]
    seen = []
    def create(**kwargs):
        assert kwargs["store"] is False and kwargs["stream"] is True
        assert kwargs["tools"][0]["name"] == "scoped_drive"
        assert kwargs["tools"][0]["strict"] is True
        assert kwargs["tools"][0]["parameters"]["properties"]["action"]["enum"] == ["draft"]
        seen.append(kwargs)
        return streams[len(seen)-1]
    checked = []
    executor = SimpleNamespace(execute=lambda args: {"status":"verified"}, recheck=lambda: checked.append(True))
    client = SimpleNamespace(responses=SimpleNamespace(create=create))
    assert respond_responses("test", executor, {"model":"synthetic","allowed_actions":["draft"]}, client) == "done"
    assert checked and all(s.closed for s in streams)


def test_unknown_response_tool_denies():
    stream = Stream([{"type":"function_call","name":"shell","arguments":"{}","call_id":"synthetic"}])
    client = SimpleNamespace(responses=SimpleNamespace(create=lambda **kwargs: stream))
    with pytest.raises(Denied):
        respond_responses("test", None, {"model":"synthetic","allowed_actions":["draft"]}, client)
    assert stream.closed
