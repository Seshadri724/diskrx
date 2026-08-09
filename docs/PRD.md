# dxcli — Product Requirements Document

> **Status:** Draft v1.0 · 2026-07-13
> **Owner:** Seshadri Naidu Vangapandu
> **Strategy:** Portfolio-grade open-source project with a growth loop, not a startup. Paid tier is a *conditional* future bet gated on traction evidence (see [ROADMAP.md](ROADMAP.md), Phase 5 gate).

---

## 1. Press Release (written as if launching today)

**dxcli 1.0: your CI build just died at 94 minutes — now you know why in 10 seconds.**

*The disk doctor for CI pipelines and dev boxes now performs autopsies on failed builds, posts the diagnosis straight to your pull request, and cleans your dev machine with one command.*

Every developer has seen it: `No space left on device`, halfway through a build that passed locally. The usual response is an hour of `du -sh *`, a shrug, and a bigger runner. dxcli replaces that hour. Add one step to your workflow and dxcli guards the runner before the build, performs an autopsy when a build fails — *"this build wrote 12.4 GB: 8.1 GB Docker build cache, 3.2 GB in `/tmp/pytest-*`"* — and posts the findings as a PR comment so the whole team learns from one failure. On your laptop, `dxcli clean` finds the 23 GB of pip/npm/cargo caches and dead venvs you forgot about and reclaims them safely, reversibly, with a dry-run by default. And because modern debugging happens in AI agents too, `dxcli mcp` exposes the whole diagnostic engine to Claude Code and any MCP-compatible agent.

"We built dxcli around one principle: prescription over description," said the maintainer. "Every other disk tool shows you bytes. dxcli tells you what happened, which process did it, and the exact command that fixes it."

Getting started takes one line: `pip install dxcli`, then `dxcli ci` in your pipeline or `dxcli clean` on your machine.

## 2. Internal FAQ — the ten hardest questions

1. **Why will anyone use this over `du`/`ncdu`/`docker system df`?**
   Those are viewers; dxcli is a decision engine with exit codes, attribution, and prescriptions. But honestly: the wedge is not "better du" — it's the PR comment. No incumbent posts a disk autopsy to a pull request.

2. **Why will this make money?**
   It probably won't, directly — and the PRD says so out loud. The primary return is reputation capital (stars, Marketplace installs, blog reach) plus a cheap option on a paid hosted-history tier *if* the traction gate in Phase 5 is met. Budget expectations: hundreds/month ceiling, not thousands.

3. **What's the moat?**
   Thin, and narrowing as agents get better at ad-hoc diagnosis. The defensible positions are (a) being the disk tool agents call via MCP, and (b) the PR-comment growth loop compounding installs. Speed to those two positions *is* the strategy.

4. **Why would a team trust a tool that deletes files?**
   Dry-run by default, explicit `--yes` for anything irreversible, scoped deletion via the existing zero-trust heal engine (realpath scoping, symlink-escape rejection), and an undo stack for everything undoable. Deletion safety is a Phase-1 exit gate, not a feature.

5. **What kills this project?**
   Flat install curve after the launch push. The kill criterion is explicit: if weekly Action runs haven't grown month-over-month by the end of the 2-month timebox, stop feature work, leave it in maintenance mode, take the portfolio win.

6. **Why Python? CI users hate slow installs.**
   Because the engine already exists and works. Mitigation, not rewrite: prebuilt Docker image (`ghcr.io/...`) for container jobs, `pipx`/`uv tool install` docs, and a PyInstaller single binary as a stretch goal. A Rust rewrite is an explicit non-goal.

7. **How do we measure anything with zero telemetry?**
   Public signals only: GitHub Marketplace install count, Action run badges on public repos (searchable), PyPI download stats (pypistats/BigQuery), stars, ghcr pulls. Zero telemetry is a trust feature we keep.

8. **What about fork PRs where `GITHUB_TOKEN` can't write comments?**
   Known limitation; autopsy falls back to a job-summary (`$GITHUB_STEP_SUMMARY`) and an artifact. Documented, not hidden.

9. **Isn't the AI/MCP angle a gimmick?**
   It's a distribution bet, priced accordingly (~1 week of work). If agent marketplaces develop paid placement or default toolsets, early presence pays off; if not, we lose one week.

10. **Who maintains this at scale?**
    One person, evenings. Which is why every phase gate includes "CI is the reviewer": lint, tests, security scans block merges so drive-by contributions don't consume the maintainer.

## 3. Problem Statement

- **Pain:** CI builds fail with `No space left on device` — cryptically, mid-build, after wasted runner minutes. GitHub's `ubuntu-latest` image starts at roughly 80–85% disk-used; a single `npm ci` + Docker build can push it over. Locally, developer machines accumulate tens of GB of package-manager caches and stale venvs with no unified cleanup.
- **Frequency:** "no space left on device github actions" is a perennially searched error; large monorepos hit it weekly. Dev-box bloat is universal and chronic.
- **Current cost:** 30–60 min of developer debugging per CI incident (cryptic I/O errors, corrupted artifacts), plus the standing tax of oversized runners bought to paper over the problem.
- **Current alternatives:** bigger runners (money), `docker system prune` in cron (blunt, no attribution), `maximize-build-space`-style actions (space, but no diagnosis), manual `du` archaeology (time).

## 4. Goals & Non-Goals

### Goals (v1)
1. Become the drop-in disk guard + autopsy for GitHub Actions (one step, one Marketplace listing).
2. Ship the single most shareable dev-box command in the category: `dxcli clean`.
3. Be the disk tool AI agents reach for, via a first-class MCP server mode.
4. Grow via artifact, not ads: every autopsy PR comment is an advertisement with a repo-wide audience.

### Non-Goals (v1) — aggressive, on purpose
- **No hosted service, no accounts, no billing.** Phase 5 is spec-only until the traction gate passes.
- **No telemetry of any kind.** Not even opt-in in v1.
- **No Rust/Go rewrite.** Packaging mitigations only.
- **No Kubernetes/node-fleet monitoring push.** `fleet`/`serve`/`daemon` stay as-is (maintained, not marketed).
- **No Windows CI runners support guarantee for `clean`** in v1 (dev-box use on Windows: yes; exotic CI images: best-effort).
- **No plugin-ecosystem investment** beyond keeping the existing opt-in loader working.
- **No CircleCI/Azure DevOps first-class recipes** in v1 (GitHub Actions + GitLab CI only).

## 5. Success Metrics (zero-telemetry constraint: public signals only)

| Metric | Type | Definition & measurement | Target | Horizon |
|---|---|---|---|---|
| **Weekly GitHub Action runs** | **North Star** | Marketplace insights + code-search count of workflows referencing `Seshadri724/dxcli` | 200 repos referencing; MoM growth every month | 6 months |
| PyPI downloads/week | Input | pypistats.org weekly, excluding mirrors | 1,000/wk | 3 months |
| GitHub stars | Input | Repo star count | 1,000 (launch-post spike ok; watch 30-day retention slope) | 3 months |
| Autopsy adoption | Input | Code-search: workflows using `if: failure()` + dxcli autopsy step | 25 public repos | 6 months |

**Kill criterion (pre-committed):** if North Star shows no MoM growth at the end of the 2-month build timebox + 1 month of distribution, freeze features; maintenance mode.

## 6. User Stories (MoSCoW — v1 ships Must only)

**Must**
- As a **developer whose CI build just died**, I want a post-failure report saying exactly what filled the disk during the build, so I fix the cause instead of buying a bigger runner. *(autopsy)*
- As a **teammate reviewing a PR**, I want the disk autopsy visible in the PR conversation, so the fix happens in review, not in a wiki. *(PR comment / job summary)*
- As a **pipeline author**, I want a one-step guard that fails fast when the runner is unhealthy, with a copy-pasteable Marketplace action. *(ci guard — shipped; Marketplace — v1)*
- As a **developer with a full laptop**, I want one command that shows what's safely reclaimable across pip/npm/yarn/pnpm/cargo/gradle/go/docker and reclaims it only after my explicit confirmation. *(clean)*
- As an **AI-agent user**, I want my agent to diagnose disk issues using dxcli's engine, so answers come with attribution and safe prescriptions instead of guessed shell commands. *(mcp)*

**Should**
- As a pipeline author, I want a prebuilt Docker image so the guard adds seconds, not a pip install, to container jobs.
- As a security-conscious adopter, I want pinned, attested releases (SLSA provenance on the Action, Trusted Publishing on PyPI).

**Could**
- Job-summary rendering with charts; `dxcli clean --schedule` hints; GitLab MR comment parity.

**Won't (v1)**
- Hosted history, org dashboards, Slack app, per-PR regression tracking. *(Phase 5 bet, gated.)*

## 7. Functional Requirements (numbered, testable)

**Autopsy**
- **FR-001** `dxcli snapshot --baseline <file>` writes a JSON snapshot (partition usage + top-N dir sizes + docker df if available) in < 60 s on a standard runner.
- **FR-002** `dxcli autopsy --baseline <file>` diffs current state vs baseline and emits: total bytes written, top 10 growth paths with byte deltas, Docker growth breakdown, and ≥1 prescription per growth path where a rule matches.
- **FR-003** `dxcli autopsy --format markdown` emits GitHub-flavored markdown ≤ 64 KB (GitHub comment limit is 65,536 chars) — truncation must be deterministic and labeled.
- **FR-004** With `GITHUB_TOKEN` present and `--pr-comment`, autopsy upserts (creates or updates, never duplicates) a single comment on the PR identified from the Actions environment; on fork PRs (read-only token) it degrades to `$GITHUB_STEP_SUMMARY` with exit code 0.
- **FR-005** The composite Action exposes `autopsy: true` and posts the comment without the user writing any script.

**Clean**
- **FR-010** `dxcli clean` with no flags performs **dry-run only**: lists each reclaimable target with category, path, size, and reversibility class; deletes nothing (verify: filesystem unchanged).
- **FR-011** `dxcli clean --yes` reclaims only targets in the built-in catalog (pip, npm, yarn, pnpm, cargo registry cache, gradle caches, go build cache, Docker dangling images/build cache) plus stale venvs matched by rule; every deletion path must pass the heal engine's realpath-scope check.
- **FR-012** Irreversible targets are labeled `IRREVERSIBLE` in dry-run and require `--yes`; reversible targets are journaled and revertible via `dxcli undo`.
- **FR-013** `dxcli clean --json` emits machine-readable results (schema in [ARCHITECTURE.md](ARCHITECTURE.md) §6).
- **FR-014** A `--only <category>` / `--skip <category>` filter restricts the catalog (verify: skipped category untouched).

**MCP**
- **FR-020** `dxcli mcp` starts an MCP server on stdio exposing tools: `disk_status`, `diagnose`, `diff`, `predict`, `clean_preview`. No tool performs deletion.
- **FR-021** Every MCP tool returns structured JSON matching the same schemas as the CLI `--json` flags (single source of truth: shared serializer).
- **FR-022** MCP server refuses paths outside an allowlist provided at startup (`dxcli mcp --allow <path>...`, default: home + cwd).

**Distribution**
- **FR-030** The GitHub Action is published to the Marketplace with a major-version tag (`@v1`) that tracks the latest compatible release.
- **FR-031** A container image is published to ghcr.io on every release; `docker run ghcr.io/seshadri724/dxcli ci` works.
- **FR-032** Release pipeline: tag push → build → test → PyPI via Trusted Publishing (OIDC, no long-lived token) → ghcr push → GitHub Release with changelog.

## 8. Non-Functional Requirements

| Category | Requirement |
|---|---|
| Performance | Guard (`dxcli ci`) p95 < 30 s on `ubuntu-latest` for a checkout ≤ 5 GB; snapshot < 60 s; `clean` dry-run < 20 s on a typical dev home dir. |
| Footprint | `pip install dxcli` ≤ 15 s on runner-cached PyPI; container image ≤ 250 MB. |
| Reliability | Exit codes are API: 0 healthy, 1 CI failure, distinct codes for validation vs runtime errors (already in `runtime.ExitCode`) — never change meanings within a major version. |
| Safety | No deletion ever occurs without `--yes`; no network call ever occurs except (a) Docker socket, (b) GitHub API when `--pr-comment`, (c) user-configured webhooks. |
| Privacy | Zero telemetry. Autopsy comments contain paths — document that private path names become PR-visible; provide `--redact` pattern option. |
| Compatibility | Python 3.8–3.13; Linux/macOS/Windows for CLI; Linux for the Action. |
| Security | Pinned GitHub Actions by SHA in our own workflows; bandit + pip-audit + secret scan gate merges; SLSA provenance on releases (stretch). |
| Accessibility | `--no-color`/`NO_COLOR` respected; TUI remains optional; all critical output readable in plain logs. |

## 9. Out of Scope & Future Bets

- **Hosted per-repo disk history + PR regression tracking** ("this PR grew your build's footprint 40%") — the actual business, deferred behind the Phase 5 evidence gate because it adds accounts/billing/liability that the traction data must justify.
- **CI cost optimization** (minutes + cache waste in dollars) — the stronger commercial adjacent; noted as the pivot direction if disk-only positioning stalls.
- **GitLab MR comments, Bitbucket, Jenkins plugin** — after GitHub loop proves out.

## 10. Open Questions & Risks

| # | Question / risk | Owner | Deadline |
|---|---|---|---|
| Q1 | Comment upsert strategy: marker-comment + update vs delete+recreate (notification noise) | Maintainer | Phase 2 start |
| Q2 | `clean` on Windows: junction/AppData edge cases — ship v1 as Linux/macOS-first? | Maintainer | Phase 1 design |
| Q3 | MCP SDK pin: `mcp` Python package API stability across releases — pin exact version? **UNVERIFIED: check current SDK release status before Phase 3.** | Maintainer | Phase 3 start |
| Q4 | Marketplace listing requires the repo to be public — confirm repo visibility plan & scrub history (e.g., `fleet_snapshots.db`, `DEBUG_LOG.md`) before publishing | Maintainer | Phase 0 |
| R1 | **Deletion bug = trust death.** One bad `clean` deleting user data ends the project's reputation arc. Mitigation: Phase 1 threat-model gate, property-based path tests, staged rollout (dry-run-only release first). | Maintainer | standing |
| R2 | Agent commoditization: generic agents answer "why is disk full" well enough without dxcli. Mitigation: MCP mode makes dxcli *the tool the agent uses*. | Maintainer | standing |

---

*Exit gate check (Phase 2): every FR above is verifiable by a single test; non-goals list is non-empty and aggressive. ✔*
