# Contributing

Contributions should preserve the following boundaries:

1. PeerTube remains the canonical authority for user identity and source-video permissions.
2. The plugin remains a thin UI/authentication/authorization façade.
3. Long-running AI, media and rendering work runs outside the PeerTube process.
4. Canonical transcript text comes from PeerTube captions whenever available.
5. AI candidate output is treated as a suggestion for human review, not as an automatic editorial decision.
6. Exact duplicates may be suppressed, while partial overlap is allowed when editorially distinct.

Before proposing a new dependency, explain why it belongs in the plugin, bridge, analysis adapter or renderer adapter.
