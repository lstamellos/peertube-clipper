# Installation

## Design principle

PeerTube plugins run inside the PeerTube application process. They are an appropriate place for JavaScript dependencies, hooks, routes, settings and UI assets; they are **not** an appropriate privilege boundary for installing operating-system packages or managing privileged services.

PeerTube Clipper therefore separates installation into two layers:

1. the PeerTube plugin, installed by PeerTube's supported plugin mechanism;
2. companion services, installed by the administrator-run `scripts/install.sh`.

The plugin never receives access to `sudo`, `apt`, `systemctl` or `/var/run/docker.sock`.

## Installer modes

### Container mode (default)

Requirements:

- Docker Engine;
- Docker Compose v2;
- a working PeerTube installation if the plugin is to be installed in the same run.

The installer stages a self-contained stack under a state directory, creates a random service credential on first installation, builds the Clip Bridge and starts it. The default bind is `127.0.0.1:18100`.

Example for a native PeerTube installation:

```sh
sudo ./scripts/install.sh \
  --mode container \
  --peertube-deployment native \
  --peertube-root /var/www/peertube/peertube-latest
```

Optional local analysis service:

```sh
sudo ./scripts/install.sh \
  --mode container \
  --with-analysis \
  --model qwen3:1.7b \
  --peertube-deployment native \
  --peertube-root /var/www/peertube/peertube-latest
```

The Ollama profile is optional and the analysis adapter is still under development; enabling the profile only provisions the service/model.

### Native Bridge mode

Requirements:

- root;
- Python 3.11+ with `venv` support;
- systemd.

The installer creates:

- service user `peertube-clipper`;
- `/opt/peertube-clipper` for the virtual environment/application;
- `/var/lib/peertube-clipper` for persistent data;
- `/etc/peertube-clipper/bridge.env` for the private service credential;
- `peertube-clipper-bridge.service`.

Example:

```sh
sudo ./scripts/install.sh \
  --mode native \
  --peertube-deployment native \
  --peertube-root /var/www/peertube/peertube-latest
```

The installer does not install Python, systemd or operating-system packages on the administrator's behalf; it validates prerequisites and fails with a clear error when they are missing.

### External mode

Use this when the Bridge is already deployed elsewhere:

```sh
sudo PEERTUBE_CLIPPER_SERVICE_TOKEN='replace-me' \
  ./scripts/install.sh \
  --mode external \
  --bridge-url http://10.0.0.20:18100 \
  --peertube-deployment native \
  --peertube-root /var/www/peertube/peertube-latest
```

For automation, prefer `--bridge-token-file PATH` instead of placing a credential directly in shell history.

## Idempotent reruns and credential rotation

Container and native installer reruns reuse the existing Bridge service credential by default. This keeps upgrades and `--skip-plugin` Bridge-only maintenance from silently desynchronizing the Bridge and PeerTube plugin configuration.

Rotate the credential only deliberately:

```sh
sudo ./scripts/install.sh \
  --rotate-token \
  --mode container \
  --peertube-deployment native \
  --peertube-root /var/www/peertube/peertube-latest
```

When rotation is requested in a normal combined installation, the installer writes the new credential to both sides before completion. Do not use `--rotate-token` together with `--skip-plugin` unless the plugin configuration will be updated separately.

## Native PeerTube plugin installation

PeerTube Clipper uses PeerTube's supported local plugin installer:

```text
npm run plugin:install -- --plugin-path ...
```

The local staging directory passed to PeerTube always has the exact basename `peertube-plugin-clipper`, because PeerTube derives local plugin identity from that basename.

The general installer auto-detects the PeerTube service user from the application tree when possible. For non-standard layouts, provide:

```text
--peertube-user USER
--peertube-config-dir PATH
--peertube-storage-dir PATH
```

The Bridge URL/token are written into a private `bridge.json` file in the plugin's server-side data directory. This avoids requiring PeerTube admin API credentials during installation and keeps the Bridge credential out of browser code.

## Dockerized PeerTube

For an official-style Compose deployment:

```sh
./scripts/install.sh \
  --mode external \
  --bridge-url http://bridge.internal:18100 \
  --bridge-token-file /secure/bridge-token \
  --peertube-deployment docker \
  --peertube-compose-dir /srv/peertube \
  --peertube-service peertube
```

The installer copies the local plugin package into the running PeerTube container and runs PeerTube's own `plugin:install` command there.

Important: `127.0.0.1` inside the PeerTube container is **not** the Docker host. When PeerTube itself is containerized and the Bridge is outside that same container, `--bridge-url` must name an address reachable from the PeerTube container. Keep that address on a private network and firewall it appropriately.

The official PeerTube image normally uses `/app` as the application root and `/data/plugins` for plugin data; both can be overridden with installer flags.

## Validation

Read-only installation validation:

```sh
sudo ./scripts/validate-installation.sh \
  --peertube-root /var/www/peertube/peertube-latest \
  --peertube-storage /var/www/peertube/storage \
  --peertube-url https://video.example.org \
  --show-identifiers
```

A separate `scripts/validate-review-e2e.sh` validator performs a controlled shared-review authorization test. It requires an existing source video with a channel owner, an accepted channel collaborator/editor and an unrelated ordinary user. The validator:

- refuses to run if that source already has a Clipper workflow;
- creates short-lived OAuth sessions without changing passwords or existing sessions;
- seeds three temporary Bridge candidates;
- verifies owner access, editor access to the same shared state and `403` for the unrelated user;
- exercises edit, approve and reject actions and verifies audit actor IDs;
- revokes all temporary sessions through PeerTube's normal revoke API;
- deletes the temporary Bridge workflow and verifies that it is gone.

Token and service credential values are never printed. This validator intentionally writes temporary test state, so it should only be run by an administrator who understands the selected accounts/source video.

## Dry run

Every deployment should be rehearsed first on unfamiliar layouts:

```sh
./scripts/install.sh \
  --dry-run \
  --mode container \
  --peertube-deployment native \
  --peertube-root /custom/peertube/peertube-latest
```

No service credential is printed by the installer.

## Uninstall

Container mode:

```sh
./scripts/uninstall.sh --mode container
```

Native Bridge mode:

```sh
sudo ./scripts/uninstall.sh --mode native
```

By default, persistent Bridge data is preserved. Use `--purge` only when deliberate data removal is intended.

Plugin removal can be combined with the same command by providing the corresponding `--peertube-deployment` options.

## Manual Bridge development start

```sh
cd services/clip-bridge
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
export PEERTUBE_CLIPPER_SERVICE_TOKEN=development-only
uvicorn clip_bridge.main:app --host 127.0.0.1 --port 18100
```
