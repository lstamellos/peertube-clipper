import hashlib
import json

import pytest

import clipper_worker.worker as worker_module
from clipper_worker.worker import OllamaLocator, analyze_run


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
                        "start_cue": "C002",
                        "end_cue": "C002",
                        "category": "quote",
                        "reason": "editorial anchor",
                    }
                ]
            }
        )


class FakeHTTPResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self):
        return {"response": '{"anchors":[]}'}


class FakeHTTPClient:
    instances = []

    def __init__(self, *args, **kwargs) -> None:
        self.posts = []
        self.args = args
        self.kwargs = kwargs
        self.__class__.instances.append(self)

    def post(self, url, json):
        self.posts.append((url, json))
        return FakeHTTPResponse()

    def close(self) -> None:
        return None


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
    assert written.anchor_start == 5.0
    assert written.anchor_end == 10.0
    assert written.canonical_transcript == "Intro Important statement Supporting detail"
    assert written.category == "quote"
    assert written.reason == "editorial anchor"
    assert locator.calls[0][0] == "qwen3:1.7b"
    assert "[C002 | 00:00:05.000 --> 00:00:10.000] Important statement" in locator.calls[0][1]


def test_worker_rejects_snapshot_checksum_mismatch_before_model_call() -> None:
    bridge = FakeBridge(caption=CAPTION.replace(b"Important", b"Changed"))
    locator = FakeLocator()

    with pytest.raises(RuntimeError, match="checksum mismatch"):
        analyze_run(bridge, locator, run_state())

    assert locator.calls == []
    assert bridge.candidates == []
    assert bridge.finished is None


def test_ollama_locator_enforces_cue_id_schema_and_disables_thinking(monkeypatch) -> None:
    FakeHTTPClient.instances = []
    monkeypatch.setattr(worker_module.httpx, "Client", FakeHTTPClient)

    locator = OllamaLocator("http://127.0.0.1:11434")
    result = locator.locate("qwen3:1.7b", "prompt")

    assert result == '{"anchors":[]}'
    assert len(FakeHTTPClient.instances) == 1

    client = FakeHTTPClient.instances[0]
    assert len(client.posts) == 1

    url, body = client.posts[0]
    assert url == "http://127.0.0.1:11434/api/generate"
    assert body["model"] == "qwen3:1.7b"
    assert body["stream"] is False
    assert body["think"] is False
    assert body["format"]["type"] == "object"
    assert body["format"]["required"] == ["anchors"]
    assert body["format"]["properties"]["anchors"]["type"] == "array"
    assert body["format"]["properties"]["anchors"]["maxItems"] == 8

    item_schema = body["format"]["properties"]["anchors"]["items"]
    assert item_schema["required"] == [
        "start_cue",
        "end_cue",
        "category",
        "reason",
    ]
    assert item_schema["properties"]["start_cue"]["type"] == "string"
    assert item_schema["properties"]["start_cue"]["pattern"] == "^C[0-9]{3,}$"
    assert item_schema["properties"]["end_cue"]["type"] == "string"
    assert item_schema["properties"]["end_cue"]["pattern"] == "^C[0-9]{3,}$"
    assert "start" not in item_schema["properties"]
    assert "end" not in item_schema["properties"]