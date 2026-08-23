import hashlib
import importlib
from uuid import UUID

from fastapi.testclient import TestClient


VIDEO = UUID("22222222-2222-4222-8222-222222222222")
TOKEN = "test-service-token"
CAPTION = b"WEBVTT\n\n00:10.000 --> 00:15.000\nCanonical API caption\n"
LEASE_HEADER = "X-Peertube-Clipper-Worker-Lease"


def test_snapshot_claim_candidate_and_complete_api(tmp_path, monkeypatch):
    monkeypatch.setenv("PEERTUBE_CLIPPER_SERVICE_TOKEN", TOKEN)
    monkeypatch.setenv("PEERTUBE_CLIPPER_DATABASE", str(tmp_path / "api.sqlite3"))

    import clip_bridge.main as bridge_main

    bridge_main = importlib.reload(bridge_main)
    client = TestClient(bridge_main.app)
    headers = {"X-Peertube-Clipper-Token": TOKEN}

    claim = client.post(
        f"/v1/videos/{VIDEO}/analysis-runs/claim",
        headers=headers,
        json={
            "caption_language": "el",
            "caption_checksum": hashlib.sha256(CAPTION).hexdigest(),
            "analyzer_version": "locator-v1",
            "model": "qwen3:1.7b",
            "prompt_version": "anchors-v1",
        },
    )
    assert claim.status_code == 200
    run = claim.json()["analysis_run"]
    assert run["caption_snapshot_ready"] is False

    snapshot = client.put(
        f"/v1/videos/{VIDEO}/analysis-runs/{run['analysis_run_id']}/caption",
        headers={**headers, "Content-Type": "text/vtt"},
        content=CAPTION,
    )
    assert snapshot.status_code == 200
    assert snapshot.json()["caption_snapshot_ready"] is True

    worker_claim = client.post("/v1/analysis-runs/claim-next", headers=headers)
    assert worker_claim.status_code == 200
    worker_payload = worker_claim.json()
    assert worker_payload["analysis_run"]["analysis_run_id"] == run["analysis_run_id"]
    assert worker_payload["analysis_run"]["status"] == "analyzing"
    lease = worker_payload["worker_lease"]
    assert isinstance(lease, str) and lease
    worker_headers = {**headers, LEASE_HEADER: lease}

    heartbeat = client.post(
        f"/v1/videos/{VIDEO}/analysis-runs/{run['analysis_run_id']}/heartbeat",
        headers=worker_headers,
    )
    assert heartbeat.status_code == 200
    assert heartbeat.json()["status"] == "analyzing"

    fetched = client.get(
        f"/v1/videos/{VIDEO}/analysis-runs/{run['analysis_run_id']}/caption",
        headers=headers,
    )
    assert fetched.status_code == 200
    assert fetched.content == CAPTION

    without_lease = client.post(
        f"/v1/videos/{VIDEO}/analysis-runs/{run['analysis_run_id']}/candidates",
        headers=headers,
        json={
            "anchor_start": 10,
            "anchor_end": 14,
            "suggested_start": 10,
            "suggested_end": 15,
            "canonical_transcript": "Canonical API caption",
        },
    )
    assert without_lease.status_code == 409

    created = client.post(
        f"/v1/videos/{VIDEO}/analysis-runs/{run['analysis_run_id']}/candidates",
        headers=worker_headers,
        json={
            "anchor_start": 10,
            "anchor_end": 14,
            "suggested_start": 10,
            "suggested_end": 15,
            "canonical_transcript": "Canonical API caption",
        },
    )
    assert created.status_code == 200

    state_while_analyzing = client.get(f"/v1/videos/{VIDEO}", headers=headers)
    assert state_while_analyzing.status_code == 200
    assert state_while_analyzing.json()["candidates"] == []

    completed = client.patch(
        f"/v1/videos/{VIDEO}/analysis-runs/{run['analysis_run_id']}/worker-state",
        headers=worker_headers,
        json={"status": "complete", "error": None},
    )
    assert completed.status_code == 200

    state_after = client.get(f"/v1/videos/{VIDEO}", headers=headers)
    assert state_after.status_code == 200
    assert state_after.json()["video"]["status"] == "pending_review"
    assert len(state_after.json()["candidates"]) == 1
