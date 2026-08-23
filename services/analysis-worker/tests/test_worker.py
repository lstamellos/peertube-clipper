import hashlib
import json

import pytest

from clipper_worker.worker import analyze_run


CAPTION = b"""WEBVTT

00:00.000 --> 00:05.000
Intro

00:05.000 --> 00:10.000
Important statement

00:10.000 --> 00:15.000
Supporting detail
"""


class FakeBridge:
    def __init__(self, caption: bytes = CAPTION) -> None:
        self.caption = caption
        self.candidates = []
        self.finished = None
        self.active_checks = 0

    def get_caption(self, run):
        return self.caption

    def assert_analyzing(self, run):
        self.active_checks += 1

    def create_candidate(self, run, candidate):
        self.candidates.append(candidate)

    def finish(self, run, status, error=None):
        self.finished = (status, error)


class FakeLocator:
    def __init__(self) -> None:
        self.calls = []

    def locate(self, model: str, prompt: str) -> str:
        self.calls.append((model, prompt))
        return json.dumps(
            {
                "anchors": [
                    {
                        "start": 5.5,
                        "end": 9.5,
                        "category": "quote",
                        "reason": "editorial anchor",
                    }
                ]
            }
        )


def run_state(caption: bytes = CAPTION):
    return {
        "analysis_run_id": "run-1",
        "video_uuid": "00000000-0000-4000-8000-000000000001",
        "caption_checksum": hashlib.sha256(caption).hexdigest(),
        "model": "qwen3:1.7b",
        "status": "analyzing",
    }


def test_worker_uses_snapshot_and_writes_canonical_candidate() -> None:
    bridge = FakeBridge()
    locator = FakeLocator()

    count = analyze_run(bridge, locator, run_state())

    assert count == 1
    assert bridge.finished == ("complete", None)
    assert bridge.active_checks >= 3
    assert len(bridge.candidates) == 1
    written = bridge.candidates[0]
    assert written.canonical_transcript == "Intro Important statement Supporting detail"
    assert written.category == "quote"
    assert written.reason == "editorial anchor"
    assert locator.calls[0][0] == "qwen3:1.7b"


def test_worker_rejects_snapshot_checksum_mismatch_before_model_call() -> None:
    bridge = FakeBridge(caption=CAPTION.replace(b"Important", b"Changed"))
    locator = FakeLocator()

    with pytest.raises(RuntimeError, match="checksum mismatch"):
        analyze_run(bridge, locator, run_state())

    assert locator.calls == []
    assert bridge.candidates == []
    assert bridge.finished is None
