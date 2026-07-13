# dxcli — Development Roadmap

> **Status:** v1.0 · 2026-07-13 · Companion to [PRD.md](PRD.md) and [ARCHITECTURE.md](ARCHITECTURE.md)
> **Shape:** 5 phases + 1 conditional phase over a **2-month build timebox** (evenings) + 1 month of distribution. Each phase lists objectives, step-by-step instructions, deliverables, and a **checkpoint gate** — you do not advance while a gate item is red.
> **Operating rules for AI-assisted building** (apply to every phase):
> 1. Every AI-generated change lands as a small, reviewed diff with tests — *read the code, especially deletion paths*.
> 2. No invented dependencies: any new package is verified on PyPI (name, maintenance, downloads) before `pip install`.
> 3. Anything uncertain is labeled UNVERIFIED in code review notes and confirmed before merge.
> 4. Keep a `DEFERRED.md` tech-debt ledger; nothing is silently dropped.

---

## Phase 0 — Foundation & repo readiness (Week 0, ~2 evenings)

**Objective:** the repo is public-ready, releases are automated, and CI is the reviewer — so every later phase is fast and safe.

### Instructions
1. Merge `reshape-a-developer-ci` into `master` (or make it the mainline).
2. **History & hygiene scrub** (blocking for Marketplace):
   - Remove `fleet_snapshots.db` from the working tree and add to `.gitignore`; check `git log` for other accidental artifacts (`dist/`, `DEBUG_LOG.md` — decide keep/remove deliberately).
   - Add issue templates (bug: require `dxcli --version`, OS, reproduction; feature: require use case) and a `SECURITY.md` with a private disclosure contact.
3. **CI hardening** (`.github/workflows/`):
   - Test matrix: {3.8, 3.12, 3.13} × {ubuntu, macos, windows}; lint (`black --check`, `flake8`), `bandit`, `pip-audit`, secret scan (gitleaks action) — all required checks on PRs.
   - Pin all third-party actions by commit SHA.
4. **Release automation:** workflow on tag `v*`: build sdist/wheel → run tests → publish to PyPI via **Trusted Publishing** (configure the PyPI publisher for the repo first) → build & push `ghcr.io/seshadri724/dxcli` → draft GitHub Release from CHANGELOG.
5. Turn on branch protection: required checks + linear history.
6. Create `docs/DEFERRED.md` (tech-debt ledger) and seed it with known items (e.g., Windows `clean` edge cases, GUIDE_CI Jenkins section refresh).

### Checkpoint gate — Phase 0 exit
- [ ] `git tag v0.3.1 && git push --tags` produces a PyPI release and a ghcr image with **zero manual steps**.
- [ ] A deliberately-broken PR (failing test, a hardcoded fake secret) is blocked by CI. *(Scaffolding gate: CI actually blocks.)*
- [ ] Repo contains no committed artifacts/DBs; `git status` clean policy documented in CONTRIBUTING.
- [ ] SECURITY.md, issue templates, branch protection live.

---

## Phase 1 — `dxcli clean` (Weeks 1–2) — the star magnet

**Objective:** the single most shareable command in the category, with deletion safety as the headline feature.

### Instructions
1. **Design first (1 evening):** write `docs/design/clean.md` — the `CacheTarget` catalog (pip, npm, yarn, pnpm, cargo registry, gradle, go build cache, Docker dangling/build-cache, stale venvs), detectors, reversibility classes, and the **threat model for deletion**:
   - Abuse/accident cases: symlinked cache dir pointing at `$HOME`; `HOME` unset/weird; path with unicode/spaces; cache path that is a mountpoint; concurrent `clean` runs; interrupted deletion.
   - Every case gets a named mitigation, most inherited from heal engine (realpath containment, scope checks) — new mitigations go in the plan.
2. **Build planner** (`dxcli/analyzers/clean_catalog.py` + `dxcli/clean_planner.py`): pure planning, no I/O beyond stat/du; unit tests with fake filesystems (`tmp_path`), including *adversarial* fixtures for each threat case.
3. **Wire executor through heal engine** — clean never calls `shutil.rmtree` itself. Extend heal journal for `IRREVERSIBLE` class (journal the *decision*, not the bytes).
4. **CLI command** per FR-010…FR-014: dry-run default, `--yes`, `--json`, `--only/--skip`, human-readable table with category/size/reversibility.
5. **Tests as the gate:** property-style tests that generate path structures and assert nothing outside catalog roots is ever in a plan; integration test that runs `clean --yes` in a scratch home and diffs the filesystem against expectation.
6. **Staged release:** ship `v0.4.0` with clean **dry-run only** (executor behind `DXCLI_CLEAN_EXPERIMENTAL=1`); dogfood on your own machine for a week; then `v0.5.0` enables `--yes` generally.
7. Update README (`clean` gets a top-3 slot), record a terminal GIF (vhs or asciinema) for the README.

### Checkpoint gate — Phase 1 exit
- [ ] Threat-model doc exists; **every Critical/High case has a named, tested mitigation.** *(Phase-4-style gate, scoped to deletion.)*
- [ ] Mutation check: deliberately break the scope check in a branch — at least one test fails. *(Tests actually protect.)*
- [ ] `dxcli clean` on your real machine: dry-run output audited by hand, then `--yes` reclaims with zero false positives; `dxcli undo` restores a reversible target.
- [ ] Windows behavior decided and documented (support or graceful "not yet").
- [ ] AI-provenance review: you have personally read every line of planner + executor diff. *(Supp-B gate: no unreviewed AI code in security paths.)*
- [ ] v0.4.0 (dry-run) shipped ≥ 5 days before v0.5.0 (`--yes`).

---

## Phase 2 — Autopsy + PR comments + Marketplace (Weeks 3–4) — the growth loop

**Objective:** failed builds become advertisements: guard → build fails → autopsy comment appears on the PR.

### Instructions
1. **Verify GitHub environment facts first** (30 min, before code): confirm on a scratch repo the exact env/event-payload fields for PR number discovery, `GITHUB_TOKEN` default permissions, comment size limit, fork-PR token behavior. Record findings in `docs/design/autopsy.md`. *(These were assumptions in ARCHITECTURE §3 — de-risk them first.)*
2. **Snapshot command** (FR-001): reuse `DirectoryTreeCollector` + docker collector; atomic JSON write; `schema: 1`.
3. **Autopsy engine** (FR-002): diff module (baseline vs fresh scan), route growth paths through `PrescriptionEngine`; absolute-report fallback when no baseline.
4. **Renderers** (FR-003): markdown (marker comment, deterministic ≤64 KB truncation) and JSON; job-summary writer (`$GITHUB_STEP_SUMMARY`).
5. **Commenter** (FR-004): stdlib HTTP client, marker-based upsert, retry/backoff, fork-PR fallback path, token redaction in all logging.
6. **Action v2** (FR-005): `autopsy: true` input wires baseline in a pre-step and autopsy in a post-failure step (composite `post:` steps can't be conditional — implement as documented two-step usage or use `if: failure()` guidance in README; decide in design doc).
7. **Integration proof:** a public scratch repo with a workflow that deliberately fills disk → CI fails → comment appears. Screenshot goes in README.
8. **Marketplace:** release `v1.0.0` of the action, publish listing (name, icon, categories: CI, utilities), floating `@v1` tag automation.
9. Ship dxcli `v0.6.0`.

### Checkpoint gate — Phase 2 exit
- [ ] Live demo repo: failing build produces exactly **one** comment, re-runs update it (no duplicates), fork-PR run degrades to summary with exit 0.
- [ ] Comment renders correctly at the 64 KB truncation boundary (test with synthetic 500-dir growth set).
- [ ] `GITHUB_TOKEN` never appears in logs at any verbosity (grep CI logs of demo runs).
- [ ] Action listed on Marketplace; `uses: Seshadri724/dxcli@v1` works from a *different* account/repo.
- [ ] README top section shows the PR-comment screenshot (the product is the artifact).
- [ ] Failure-mode table from ARCHITECTURE §7 has a test or documented manual verification per row (GitHub API down → fallback, missing baseline → absolute report, no Docker → degrade).

---

## Phase 3 — MCP server mode (Weeks 5–6) — the agent bet

**Objective:** dxcli is the disk tool agents call; ~1 week of work buys the option.

### Instructions
1. **Pin the SDK:** check the current official `mcp` Python SDK release, pin exact version, note protocol revision in `docs/design/mcp.md`. *(Q3 from PRD — resolve before code.)*
2. Add optional extra `dxcli[mcp]`; `dxcli mcp` errors helpfully if extra not installed.
3. **Shared serializers first:** extract the `diagnose --json` encoder into a module both CLI and MCP use (FR-021 single source of truth) — this is a refactor of `cli.py`'s inline `DxEncoder`; keep CLI output byte-identical (golden-file test).
4. Implement the five read-only tools (FR-020) with the path allowlist enforced per call (FR-022); stdout discipline (server logs → stderr).
5. **Agent-facing docs:** `docs/MCP.md` with Claude Code registration (`claude mcp add dxcli -- dxcli mcp`), Claude Desktop config snippet, and 3 worked agent transcripts ("why is my disk full?" → agent calls `diagnose` → grounded answer).
6. Dogfood: register in your own Claude Code, run the three scenarios, paste real transcripts into docs.
7. Ship `v0.7.0`; submit/announce in MCP server directories and lists.

### Checkpoint gate — Phase 3 exit
- [ ] Claude Code session demonstrably answers a disk question via dxcli tools (transcript saved in docs).
- [ ] Allowlist test: tool call for a path outside allowlist is refused, with a useful error.
- [ ] No deletion reachable through MCP (grep + test: `clean_preview` only).
- [ ] CLI `--json` outputs byte-identical pre/post refactor (golden files).
- [ ] Listed in at least 2 MCP directories/awesome lists.

---

## Phase 4 — Launch push & measurement (Weeks 7–8 + distribution month)

**Objective:** concentrated distribution, then honest measurement against the pre-committed kill criterion.

### Instructions
1. **The data post:** run dxcli's engine over N popular public repos' workflow patterns (or instrument scratch builds of popular OSS) and write *"I profiled disk usage of X popular CI setups — half are one `npm ci` from failure."* Publish on dev.to + personal blog; submit Show HN mid-week morning US time; cross-post r/devops, r/github.
2. Submit to awesome lists: awesome-ci, awesome-actions, awesome-python, awesome-mcp-servers (PRs with honest one-line descriptions).
3. Add GitHub Sponsors (tip-jar framing) + "Sponsor" button; polish repo social preview image.
4. **Metrics baseline:** record week-0 values for every PRD §5 metric in `docs/METRICS.md`; update weekly (public signals only: pypistats, star count, Marketplace insights, code-search counts).
5. Respond to every issue within 48h during launch month; label `good-first-issue` generously.
6. **Week 12 review — write the verdict in `docs/METRICS.md`:**
   - North Star growing MoM → open Phase 5 evaluation.
   - Flat → execute the kill criterion: maintenance mode, pin versions, write the retro, take the portfolio win. *(This is a pre-commitment; don't relitigate it under sunk-cost pressure.)*

### Checkpoint gate — Phase 4 exit
- [ ] Blog post published + submitted to ≥3 channels; HN/Reddit threads answered same-day.
- [ ] `docs/METRICS.md` has ≥4 weekly entries with real numbers.
- [ ] All launch-week bugs triaged; nothing critical open >7 days.
- [ ] **Verdict recorded** (grow / maintain) with the numbers that justify it.

---

## Phase 5 — CONDITIONAL: hosted history ("the actual business")

**Entry gate (all must be true — this is the Monetization gate):**
- [ ] North Star grew MoM through the distribution month.
- [ ] ≥25 public repos run autopsy in anger (code-search evidence).
- [ ] ≥5 unsolicited requests for history/trends/org features exist in issues.
- [ ] You have appetite for on-call, accounts, and billing (write it down; it's a lifestyle change, not a feature).

**If entered — build order sketch (spec first, 2-week spike cap):**
1. Spec `docs/design/hosted.md` against ARCHITECTURE §8 sketch: FastAPI ingest (`POST /v1/snapshots`, repo-scoped tokens), Postgres, per-PR regression comparison, GitHub App for comments (solves the fork-token problem properly).
2. Run this same pipeline's higher tiers on it: real threat model (multi-tenant data isolation), pricing validation *before* building billing (talk to the 5 requesters; target $10–20/repo-set/mo), then a private beta with the requesters.
3. Kill trigger inside Phase 5: if <50% of beta repos are still sending snapshots after 30 days, archive the spike.

**If not entered:** the pivot direction on file is **CI cost optimization** (dollars, not bytes) — revisit PRD §9.

---

## Cross-phase checkpoint summary (print this)

| Phase | Ships | The one gate that matters most |
|---|---|---|
| 0 | v0.3.1 (automation) | Tag → PyPI+ghcr with zero manual steps |
| 1 | v0.4.0 dry-run, v0.5.0 `--yes` | Deletion threat model tested; every planner line human-read |
| 2 | v0.6.0 + Action v1 on Marketplace | One idempotent comment on a real failing PR, fork-safe |
| 3 | v0.7.0 `[mcp]` | Real agent transcript answering via dxcli tools |
| 4 | Launch | Verdict written down with numbers |
| 5 | (conditional) | Entry gate met with evidence, not hope |
