# Security Design

## Browser → PeerTube plugin

Use the existing authenticated PeerTube session. Do not create a second login system.

## PeerTube plugin → Clip Bridge

Use a private endpoint and a generated service credential. The credential is server-side only.

## Clip Bridge → analysis/render services

Use private networking wherever possible. Provider API keys, if used, belong to the Bridge/worker environment and must never be exposed in browser responses or technical reports.

## Host permissions

The PeerTube service account should not receive:

- membership in the Docker group;
- access to the Docker socket;
- passwordless sudo for PeerTube Clipper;
- write permission to Clip Bridge service directories beyond any explicitly required socket/token file.

## Transcript handling

Technical diagnostics should report sizes/counts/timestamps, not dump full transcripts. Review payloads necessarily contain the selected canonical excerpts.
