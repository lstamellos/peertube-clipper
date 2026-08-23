# Permissions

## Principle

Access is determined by whether the current PeerTube user can manage the **source video/channel**, not by whether that user uploaded the video.

This is necessary for collaborative channels: owner, users with instance-wide video update rights, and accepted channel collaborators/editors must see the same candidate queue when PeerTube grants them management rights.

## PeerTube 8.2 compatibility adapter

PeerTube Clipper now implements a version-scoped adapter matching PeerTube 8.2 video-management semantics:

1. the video must be local;
2. a user with `UPDATE_ANY_VIDEO` is allowed;
3. the owner of the video's channel account is allowed;
4. an `ACCEPTED` `videoChannelCollaborator` for that channel is allowed;
5. all other users are denied.

The adapter uses the authenticated `UserModel` returned by `peertubeHelpers.user.getAuthUser()`, including its native `hasRight()` method, and a read-only database query for channel ownership/collaboration.

Compatibility constants are intentionally explicit and covered by tests for PeerTube 8.2:

```text
UserRight.UPDATE_ANY_VIDEO = 17
VideoChannelCollaboratorState.ACCEPTED = 2
```

If PeerTube changes these public enum values or exposes a supported `canManageVideo()` plugin helper, the adapter should be updated to prefer the native public helper.

## Authorization boundary

The browser is never trusted to supply an editor identity or an authorization decision.

```text
browser
  ↓ PeerTube OAuth session
plugin server
  ↓ getAuthUser()
  ↓ per-video manage permission adapter
  ↓ inject authenticated user.id as audit actor
Clip Bridge
```

The Clip Bridge does not independently reimplement PeerTube account/channel authorization. It accepts requests only from the plugin service credential and stores the authenticated PeerTube user ID supplied by the plugin server.

## Shared review state

All authorized editors see the same source-video candidate state. Per-user data is audit metadata only:

```text
acted_by_user_id
acted_at
```

Candidate approval/rejection/boundary changes never create a private per-editor copy of the queue.

## Future upstream path

Preferred long-term options remain:

1. use a public PeerTube `canManageVideo()` helper if one is added;
2. upstream a small generic plugin-API extension exposing native video-management authorization;
3. remove the compatibility SQL adapter when such an API is available.
