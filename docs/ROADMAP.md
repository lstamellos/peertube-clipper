# Roadmap

## Phase 2A — shared review foundation

- [x] Define generic architecture and security boundaries.
- [x] Define shared per-video state model.
- [x] Provide buildable PeerTube plugin/Bridge skeleton.
- [x] Provide general installer and uninstall paths.
- [ ] Validate production permission adapter on PeerTube 8.2.x.
- [ ] Implement per-video review page.
- [ ] Implement approve/reject/boundary editing.
- [ ] Add multi-editor audit trail tests.

## Phase 2B — automatic discovery

- [ ] Readiness gate for transcodes + canonical captions.
- [ ] Caption normalization/chunking.
- [ ] Pluggable local/remote analysis adapter.
- [ ] Editorial-anchor discovery.
- [ ] Deterministic review-window expansion.

## Phase 2C — rendering

- [ ] Renderer adapter interface.
- [ ] SupoClip reference adapter.
- [ ] Render queue and retry semantics.
- [ ] Download and optional PeerTube publish-back.

## Packaging and operations

- [x] Container Bridge deployment.
- [x] Native systemd Bridge deployment.
- [x] External Bridge configuration mode.
- [x] Native PeerTube plugin installation.
- [x] Docker PeerTube plugin installation.
- [ ] Published NPM plugin release.
- [ ] Versioned upgrade/migration command.
- [ ] Installer integration tests across representative PeerTube layouts.

## PeerTube UX upstream work

- [ ] Propose a generic plugin extension point for Video Manage menu/child pages.
- [ ] Move the same review UI from the temporary supported plugin surface into `Manage → Clips` when available.
