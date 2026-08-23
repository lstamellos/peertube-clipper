# Permissions

## Principle

Access is determined by whether the current PeerTube user can manage the **source video/channel**, not by whether that user uploaded the video.

This is necessary for collaborative channels: owner, administrators and channel collaborators/editors must see the same candidate queue when PeerTube grants them management rights.

## Native PeerTube semantics

PeerTube's own video-management authorization resolves through channel management rights and channel collaborator membership. The project should reuse that semantic boundary rather than maintaining an independent editor list.

## Plugin API limitation

At the time this scaffold was created, the public plugin helper API exposes the authenticated user and video loaders, but no documented `canManageVideo()` helper equivalent to PeerTube's internal validator.

The implementation therefore keeps authorization behind a `PermissionProvider` boundary. The production adapter must be validated against the target PeerTube version before write operations are enabled.

Acceptable approaches, in preference order:

1. a future public PeerTube permission helper;
2. a small upstreamable PeerTube plugin-API extension exposing native `canManageVideo` semantics;
3. a compatibility adapter that delegates to an existing native PeerTube endpoint whose authorization uses the same management validator;
4. a version-scoped database compatibility adapter, only with explicit tests.

Do not authorize based only on `video.account`/uploader identity.

## Shared review state

All authorized editors see the same candidate state. Per-user data is audit metadata only:

```text
approved_by
rejected_by
edited_by
acted_at
```
