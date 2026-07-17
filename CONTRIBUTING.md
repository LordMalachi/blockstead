# Contributing

Read `docs/product-spec.md`, `docs/architecture.md`, and
`docs/threat-model.md` first; `README.md` is the owner-facing setup guide.
Never commit Minecraft jars, worlds, secrets, or real player data.

Use `./scripts/bootstrap-dev.sh`, then `./scripts/test.sh`. Changes to security
boundaries need negative tests and a threat-model update. Lifecycle changes
must be tested with the fake server process; ordinary tests may not download a
Minecraft server.

The repository owner has not selected an open-source license, so contributions
do not imply a redistribution grant.
