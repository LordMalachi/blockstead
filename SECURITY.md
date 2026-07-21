# Security policy

Blockstead 1.x is intended for local or trusted private-network use and should
not be exposed directly to the public internet. It binds to localhost by
default.

Report suspected vulnerabilities privately to the repository owner. Do not put
credentials, session cookies, server worlds, player data, or exploit details in
a public issue. Include the affected revision, reproduction steps using
sanitized fixtures, and likely impact.

Security fixes must preserve the boundaries in `docs/threat-model.md` and add a
negative regression test.
