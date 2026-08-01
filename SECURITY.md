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

## Current dependency-audit exception

As of 2026-07-31, `npm audit` reports
[GHSA-qwww-vcr4-c8h2](https://github.com/advisories/GHSA-qwww-vcr4-c8h2)
for React Router 7.18.1. The advisory states that only applications using the
unstable React Server Components APIs are affected; Blockstead is a client-only
Vite application and uses none of those APIs. npm currently offers only a
forced downgrade to 7.11.0, while the advisory's patched release is 8.3.0.
Do not force the downgrade: reassess this exception when a compatible patched
7.x release exists or Blockstead deliberately migrates to React Router 8.
