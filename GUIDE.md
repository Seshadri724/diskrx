# dxcli — the developer guide

The disk doctor for your CI pipeline and dev box. This guide covers everything from a 30-second CI guard to long-running production deployments.

---

## What you'll use it for

- **CI pipelines** — fail fast when a runner is unhealthy instead of failing weird mid-build. See [CI integration](#ci-integration).
- **Docker builds** — diagnose image bloat, dangling cache, and orphan volumes. See [Docker workflows](#docker-workflows).
- **Dev containers and laptops** — find what's eating your home dir without grepping `du -sh *` for an hour. See [Local dev usage](#local-dev-usage).
- **Long-running hosts** — daemon mode, webhook alerts, systemd sandboxing. See [Production deployment](#production-deployment).

---

## Quick start

```bash
pip install dxcli
dxcli ci              # silent on success, exits 1 on critical pressure
dxcli diagnose .      # interactive report on the current dir
dxcli diagnose ~ --classify   # group home-dir usage by category
```

---

## CI integration

The shortest possible drop-in:

```yaml
- name: Disk guard
  run: |
    pip install dxcli
    dxcli ci
```

`dxcli ci` is equivalent to `dxcli diagnose . --ci --docker`. It exits `1` if:

- Disk usage is ≥ 90% on the partition holding the path.
- Any `[CRITICAL]` policy violation is found.

### Why a pre-build guard
Build agents are ephemeral or shared. `No space left on device` mid-build corrupts artifacts, produces cryptic I/O errors, and wastes 30–60 minutes of debugging. A guard step catches the problem in seconds and points at the cause.

### Worked examples
- [GitHub Actions workflow](docs/examples/github-actions.yml)
- [GitLab CI snippet](docs/examples/gitlab-ci.yml)
- [Composite GitHub Action](action.yml) — `uses: Seshadri724/dxcli@v1`
- [Jenkins, full CI playbook](GUIDE_CI.md)

---

## Docker workflows

```bash
dxcli diagnose . --docker
```

Correlates Docker's own bookkeeping (images, containers, volumes, build cache) with system disk pressure and prescribes specific cleanup commands (`docker builder prune`, `docker image prune -a`, …) with the actual bytes each would free.

Use it:
- Before a `docker build` in a tight runner.
- As a post-step on failed builds to attach evidence to a bug report (`--report disk-report.html`).
- Inside a multi-stage build to catch a bloated builder layer — see [docs/examples/Dockerfile](docs/examples/Dockerfile).

---

## Local dev usage

```bash
dxcli diagnose ~ --classify
```

Groups disk usage by category — `node_modules`, Python venvs, build artifacts, caches (pip, npm, yarn, cargo), logs — so you can see at a glance whether it's `~/.cache/pip` or that one `node_modules` from 2024 that's killing you.

Other useful commands on a dev box:

| Command | What it does |
| --- | --- |
| `dxcli diff . --hours 1` | Directories that grew in the last hour. Catches the `npm install` that bloated the disk. |
| `dxcli predict /` | Estimates time-to-full via linear regression on historical snapshots. |
| `dxcli heal <path>` | Applies scoped, reversible cleanup. `dxcli undo` reverts the last one. |
| `dxcli dash` | TUI dashboard with live updates. |

A devcontainer recipe is in [docs/examples/devcontainer.json](docs/examples/devcontainer.json); a git pre-commit hook is in [docs/examples/pre-commit-hook.sh](docs/examples/pre-commit-hook.sh).

---

## Command reference

### `dxcli ci [PATH]`
CI shortcut. Equivalent to `dxcli diagnose PATH --ci --docker`. `--no-docker` skips Docker analysis; `--json` outputs structured results.

### `dxcli diagnose [PATH]`
Deep scan and diagnosis.
- `--ci` — CI mode: exits 1 on critical pressure or policy violations.
- `--docker` — include Docker disk usage.
- `--classify` — group output by semantic category.
- `--report file.html` — write a shareable HTML report.
- `--json` — machine-readable output.
- `--target NAME` — use a named target from `config.yaml`.
- `--enable-plugins` — opt-in to local plugins from `~/.dx/plugins`.

### `dxcli diff [PATH] --hours N`
Show what grew (or shrank) since a past snapshot.

### `dxcli predict [PATH]`
Estimate time-to-full via linear regression on history.

### `dxcli watch [PATH] --interval N --alert-threshold SIZE`
Continuous monitoring. `--webhook URL` posts to Slack/PagerDuty; `--notify-desktop` raises native notifications.

### `dxcli heal [PATH]` / `dxcli undo`
Apply or revert scoped cleanup. Always preview with `--dry-run`.

### `dxcli serve` / `dxcli daemon`
`serve` exports Prometheus metrics; `daemon` runs `watch` or `serve` as a background process.

### `dxcli fleet [HOSTS...]`
Aggregate metrics across hosts.

### `dxcli add-target` / `dxcli generate-service`
Wizards for registering a monitor target and producing a hardened systemd unit.

### `dxcli dash` / `dxcli demo`
TUI dashboard and a synthetic dataset for trying things out.

---

## Production deployment

The same engine that runs in a 60-second CI step also runs as a long-lived process for fleet monitoring.

- **Hardened state directory** — `~/.dx` is locked to `0700`, `history.db` to `0600`.
- **Atomic writes** — state is never left partial across crashes.
- **Systemd sandboxing** — `generate-service` produces a unit with `NoNewPrivileges` and `ProtectSystem=strict`.
- **Plugin opt-in** — community plugins never execute without explicit `--enable-plugins`.
- **Zero-trust healing** — `heal` enforces realpath-based scoping; symlink escapes are rejected.
- **Reversibility** — every `heal` action is recorded; `undo` rolls it back.

Use the same `dxcli ci` pattern for canary jobs on production hosts, or `dxcli daemon start --command serve` to export Prometheus metrics.

---

## Philosophy

1. **Prescription over description** — tell the user what to do, not just what they have.
2. **Attribution is key** — every byte has a parent process. Find it.
3. **Safe remediation** — every automated action must be auditable and reversible.
4. **Fail fast in CI, never fail weird** — exit codes are a feature.

---

## Project evolution log

### Iteration 5: Production hardening
*2026-05-12 — "secure by default"*
- Plugin execution gated behind `--enable-plugins`.
- `HealEngine` enforces realpath-based scoping; symlink escapes blocked.
- Centralized atomic writes via `dxcli/state.py`.
- `0700` / `0600` enforced via a unified state provider.
- Lifecycle hardening for Sentinel and Watch.
- Quality gates: `flake8`, `black`, `bandit`.

### Iteration 4: Attribution and Docker
*2026-05-12*
- Throughput-sampling process mapper (bytes/sec, not just PID lists).
- Docker Analyzer: dangling layers, build cache, estimated savings.
- Named targets / YAML config; `add-target` and `--target`.
- `generate-service` for hardened systemd units.
- Cross-platform desktop notifications.
- `fleet` for multi-host aggregation.

### Iteration 3: Diff engine and shareable reports
*2026-04-24*
- `dxcli diff` against historical snapshots.
- `--alert-threshold` tripwires for `watch`.
- Self-contained HTML reports via `--report`.

### Iteration 2: Foundations
*2026-04-14*
- Parallel BFS scanner.
- YAML policy engine.
- Plugin SDK with sample analyzers.
- Reversible remediation with `undo`.

---

*Updated with every release.*
