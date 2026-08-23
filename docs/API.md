# Clip Bridge API

The Bridge API is private. Browser JavaScript must not call it directly.

Every request except `/healthz` requires the service token supplied by the PeerTube plugin server.

## Health

`GET /healthz`

## Video state

`GET /v1/videos/{video_uuid}`

Returns shared workflow state for a source video.

## Ensure source state

`PUT /v1/videos/{video_uuid}`

Idempotently creates/updates the source-video workflow record.

## Candidates

`GET /v1/videos/{video_uuid}/candidates`

`POST /v1/videos/{video_uuid}/candidates`

The latter is an internal/testing endpoint in Phase 2A and will later be used by the analysis worker.

## Review action

`PATCH /v1/videos/{video_uuid}/candidates/{candidate_id}`

Allowed review states:

- `suggested`
- `edited`
- `approved`
- `rejected`

The authorized PeerTube user ID is supplied by the plugin server as audit metadata. The Bridge does not independently decide whether that user may manage the video.
