# Security Policy

This project is pre-alpha and should not yet be exposed directly to the public internet.

## Trust boundaries

- PeerTube authenticates end users.
- The PeerTube plugin authorizes access to each source video.
- The Clip Bridge trusts only authenticated requests from the plugin server.
- The Clip Bridge should bind to loopback or a private network by default.
- Analysis and rendering workers must not run inside the PeerTube process.

## Do not

- expose the Clip Bridge without authentication;
- pass the bridge service credential to browser JavaScript;
- mount `/var/run/docker.sock` into PeerTube;
- grant the PeerTube service account passwordless sudo for this project;
- store API keys, model credentials or service tokens in the repository;
- infer video management permission only from uploader identity.

Please report security issues privately to the repository maintainer rather than opening a public issue containing exploit details.
