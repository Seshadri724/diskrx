# dxcli — project docs

Institutional memory for the project. Read in this order if you're new:

| Doc | What it is |
|---|---|
| [PRD.md](PRD.md) | Product requirements — press release, FAQ, goals/non-goals, metrics with a pre-committed kill criterion, testable FRs/NFRs |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Technical design — component diagram, technology trade-offs, data model, API contracts, failure modes, security architecture |
| [ROADMAP.md](ROADMAP.md) | Phased build plan (0–5) with step-by-step instructions and checkpoint gates per phase |
| [RESOURCES.md](RESOURCES.md) | Libraries, platform docs, tooling, and reference projects per phase |
| [DEFERRED.md](DEFERRED.md) | Tech-debt / deferred-decisions ledger — nothing gets silently dropped |
| [examples/](examples/README.md) | Copy-pasteable CI/Docker/devcontainer recipes (user-facing) |

Design docs for individual features land in `docs/design/` as each phase starts (`clean.md`, `autopsy.md`, `mcp.md`, `hosted.md`).
