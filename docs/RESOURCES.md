# dxcli — Build Resources & Tooling Guide

> Companion to [ROADMAP.md](ROADMAP.md). Everything referenced by phase, with the *reason* it's on the list. Items marked **UNVERIFIED** must be confirmed current before use — do not trust names/versions from memory, including this document's.

---

## Core libraries (already in use — keep)

| Library | Used for | Notes |
|---|---|---|
| `click` | CLI framework | Stay on 8.x; don't chase majors mid-roadmap |
| `rich` | Terminal output | |
| `textual` | TUI (`dxcli dash`) | Optional-extra candidate later if install weight becomes an issue (DEFERRED ledger) |
| `psutil` | Process/partition data | Cross-platform backbone of attribution |
| `numpy` | Regression/statistics | Heaviest dep; keep an eye on wheel availability for new Python versions |
| `pyyaml` | Policies/config | |

## New dependencies by phase (verify each on PyPI before install)

| Phase | Package | Purpose | Risk notes |
|---|---|---|---|
| 1 | *(none)* | `clean` uses stdlib + existing heal engine | Deliberate: deletion code gets no new deps |
| 2 | *(none)* | GitHub REST via stdlib `urllib.request` | Two endpoints don't justify PyGithub |
| 3 | `mcp` (official Anthropic Python SDK) | MCP server mode | **UNVERIFIED at time of writing** — pin exact version at Phase 3 start; ship as `dxcli[mcp]` extra |
| dev | `pytest`, `pytest-mock`, `black`, `flake8`, `bandit` | Existing quality gates | Already in `[test]` extra |
| dev | `pip-audit` | Dependency CVE scan in CI | Add in Phase 0 |
| dev | `gitleaks` (GitHub Action, not pip) | Secret scanning gate | Pin by SHA |
| dev (optional) | `hypothesis` | Property-based tests for clean-planner path safety | Strong fit for "nothing outside catalog roots ever enters a plan" |

## Platform documentation to have open, by phase

**Phase 0 — release engineering**
- PyPI **Trusted Publishing** guide (OIDC from GitHub Actions) — the no-token publish flow.
- `pypa/gh-action-pypi-publish` action docs.
- GitHub docs: branch protection rules, required status checks.
- ghcr.io: publishing containers from Actions (`GITHUB_TOKEN` `packages: write`).

**Phase 2 — autopsy / Action**
- GitHub REST: *Issues → Comments* endpoints (PR comments are issue comments).
- GitHub Actions docs: `GITHUB_TOKEN` default permissions & the `permissions:` block; *variables and contexts* (`github.event.pull_request.number`, `GITHUB_STEP_SUMMARY`); *metadata syntax for composite actions*; fork-PR token restrictions (`pull_request` vs `pull_request_target` — read the security warnings on the latter carefully; prefer degrading to job summary over using it).
- GitHub Marketplace: publishing an action (public repo, single action.yml at root, release tagging, branding block — already present).
- Comment length limit: 65,536 characters (verify current value when implementing FR-003).

**Phase 3 — MCP**
- modelcontextprotocol.io — protocol spec + Python SDK quickstart (stdio server, tool definitions).
- Claude Code docs: `claude mcp add` registration; Claude Desktop `claude_desktop_config.json` format.
- Existing in-repo starting point: `dxcli/server/` (untracked scaffolding from V4 work) — audit whether it's reusable or should be replaced before building on it.

**Phase 4 — distribution**
- pypistats.org (weekly downloads), GitHub code search (`Seshadri724/dxcli path:.github/workflows`), Marketplace insights tab.
- Submission targets: awesome-actions, awesome-ci, awesome-python, awesome-mcp-servers; dev.to; Show HN guidelines (text of the post matters less than the first comment you leave).

## Tooling for the craft bits

| Need | Tool | Why |
|---|---|---|
| README terminal GIF | `vhs` (charmbracelet) or asciinema+agg | Scriptable = reproducible when output changes |
| Social preview image | Repo settings → social preview; 1280×640 | Star conversion is partly a thumbnail game |
| Local Action testing | `act` (nektos) | Imperfect emulation — final verification always on a real scratch repo |
| Multi-Python local testing | `uv` (`uv run --python 3.8 pytest`) or `tox` | Matrix parity with CI before pushing |
| Windows CI quirks | The existing UTF-8 shims in `cli.py` | Windows runners are where encoding bugs surface; keep matrix green |
| Container build | Docker multi-stage on `python:3.12-slim`, non-root `USER` | See ARCHITECTURE §3 |
| Changelog discipline | Keep a `CHANGELOG.md` section per tag; release workflow reads it | Already have CHANGELOG.md — formalize the per-version headers |

## Reference projects (study the mechanics, not the code)

| Project | Steal this lesson |
|---|---|
| **Codecov / Danger JS** | The PR-comment growth loop: one install → whole team sees output → more installs. Their comment formatting (collapsible sections, deterministic upsert) is the pattern for FR-003/004 |
| **`jlumbroso/free-disk-space`** & `easimon/maximize-build-space` actions | Your closest Action-space neighbors: they *free* space blindly; dxcli *diagnoses*. Their READMEs show what users search for — mine the issue trackers for real pain phrasing |
| **ncdu / dust / dua** | The viewer competition; their GitHub issues asking "why is it growing?" are your marketing copy |
| **ruff** | Gold standard README for a CLI dev tool: benchmark table, GIF, one-line install, badges. Also the counterexample on language choice — don't take the Rust bait in v1 |
| **pre-commit** | How a Python CLI became CI infrastructure without a hosted service |
| **mcp-server-git / other official MCP servers** | Canonical tool-definition style, error handling, and README registration snippets to mirror in `docs/MCP.md` |

## Standing constraints (from PRD — repeated here so they're never "forgotten" in a build session)

1. **Zero telemetry.** No phone-home code enters the tree, period.
2. **No deletion without `--yes`**, no deletion outside heal-engine scoping, no deletion reachable via MCP.
3. **Exit codes and `--json` schemas are public API** — breaking them is a major-version event.
4. **Every new dependency is verified real, maintained, and pinned** before first import (supply-chain gate).
5. **AI-generated code in deletion/token/scoping paths is human-read line-by-line before merge.**
