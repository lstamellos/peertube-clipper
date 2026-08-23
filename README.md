# PeerTube Clipper

PeerTube Clipper is a review-first clip discovery and production workflow for PeerTube.

The project is built around a simple rule: automated analysis may discover candidate moments, but a human editor reviews, rejects, approves or adjusts them before rendering.

## Status

**Pre-alpha / architecture foundation.**

The repository currently provides:

- a PeerTube plugin package and temporary per-video entry surface;
- a private Clip Bridge service with persistent shared per-video/candidate state;
- a general installer for native or containerized companion services;
- native and Docker PeerTube plugin installation paths;
- server-side Bridge configuration that does not expose service credentials to the browser;
- documentation for architecture, permissions, installation, operations and security;
- CI checks for Node, shell and Python components.

Automatic analysis, the final per-video review UI and renderer adapters remain under active development.

## Goals

- Keep PeerTube authoritative for video identity, user identity, permissions and captions.
- Use corrected PeerTube captions as the canonical transcript whenever available.
- Start analysis only after source readiness conditions are satisfied.
- Present one shared candidate queue per source video to every user who can manage that video/channel.
- Require human review before rendering.
- Allow partial overlap when candidates serve different editorial purposes.
- Suppress only exact/effectively identical duplicates.
- Keep long-running AI and rendering work outside the PeerTube server process.
- Avoid a long-lived fork of PeerTube or the rendering backend.

## Architecture

```text
PeerTube
  Manage → plugin entry
        │
        │ authenticated plugin API
        ▼
PeerTube plugin (UI + authorization façade)
        │
        │ private service API
        ▼
Clip Bridge
  ├─ readiness gate
  ├─ canonical transcript adapter
  ├─ candidate/state persistence
  ├─ analysis adapter
  └─ renderer adapter
        │
        ├─ local/remote analysis backend
        └─ renderer backend
```

The preferred final UX is a `Clips` page inside the Manage area of each source video. Until PeerTube exposes a supported child-page extension point for Video Manage, the plugin uses supported plugin surfaces and keeps the review application portable.

See [Architecture](docs/ARCHITECTURE.md), [Permissions](docs/PERMISSIONS.md) and [Installation](docs/INSTALLATION.md).

## Repository layout

```text
packages/peertube-plugin-clipper/   PeerTube plugin façade/UI
services/clip-bridge/               Private orchestration/state service
docs/                               Architecture and operations documentation
scripts/                            Installer and maintenance entry points
```

## General installer

The plugin itself does **not** receive package-manager, systemd, sudo or Docker-socket privileges. Instead, the repository ships an administrator-run installer:

```sh
./scripts/install.sh --help
```

Companion service modes:

- `container` — default; builds and runs the Bridge with Docker Compose and can optionally start Ollama;
- `native` — installs the Bridge into a dedicated Python virtual environment and systemd service;
- `external` — connects the plugin to an already deployed Bridge.

PeerTube deployment modes:

- `native` — installs the plugin with PeerTube's supported `npm run plugin:install` mechanism;
- `docker` — installs the plugin into a running PeerTube Compose service;
- `skip` — installs/configures companion services only.

Examples are in [docs/INSTALLATION.md](docs/INSTALLATION.md).

## Security model

- Browser requests are authenticated by PeerTube.
- The plugin server is the authorization façade.
- Candidate state is keyed by source video UUID, not by user.
- Review actions retain acting-user audit attribution.
- The Bridge is private/loopback by default and requires a service credential.
- The browser never receives that service credential.
- The PeerTube process is never granted Docker-socket, sudo, package-manager or systemd access by this project.

## Development checks

```sh
npm run check
python3 -m pip install -e 'services/clip-bridge[dev]'
pytest -q services/clip-bridge/tests
```

## License

AGPL-3.0-only. Third-party components retain their own licenses. No third-party source code is vendored by this repository.
