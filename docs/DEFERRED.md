# Deferred / tech-debt ledger

Rule: nothing important gets silently dropped. When a decision is punted, it lands here with a revisit trigger.

| # | Item | Why deferred | Revisit trigger |
|---|---|---|---|
| 1 | Windows support for `dxcli clean` (junctions, AppData layouts) | Linux/macOS-first keeps Phase 1 shippable | First 3 Windows-specific clean issues, or Phase 4 review |
| 2 | `textual` as an optional extra (install-weight reduction for CI users) | Breaking install layout mid-roadmap is churn | If install-time complaints appear in issues |
| 3 | PyInstaller single-binary build | Packaging rabbit hole; ghcr image covers the fast-start need | If Action cold-start becomes a top-3 complaint |
| 4 | GUIDE_CI.md Jenkins section refresh + GitLab MR comment parity | GitHub loop first (PRD non-goal) | Phase 5 entry review |
| 5 | `dxcli/server/` scaffolding (untracked, from V4) | Unaudited; MCP phase will audit reuse-vs-replace | Phase 3 start |
| 6 | Plugin ecosystem investment beyond keeping loader working | No demand signal | 5+ plugin-related issues/requests |
| 7 | SLSA provenance / artifact attestation on releases | Stretch; Trusted Publishing covers the main risk | After Marketplace listing is live |
| 8 | `fleet` / `serve` / `daemon` marketing & docs depth | Demoted per Reshape A positioning | Phase 5 (hosted) entry, if ever |
