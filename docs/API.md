# Clip Bridge and plugin API

The Clip Bridge API is private. Browser JavaScript must not call it directly.

Every Bridge request except `/healthz` requires the service token supplied by the PeerTube plugin server.

## Browser-facing plugin routes

These routes are exposed by the PeerTube plugin router and require a valid PeerTube login plus manage permission on the source video.

### Shared state

`GET .../router/videos/{video_uuid}/state`

The exact plugin route prefix is provided by PeerTube's `getBaseRouterRoute()` helper. The response contains:

- the authorization path (`channel_owner`, `channel_collaborator`, or `update_any_video`);
- source-video UUID/name;
- shared Clip Bridge workflow state;
- candidates for the source video.

If no Bridge record exists, the plugin idempotently creates one before reading state.

### Review candidate

`PATCH .../router/videos/{video_uuid}/candidates/{candidate_id}`

Browser payload:

```json
{
  "status": "approved",
  "editorStart": 12.5,
  "editorEnd": 43.2
}
```

Allowed browser review states are `edited`, `approved`, and `rejected`.

The browser cannot provide `acted_by_user_id`. The plugin server injects the authenticated PeerTube user ID after authorization.

## Private Clip Bridge API

### Health

`GET /healthz`

### Video state

`GET /v1/videos/{video_uuid}`

Returns shared workflow state for a source video.

### Ensure source state

`PUT /v1/videos/{video_uuid}`

Idempotently creates/updates the source-video workflow record without replacing an existing workflow status.

### Candidates

`GET /v1/videos/{video_uuid}/candidates`

`POST /v1/videos/{video_uuid}/candidates`

The POST endpoint is internal/testing-only in Phase 2A and will later be used by the analysis worker. Creating a candidate moves the source workflow to `pending_review`.

### Review action

`PATCH /v1/videos/{video_uuid}/candidates/{candidate_id}`

The Bridge accepts `edited`, `approved`, or `rejected` plus the authenticated PeerTube actor ID from the plugin server. `edited` remains pending review; once no candidates remain in `suggested`/`edited`, the source workflow becomes `reviewed`.
