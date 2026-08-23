# Architecture

## Components

### PeerTube plugin

Responsibilities:

- expose the workflow inside PeerTube;
- identify the current source video;
- authenticate the current PeerTube user;
- enforce per-video management permission;
- proxy authorized review actions to the Clip Bridge;
- show readiness, analysis, review and render state.

Non-responsibilities:

- LLM inference;
- FFmpeg orchestration;
- renderer lifecycle;
- system package installation;
- long-running background workers.

### Clip Bridge

Responsibilities:

- persist shared per-video workflow state;
- implement an idempotent readiness gate;
- retrieve/normalize canonical captions;
- chunk transcripts for analysis;
- invoke a configured analysis adapter;
- persist candidate anchors and suggested review windows;
- accept approve/reject/boundary-edit actions;
- enqueue approved candidates for rendering;
- record audit attribution supplied by the authorized plugin façade.

### Analysis adapter

The analysis adapter is replaceable. A local model is the default design target, but hosted providers may be supported without changing the review model.

The model should primarily locate editorial anchors. Canonical text and review windows are reconstructed deterministically from PeerTube captions.

### Renderer adapter

The renderer is replaceable. SupoClip is the initial reference backend, but the Bridge API must not depend on SupoClip-specific UI or storage models.

## Workflow

```text
live/upload
    ↓
PeerTube transcoding + transcription
    ↓
readiness gate
    ↓
analysis
    ↓
SUGGESTED candidates
    ↓
human review in PeerTube
    ├─ REJECTED
    ├─ EDITED
    └─ APPROVED
          ↓
      render queue
          ↓
       RENDERED
          ↓
 optional publish-back
```

## Readiness gate

Analysis may start only when all required conditions are true:

```text
video is not actively live
AND required transcodes are complete
AND canonical caption exists
AND analysis has not already been started for the same source revision
```

Every trigger re-evaluates this gate. Triggers are hints; the gate is authoritative and idempotent.

## Candidate model

Candidates belong to a source video, not a user.

Minimum fields:

```text
source_video_uuid
candidate_id
anchor_start
anchor_end
suggested_start
suggested_end
canonical_transcript
status
created_at
```

Human review fields are stored separately so the original AI suggestion remains available for evaluation/debugging:

```text
editor_start
editor_end
status = approved | rejected
acted_by_user_id
acted_at
```
