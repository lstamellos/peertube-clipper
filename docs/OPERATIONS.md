# Operations

## Queue isolation

Analysis and rendering should use separate queues.

```text
analysis_queue → pending_review → render_queue
```

Initial production recommendation is rendering concurrency `1` on CPU-only hosts. Analysis should be scheduled at lower priority than active PeerTube live/transcoding work.

## Failure isolation

A failed analysis must not affect PeerTube playback or publishing.

A failed render must leave the approved candidate and editor boundaries intact so the render can be retried.

## Idempotency

Readiness evaluation and enqueue operations must be idempotent. Repeated PeerTube hooks must not create duplicate analysis jobs.
