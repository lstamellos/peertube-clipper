# Development

## Plugin

The plugin package lives in `packages/peertube-plugin-clipper` and follows PeerTube's required `peertube-plugin-` package naming convention.

The current client UI is deliberately small until the production per-video Manage integration point and permission adapter have passed end-to-end validation.

The plugin can read installer-provisioned Bridge configuration from its private PeerTube plugin data directory (`bridge.json`). Admin settings can override that file without exposing the service credential to browser JavaScript.

## Bridge

The Clip Bridge is a small FastAPI service. Phase 2A uses SQLite for a self-contained store. A PostgreSQL implementation can later be introduced behind the same storage boundary for larger deployments.

## Testing priorities

1. PeerTube owner can access a source-video workflow.
2. PeerTube channel collaborator/editor receives the same access when PeerTube grants video management rights.
3. Unauthorized users receive no candidate data.
4. Two editors see the same shared candidate state.
5. Review attribution records the acting PeerTube user.
6. Bridge credentials never appear in client responses or client JavaScript.
7. Installer dry-run performs no mutation.
8. Native/container installs remain idempotent enough to be safely repeated for upgrades.

## Local checks

```sh
npm run check
python3 -m pip install -e 'services/clip-bridge[dev]'
python3 -m compileall -q services/clip-bridge/clip_bridge
pytest -q services/clip-bridge/tests
```
