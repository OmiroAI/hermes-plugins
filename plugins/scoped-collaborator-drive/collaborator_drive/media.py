"""Optional local transcription adapter. Decoder/transcriber receive no API secrets."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import selectors
import time
from .registry import Uncertain


def transcribe(adapter, target, command, decoder="/usr/bin/ffmpeg"):
    if not isinstance(command, list) or not command or any(not isinstance(v, str) or not v for v in command):
        raise Uncertain("No operator-configured local transcriber.")
    with tempfile.TemporaryDirectory(prefix="collaborator-media-") as directory:
        media, audio = (Path(directory) / name for name in ("media", "audio.wav"))
        adapter.download_media(target, media, 200_000_000)
        env = {"PATH": os.defpath, "HOME": directory, "LANG": "C.UTF-8", "OMP_NUM_THREADS": "2"}
        if not isinstance(decoder, str) or not os.path.isabs(decoder):
            raise Uncertain("Decoder must be an operator-configured absolute path.")
        subprocess.run([decoder, "-nostdin", "-v", "error", "-protocol_whitelist", "file,pipe",
            "-format_whitelist", "mov,matroska,webm,wav,mp3,mpegts,flac,ogg,avi,aac",
            "-i", str(media), "-t", "900", "-vn", "-ac", "1", "-ar", "16000", str(audio)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60, env=env)
        result = json.loads(capture_transcript([*command, str(audio)], env))
        if not isinstance(result, dict) or set(result) != {"text"} or not isinstance(result["text"], str):
            raise Uncertain("Invalid transcriber output.")
        return {"text": result["text"], "limit": "First 15 minutes; human verification required."}


def capture_transcript(command, env):
    """Read at most 120 KB while enforcing the process deadline, not after buffering."""
    output = bytearray()
    deadline = time.monotonic() + 600
    proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, env=env)
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise Uncertain("Transcriber timed out.")
                chunk = os.read(proc.stdout.fileno(), min(8192, 120001 - len(output)))
                if not chunk:
                    break
                output.extend(chunk)
                if len(output) > 120000:
                    raise Uncertain("Transcript exceeds output limit.")
        if proc.wait(timeout=max(0.001, deadline - time.monotonic())):
            raise Uncertain("Transcriber failed.")
        return output
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=5)
        proc.stdout.close()
