# Analysis worker

Phase 2C adds a local, single-concurrency analysis worker. It discovers editorial clip anchors from the canonical PeerTube caption revision but does not render clips.

## Safety boundary

The worker never reads an arbitrary current transcript. A successful readiness evaluation stores the exact canonical VTT bytes in the Clip Bridge and verifies them against the SHA-256 checksum attached to the analysis run.

A queued analysis run is eligible for a worker claim only when that immutable VTT snapshot is present. The worker hashes the snapshot again before analysis.

If a newer canonical caption revision or analyzer generation is claimed while an older run is analyzing, the older run becomes `stale` and its worker lease is revoked. Bridge writes are state- and lease-checked atomically: a stale or expired worker cannot add more candidates or transition to `complete`. Candidates attached to non-complete or stale runs remain in persistence for audit/history but are not exposed in the shared review queue.

## Worker lifecycle

```text
queued + caption snapshot
        |
        | atomic claim + 20 minute renewable lease
        v
    analyzing
        |
        | canonical VTT -> 5 minute chunks
        | qwen3:1.7b editorial anchors
        | deterministic cue-context expansion
        | conservative overlap-boundary dedupe
        | heartbeat / lease check around model work and writes
        v
      complete
        |
        +--> pending_review  (one or more candidates)
        +--> reviewed        (zero candidates)
```

Errors move an active run to `failed` / workflow `partial_failure`. If the run became stale first, the worker stops without changing the stale state.

If a worker process dies, its lease eventually expires. The next atomic worker claim requeues that run, removes only partial candidates from the abandoned attempt, and issues a new lease. The 20 minute lease is intentionally longer than the initial 900 second maximum model request; successful workers renew it before and after model chunks and before candidate writes.

## Initial analysis defaults

- model: `qwen3:1.7b`
- Ollama endpoint: `http://127.0.0.1:11434`
- chunk size: 300 seconds
- chunk overlap: 40 seconds
- model context: 16384
- CPU threads: 8
- model request timeout: 900 seconds
- worker lease: 1200 seconds, renewable
- maximum anchors returned per chunk: 8
- deterministic context expansion: 12 seconds before/after the anchor, snapped to canonical cue boundaries
- Ollama output contract: JSON Schema constrained `anchors[]`
- Qwen3 thinking: disabled for locator extraction (`think: false`)

The model is asked for editorial anchors only. Candidate transcript text is rebuilt from the canonical caption cues and is never accepted from model-generated prose.

The locator passes the expected anchor JSON Schema directly to Ollama's `format` field rather than relying on `format: "json"` alone. The prompt also describes the expected top-level `anchors[]` shape. The worker still validates and normalizes the returned fields and rejects anchors outside the current source window.

## Container Ollama exposure

In container companion mode, the optional `analysis` profile runs Ollama in Docker while the initial analysis worker runs on the host. The compose stack therefore publishes Ollama to loopback only:

```text
PEERTUBE_CLIPPER_OLLAMA_BIND=127.0.0.1
PEERTUBE_CLIPPER_OLLAMA_PORT=11434
```

The resulting host endpoint is `http://127.0.0.1:11434`. Do not bind Ollama to a public interface unless a separate deployment explicitly requires and secures remote access.

## Duplicate and generation policy

Partial and nested overlaps are allowed. The worker removes only anchors whose start and end boundaries are both within 2.5 seconds of an already accepted anchor. This is intentionally conservative so distinct editorial uses are not collapsed merely because their proposed clips overlap.

A new caption checksum or analyzer version creates a new analysis generation and stales the previous non-stale generation. Older generation candidates remain stored for audit/history but are hidden from the active review queue.

## Concurrency

The initial worker is single-concurrency. The process takes a non-blocking host lock before polling the Bridge. The Bridge atomically transitions a claimed run from `queued` to `analyzing` and returns a per-claim lease token. Candidate writes, heartbeats and completion require that live lease.

Run exactly one worker service per analysis host in the initial deployment.

## Environment

Required:

```text
PEERTUBE_CLIPPER_SERVICE_TOKEN
```

Optional:

```text
PEERTUBE_CLIPPER_BRIDGE_URL=http://127.0.0.1:18100
PEERTUBE_CLIPPER_OLLAMA_URL=http://127.0.0.1:11434
PEERTUBE_CLIPPER_WORKER_POLL_SECONDS=10
PEERTUBE_CLIPPER_WORKER_LOCK=/tmp/peertube-clipper-analysis-worker.lock
PEERTUBE_CLIPPER_WORKER_LOG_LEVEL=INFO
```

The service token and worker lease are server-side credentials and must never be exposed to browser JavaScript or logs.

## Isolated validation

Before deployment, run:

```sh
bash scripts/check-phase2c-isolated.sh
```

The check creates a disposable Python virtual environment under `/tmp`, runs Bridge and worker tests, runs Python bytecode compilation, and executes the existing Node/shell checks. It does not contact the production Bridge, claim production analysis runs, start Ollama inference, alter PeerTube, or render media.

Only after the isolated suite passes should the Bridge/plugin schema upgrade and worker canary be deployed.
