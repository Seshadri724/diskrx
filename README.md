# dxcli — The Disk Doctor for Your CI Pipeline, Dev Box, and Servers

`dxcli` keeps GitHub Actions runners, dev containers, Docker builds, and server fleets from crashing due to disk exhaustion. It diagnoses **what** filled the drive, **which process** did it, forecasts time-to-full, and gives you actionable, reversible fixes.

[![PyPI](https://img.shields.io/pypi/v/diskrx.svg)](https://pypi.org/project/diskrx/)
[![Tests](https://github.com/Seshadri724/diskrx/actions/workflows/test.yml/badge.svg)](https://github.com/Seshadri724/diskrx/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> *"No space left on device at minute 45 of a 50-minute CI build isn't a disk problem — it's a diagnosis problem."*

---

## ⚡ What It Looks Like

```console
$ dxcli diagnose . --docker

  DISK INTELLIGENCE REPORT  ────────────────────────────────────
  Partition: /            92%  ██████████████████░░  38.1 GB free
  Full in ~6 days at current growth (±1.5 days, high variance)

  ● Primary Culprit:  /var/lib/docker/overlay2   14.2 GB
    Written by:       buildkitd (pid 2043, writing now)

  Prescriptions
    [safe]   docker builder prune -f            reclaims ~9.1 GB
    [safe]   docker image prune -a              reclaims ~3.4 GB
    [review] rm -rf ./build/.cache              reclaims ~1.2 GB

  Exit: 1  (critical: partition >= 90% used)
```

Tools like `du` and `ncdu` show you where bytes live. `dxcli` tells you **what caused the pressure, which process is writing to it right now, and how to fix it** — with exit codes specifically tailored for CI/CD fail-fast pipelines.

---

## 🚀 Quick Start

> **Install name vs. command name:** the package installs from PyPI as **`diskrx`**, and provides the **`dxcli`** command.

```bash
# Install via pip
pip install diskrx

# 1. Check system partition health
dxcli status

# 2. Fast-fail CI check (silent on success, exits 1 on >= 90% pressure)
dxcli ci

# 3. Categorize developer disk usage in home directory
dxcli diagnose ~ --classify

# 4. Launch interactive terminal TUI dashboard
dxcli dash
```

---

## 🔑 Key Capabilities

### 1. Two-Phase CI/CD Guard & Autopsy
- **Phase 1 (Pre-Build Guard)**: Fail fast in < 2 seconds if a runner is already starved of disk (`dxcli ci`).
- **Phase 2 (Post-Build Autopsy)**: Compare against a pre-build baseline (`dxcli snapshot-baseline`) to pinpoint exact directories or Docker layers that grew during the build (`dxcli autopsy`).
- **Rich CI Integration**: Automatically renders markdown summaries into `$GITHUB_STEP_SUMMARY` and posts PR comments.

### 2. Docker Storage & BuildKit Diagnosis
- Correlates Docker internal objects (images, containers, anonymous volumes, BuildKit cache) with system disk metrics.
- Surfaces actionable commands with exact byte-reclamation estimates.

### 3. Active Process Attribution & IO Mapping
- Uses throughput sampling and open file handle inspection to identify which active processes (`pid`, process name, command line) are writing to bloated paths.

### 4. Semantic Storage Classification
- Automatically aggregates unorganized directories into intuitive developer categories:
  - `node_modules` & dependency trees
  - Python virtual environments (`.venv`, `conda`)
  - Package manager caches (`pip`, `npm`, `yarn`, `cargo`, `pnpm`)
  - Build targets (`dist/`, `build/`, `target/`)
  - System and application logs

### 5. Safe & Reversible Remediation
- `dxcli clean` previews and purges stale caches, build bloat, and orphaned containers.
- `dxcli heal` applies deterministic remediation policies with strict realpath scoping to prevent symlink traversal attacks.
- `dxcli undo` rolls back the previous cleanup action.

### 6. AI Agent Integration (MCP Protocol)
- Ships with a native **Model Context Protocol (MCP)** server (`dxcli mcp`).
- Lets AI coding assistants (Claude Desktop, Claude Code, Cursor) inspect storage diagnostics: `disk_status`, `diagnose`, `diff`, `predict`, and `clean_preview`.
- **Read-only by design** — no MCP tool deletes or modifies anything, and `--allow <path>` restricts which directories an agent may read. Remediation (`heal`, `clean`, `undo`) stays on the CLI.
- Setup: `claude mcp add dxcli -- python -m dxcli mcp`, or see [GUIDE.md](https://github.com/Seshadri724/diskrx/blob/master/GUIDE.md) for Claude Desktop and Cursor config.

### 7. Production Fleet & Prometheus Monitoring
- Run as a background daemon (`dxcli daemon start`).
- Expose Prometheus metrics endpoint (`dxcli serve --port 8000`).
- Generate hardened, sandboxed systemd service units (`dxcli generate-service`).
- Query and aggregate multi-host clusters (`dxcli fleet`).

---

## 🐙 GitHub Action Usage

Drop the official composite action into your `.github/workflows/`:

```yaml
name: Build with Disk Guard & Autopsy

on: [push, pull_request]

jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write # For automated PR comments

    steps:
      - uses: actions/checkout@v4

      # 1. Pre-build check & baseline snapshot
      - name: Disk Baseline
        uses: Seshadri724/diskrx@v1
        with:
          mode: "snapshot-baseline"
          baseline-file: "baseline.json"
          docker: "true"

      # 2. Main Build Step
      - name: Run Build
        run: |
          docker build -t my-app:latest .
          npm test

      # 3. Post-build growth autopsy (runs even on failure)
      - name: Disk Growth Autopsy
        if: always()
        uses: Seshadri724/diskrx@v1
        with:
          mode: "autopsy"
          baseline-file: "baseline.json"
          summary: "true"
          pr-comment: "true"
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

---

## 🛠️ CLI Cheatsheet

| Command | Purpose |
| :--- | :--- |
| `dxcli status` | Quick summary of mounted partition usage and free space. |
| `dxcli diagnose [PATH] --docker` | Comprehensive diagnostic scan including Docker container & cache analysis. |
| `dxcli ci [PATH]` | CI fast-fail guard. Exits `1` on critical disk pressure or policy breach. |
| `dxcli snapshot-baseline [PATH]` | Records baseline snapshot for CI differential growth tracking. |
| `dxcli autopsy [PATH]` | Diffs usage against baseline and identifies growth culprits. |
| `dxcli clean [PATH] --dry-run` | Previews safe, automated cleanup actions. |
| `dxcli heal [PATH] -y` | Applies policy-based remediation actions. |
| `dxcli undo` | Rolls back the last applied `heal` remediation. |
| `dxcli diff [PATH] --hours 2` | Highlights directories that grew over the past 2 hours. |
| `dxcli predict [PATH]` | Forecasts time until partition exhaustion using linear regression. |
| `dxcli explain [PATH]` | Provides a human-readable narrative of disk pressure causes. |
| `dxcli watch [PATH] --webhook URL`| Continuous monitoring loop with tripwire webhook alerting. |
| `dxcli serve --port 8000` | Exposes HTTP and Prometheus metrics endpoint. |
| `dxcli mcp` | Starts Model Context Protocol stdio server for AI agents. |
| `dxcli dash` | Full-screen interactive Textual TUI dashboard. |

---

## 🔒 Policy as Code (`dx_policies.yaml`)

Define deterministic storage rules in `dx_policies.yaml` at your repository root:

```yaml
rules:
  - name: Limit Build Artifacts
    type: limit
    path: dist/
    max_size_gb: 2
    action: Clean build directory

  - name: Purge Old Test Fixtures
    type: stale
    path: tmp/
    max_age_days: 3
    action: Safe to delete
```

---

## 📖 Documentation

- **[Developer Guide (GUIDE.md)](https://github.com/Seshadri724/diskrx/blob/master/GUIDE.md)** — In-depth architectural guide, all commands, flags, and production setups.
- **[CI/CD Playbook (GUIDE_CI.md)](https://github.com/Seshadri724/diskrx/blob/master/GUIDE_CI.md)** — Full integration examples for GitHub Actions, GitLab CI, Jenkins, Bitbucket, and Azure DevOps.

---

## 🧪 Development & Testing

```bash
# Clone the repository
git clone https://github.com/Seshadri724/diskrx
cd diskrx

# Create and activate virtual environment
python -m venv .venv
# Windows: .\.venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate

# Install development dependencies
pip install -e ".[test,server]"

# Run quality checks and unit tests
black --check dxcli tests
flake8 dxcli tests
bandit -r dxcli -q -ll
pytest
```

---

## 📄 License

Distributed under the [MIT License](https://github.com/Seshadri724/diskrx/blob/master/LICENSE).
