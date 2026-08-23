from __future__ import annotations

import argparse
import fcntl
import hashlib
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from .core import (
    ProposedCandidate,
    build_prompt,
    build_windows,
    candidate_from_anchor,
    cues_in_range,
    dedupe_candidates,
    parse_anchor_response,
    parse_vtt,
)


LOG = logging.getLogger("peertube-clipper-analysis-worker")


class RunInactive(RuntimeError):
    pass


class BridgeClient:
    def __init__(self, base_url: str, token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(
            headers={"X-Peertube-Clipper-Token": token},
            timeout=30.0,
        )

    def close(self) -> None:
        self.client.close()

    def claim_next(self) -> dict[str, Any] | None:
        response = self.client.post(f"{self.base_url}/v1/analysis-runs/claim-next")
        if response.status_code == 204:
            return None
        response.raise_for_status()
        return response.json()

    def get_caption(self, run: dict[str, Any]) -> bytes:
        response = self.client.get(
            f"{self.base_url}/v1/videos/{run['video_uuid']}/analysis-runs/{run['analysis_run_id']}/caption"
        )
        response.raise_for_status()
        return response.content

    def get_run_state(self, run: dict[str, Any]) -> dict[str, Any] | None:
        response = self.client.get(f"{self.base_url}/v1/videos/{run['video_uuid']}")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        payload = response.json()
        for candidate in payload.get("analysis_runs") or []:
            if candidate.get("analysis_run_id") == run.get("analysis_run_id"):
                return candidate
        return None

    def assert_analyzing(self, run: dict[str, Any]) -> None:
        current = self.get_run_state(run)
        if not current or current.get("status") != "analyzing":
            raise RunInactive("analysis run is no longer active")

    def create_candidate(self, run: dict[str, Any], candidate: ProposedCandidate) -> None:
        response = self.client.post(
            f"{self.base_url}/v1/videos/{run['video_uuid']}/analysis-runs/{run['analysis_run_id']}/candidates",
            json={
                "anchor_start": candidate.anchor_start,
                "anchor_end": candidate.anchor_end,
                "suggested_start": candidate.suggested_start,
                "suggested_end": candidate.suggested_end,
                "canonical_transcript": candidate.canonical_transcript,
            },
        )
        if response.status_code == 409:
            raise RunInactive("analysis run rejected candidate write")
        response.raise_for_status()

    def finish(self, run: dict[str, Any], status: str, error: str | None = None) -> None:
        response = self.client.patch(
            f"{self.base_url}/v1/videos/{run['video_uuid']}/analysis-runs/{run['analysis_run_id']}",
            json={"status": status, "error": error},
        )
        if response.status_code == 409:
            raise RunInactive("analysis run rejected final state transition")
        response.raise_for_status()


class OllamaLocator:
    def __init__(
        self,
        base_url: str,
        timeout_seconds: float = 900.0,
        num_ctx: int = 16384,
        num_threads: int = 8,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.num_ctx = num_ctx
        self.num_threads = num_threads
        self.client = httpx.Client(timeout=timeout_seconds)

    def close(self) -> None:
        self.client.close()

    def locate(self, model: str, prompt: str) -> str:
        response = self.client.post(
            f"{self.base_url}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "think": False,
                "options": {
                    "num_ctx": self.num_ctx,
                    "num_thread": self.num_threads,
                    "temperature": 0.2,
                },
            },
        )
        response.raise_for_status()
        payload = response.json()
        result = payload.get("response")
        if not isinstance(result, str) or not result.strip():
            raise RuntimeError("Ollama returned an empty response")
        return result


def analyze_run(
    bridge: BridgeClient,
    locator: OllamaLocator,
    run: dict[str, Any],
    chunk_seconds: float = 300.0,
    overlap_seconds: float = 40.0,
) -> int:
    caption = bridge.get_caption(run)
    checksum = hashlib.sha256(caption).hexdigest()
    if checksum != run.get("caption_checksum"):
        raise RuntimeError("caption snapshot checksum mismatch before analysis")

    cues = parse_vtt(caption)
    if not cues:
        raise RuntimeError("canonical caption snapshot contains no usable cues")

    duration = max(cue.end for cue in cues)
    windows = build_windows(duration, size=chunk_seconds, overlap=overlap_seconds)
    proposed: list[ProposedCandidate] = []

    for window_start, window_end in windows:
        bridge.assert_analyzing(run)
        chunk_cues = cues_in_range(cues, window_start, window_end)
        if not chunk_cues:
            continue

        prompt = build_prompt(chunk_cues, window_start, window_end)
        raw = locator.locate(str(run["model"]), prompt)
        bridge.assert_analyzing(run)

        anchors = parse_anchor_response(raw, window_start, window_end, max_anchors=8)
        for anchor in anchors:
            candidate = candidate_from_anchor(cues, anchor)
            if candidate is not None:
                proposed.append(candidate)

    candidates = dedupe_candidates(proposed)
    bridge.assert_analyzing(run)

    for candidate in candidates:
        bridge.create_candidate(run, candidate)

    bridge.assert_analyzing(run)
    bridge.finish(run, "complete")
    return len(candidates)


def process_once(bridge: BridgeClient, locator: OllamaLocator) -> bool:
    run = bridge.claim_next()
    if run is None:
        return False

    run_id = run.get("analysis_run_id")
    video_uuid = run.get("video_uuid")
    LOG.info("claimed analysis run %s for video %s", run_id, video_uuid)

    try:
        count = analyze_run(bridge, locator, run)
        LOG.info("completed analysis run %s with %d candidates", run_id, count)
    except RunInactive as exc:
        LOG.info("stopped inactive analysis run %s: %s", run_id, exc)
    except Exception as exc:
        LOG.exception("analysis run %s failed", run_id)
        message = " ".join(str(exc).split())[:4000] or exc.__class__.__name__
        try:
            bridge.finish(run, "failed", message)
        except RunInactive:
            LOG.info("analysis run %s became inactive before failure could be recorded", run_id)
        except Exception:
            LOG.exception("could not persist failure state for analysis run %s", run_id)

    return True


def acquire_singleton_lock(path: str):
    lock_path = Path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        handle.close()
        raise RuntimeError("another analysis worker instance is already running") from exc
    return handle


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PeerTube Clipper local analysis worker")
    parser.add_argument("--once", action="store_true", help="Process at most one queued analysis run")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    logging.basicConfig(
        level=os.environ.get("PEERTUBE_CLIPPER_WORKER_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    bridge_url = os.environ.get("PEERTUBE_CLIPPER_BRIDGE_URL", "http://127.0.0.1:18100")
    bridge_token = os.environ.get("PEERTUBE_CLIPPER_SERVICE_TOKEN", "")
    ollama_url = os.environ.get("PEERTUBE_CLIPPER_OLLAMA_URL", "http://127.0.0.1:11434")
    poll_seconds = max(1.0, float(os.environ.get("PEERTUBE_CLIPPER_WORKER_POLL_SECONDS", "10")))
    lock_path = os.environ.get(
        "PEERTUBE_CLIPPER_WORKER_LOCK",
        "/tmp/peertube-clipper-analysis-worker.lock",
    )

    if not bridge_token:
        LOG.error("PEERTUBE_CLIPPER_SERVICE_TOKEN is required")
        return 2

    try:
        lock_handle = acquire_singleton_lock(lock_path)
    except RuntimeError as exc:
        LOG.error("%s", exc)
        return 3

    bridge = BridgeClient(bridge_url, bridge_token)
    locator = OllamaLocator(ollama_url)
    try:
        if args.once:
            process_once(bridge, locator)
            return 0

        while True:
            processed = process_once(bridge, locator)
            if not processed:
                time.sleep(poll_seconds)
    except KeyboardInterrupt:
        return 0
    finally:
        locator.close()
        bridge.close()
        lock_handle.close()


if __name__ == "__main__":
    sys.exit(main())
