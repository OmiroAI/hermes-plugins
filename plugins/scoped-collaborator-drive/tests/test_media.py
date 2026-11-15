import json
import sys
import pytest
from collaborator_drive.media import transcribe
from collaborator_drive.registry import Uncertain


def test_missing_transcriber_pauses_before_download():
    with pytest.raises(Uncertain):
        transcribe(None, "synthetic-media", None)


@pytest.mark.parametrize("limit", [200_000_000, 2_000_000_000])
def test_bounded_media_command_and_secret_free_environment(tmp_path, monkeypatch, limit):
    class Adapter:
        def download_media(self, target, path, configured_limit):
            assert configured_limit == limit
            path.write_bytes(b"synthetic media")
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        assert kwargs["env"].keys() == {"PATH", "HOME", "LANG", "OMP_NUM_THREADS"}
        assert kwargs["timeout"] in {60, 600}

    monkeypatch.setattr("collaborator_drive.media.subprocess.run", run)
    def capture(command, env):
        assert env.keys() == {"PATH", "HOME", "LANG", "OMP_NUM_THREADS"}
        calls.append(command)
        return json.dumps({"text": "synthetic transcript"})
    monkeypatch.setattr("collaborator_drive.media.capture_transcript", capture)
    result = transcribe(Adapter(), "synthetic-media", ["/operator/transcriber"], max_media_bytes=limit)
    assert result["text"] == "synthetic transcript"
    assert "file,pipe" in calls[0] and "900" in calls[0]
    assert calls[1][0] == "/operator/transcriber"



def test_real_transcriber_subprocess_is_bounded():
    from collaborator_drive.media import capture_transcript
    assert json.loads(capture_transcript([sys.executable, "-c", 'print(\'{"text":"synthetic"}\')'], {}))["text"] == "synthetic"
    with pytest.raises(Uncertain):
        capture_transcript([sys.executable, "-c", 'print("x" * 120001)'], {})


@pytest.mark.parametrize("limit", [0, -1, True, "200000000"])
def test_invalid_media_budget_stops_before_download(limit):
    with pytest.raises(Uncertain):
        transcribe(None, "synthetic-media", ["/operator/transcriber"], max_media_bytes=limit)
