# Readiness and analysis claims

PeerTube Clipper does not start clip discovery merely because a video upload or caption event occurred. The PeerTube plugin evaluates the current authoritative PeerTube state and only claims an analysis run when all readiness conditions are satisfied.

## Readiness gate

A local video is ready when:

- it is not a live video;
- PeerTube reports no pending transcoding work in `videoJobInfo.pendingTranscode`;
- PeerTube reports no pending transcription work in `videoJobInfo.pendingTranscription`;
- a canonical PeerTube caption can be selected deterministically;
- the canonical caption can be fetched as valid WebVTT.

The plugin computes SHA-256 over the actual canonical VTT bytes. The Bridge uses the tuple `(video UUID, caption checksum, analyzer version)` as the analysis-run idempotency key.

If the canonical caption changes, a new checksum can claim a new run and previous runs for another caption revision are marked stale.

## Canonical caption selection

The source of truth is the caption stored by PeerTube.

Selection is intentionally conservative:

1. if the video has a language and a caption exists for that language, use it;
2. otherwise, if exactly one caption exists, use it;
3. otherwise stop with `canonical_caption_ambiguous` rather than guessing between languages.

Missing, empty, unavailable, oversized or invalid VTT captions keep the workflow in `waiting_for_transcript`.

## Event hints and reconciliation

PeerTube's `action:api.video-caption.created` hook is useful for captions created through the captions API, but PeerTube's internal automatic transcription path does not emit that hook when transcription finishes. PeerTube Clipper therefore treats hooks only as hints.

When automatic tracking is enabled, upload/update/file/caption/live-state hints re-evaluate readiness immediately. A reconciliation loop also re-evaluates Bridge workflows in `waiting_for_video` or `waiting_for_transcript`, so automatic transcription completion and transcoding completion cannot be missed merely because no suitable plugin action hook fired.

Only already tracked waiting workflows are reconciled. Enabling automatic tracking does not bulk-enqueue the historical PeerTube archive.

## Safe rollout

`auto-analysis-enabled` is disabled by default.

A video manager can explicitly press **Check readiness** on the Clip review page. This calls the authenticated plugin route and either:

- records the current waiting reason in the Bridge; or
- claims one queued analysis run when the gate is ready.

At this stage a `queued` analysis run is only a durable orchestration record. It does not itself run an LLM and it does not render clips. The analyzer worker and renderer are separate phases.

## Workflow states

Readiness uses these existing video workflow states:

- `waiting_for_video`: live video or pending transcoding;
- `waiting_for_transcript`: pending/missing/ambiguous/unavailable canonical caption;
- `ready_for_analysis`: an idempotent analysis run has been claimed;
- `analyzing`: analyzer worker has started the claimed run;
- `pending_review`: candidates are available for editorial review.

The Bridge stores analysis runs separately from candidate review state so analysis and rendering can remain separate queues.
