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

The installer stages a self-contained stack under a state directory, generates a random service credential, builds the Clip Bridge and starts it. The default bind is `127.0.0.1:18100`.

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

## Native PeerTube plugin installation

PeerTube Clipper uses PeerTube's supported local plugin installer:

```text
npm run plugin:install -- --plugin-path ...
```

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
