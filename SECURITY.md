# Security policy

Blockstead is pre-release software and should not be exposed to the public
internet. It binds to localhost by default.

Report suspected vulnerabilities privately to the repository owner. Do not put
credentials, session cookies, server worlds, player data, or exploit details in
a public issue. Include the affected revision, reproduction steps using
sanitized fixtures, and likely impact.

Security fixes must preserve the boundaries in `docs/threat-model.md` and add a
negative regression test.
