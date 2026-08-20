# dxcli — The Complete Developer Guide

> **The disk doctor for your CI pipeline, dev box, and server fleet.**  
> Diagnose what filled the drive, which process did it, fail fast in CI, and safely remediate bloat.

---

## 📑 Table of Contents

- [What You'll Use It For](#what-youll-use-it-for)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Core Workflows](#core-workflows)
  - [1. CI/CD Pre-Build Guard & Autopsy](#1-cicd-pre-build-guard--autopsy)
  - [2. Docker Storage & Bloat Diagnosis](#2-docker-storage--bloat-diagnosis)
  - [3. Local Dev Environment & Laptop Cleanup](#3-local-dev-environment--laptop-cleanup)
  - [4. AI Agent Integration via MCP Server](#4-ai-agent-integration-via-mcp-server)
  - [5. Production Daemon & Prometheus Monitoring](#5-production-daemon--prometheus-monitoring)
  - [6. Multi-Host Fleet Aggregation](#6-multi-host-fleet-aggregation)
- [CLI Command Reference](#cli-command-reference)
- [Exit Code Reference](#exit-code-reference)
- [Security, Sandboxing & Policy Model](#security-sandboxing--policy-model)
- [Changelog & Architecture Highlights](#changelog--architecture-highlights)

---

## What You'll Use It For

- **CI/CD Pipelines**: Fail fast in < 2 seconds when a runner is critically low on disk before starting a 45-minute build. Capture differential baselines and post-mortem autopsy reports with PR comments.
- **Docker Hosts & Runners**: Diagnose image bloat, dangling cache, buildKit storage, and orphan volumes with actionable remediation commands.
- **Dev Machines & Laptops**: Categorize storage into semantic groups (`node_modules`, Python venvs, cargo caches, Docker layers) instead of running `du -sh *` for an hour.
- **AI Coding Agents**: Expose real-time disk diagnostics, file tree telemetry, and process attribution over Model Context Protocol (MCP).
- **Production Servers & Fleets**: Monitor long-running hosts with background daemons, Prometheus metrics, and automated Slack/webhook alerts.

---

## Installation

`dxcli` is distributed on PyPI as [`diskrx`](https://pypi.org/project/diskrx/) and supports Python 3.8+ on Linux, macOS, and Windows. The install name is `diskrx`; the command it installs is `dxcli`.

```bash
# Install core package (installs the `dxcli` command)
pip install diskrx

# Or install with enterprise/server capabilities (FastAPI + Uvicorn)
pip install "diskrx[server]"
```

---

## Quick Start

```bash
# 1. Quick system partition overview
dxcli status

# 2. Deep diagnosis on current workspace
dxcli diagnose .

# 3. Categorized breakdown of your home directory
dxcli diagnose ~ --classify

# 4. CI fast-fail check (silent on healthy, exits 1 on >= 90% disk pressure)
dxcli ci

# 5. Launch the interactive Textual TUI dashboard
dxcli dash
```

---

## Core Workflows

### 1. CI/CD Pre-Build Guard & Autopsy

`dxcli` provides a two-phase workflow for build pipelines:

```bash
# Step 1: Pre-build check (exits 1 if disk is >= 90% full or policies fail)
dxcli ci

# Step 2: Record baseline disk snapshot before compilation/docker builds
dxcli snapshot-baseline --baseline /tmp/dx-baseline.json .

# ... Run your build / tests / docker build ...

# Step 3: Run post-build autopsy to pinpoint exact growth culprits
dxcli autopsy --baseline /tmp/dx-baseline.json --summary .
```

*For complete CI configurations across GitHub Actions, GitLab CI, and Jenkins, see [GUIDE_CI.md](GUIDE_CI.md).*

---

### 2. Docker Storage & Bloat Diagnosis

Correlates Docker's internal engine bookkeeping (images, containers, volumes, build cache) with system disk pressure:

```bash
dxcli diagnose . --docker
```

`dxcli` generates clear prescriptions with exact byte estimations:
- Unused build cache (`docker builder prune`)
- Dangling images (`docker image prune`)
- Stopped containers & unused anonymous volumes

---

### 3. Local Dev Environment & Laptop Cleanup

#### Semantic Classification
Groups disk usage into meaningful developer categories:
```bash
dxcli diagnose ~ --classify
```
Categories detected:
- **Package Managers & Caches**: `npm`, `pip`, `yarn`, `cargo`, `go`, `pnpm`
- **Virtual Environments**: `.venv`, `venv`, `env`, `conda`
- **Dependencies**: `node_modules`, `vendor`
- **Build Artifacts**: `target/`, `dist/`, `build/`, `out/`, `__pycache__`
- **Logs & Dumps**: `*.log`, `*.dump`, `*.core`

#### Growth Diff & Predictions
```bash
# Find directories that grew in the last 2 hours
dxcli diff . --hours 2

# Linear regression time-to-full forecast based on historical snapshots
dxcli predict /

# Human-readable plain English explanation of disk pressure
dxcli explain .
```

#### Safe Cleanup & Reversible Healing
```bash
# Preview safe automated cleanups
dxcli clean --dry-run .

# Apply safe scoped remediation
dxcli heal /tmp --yes

# Rollback the last remediation action if needed
dxcli undo
```

---

### 4. AI Agent Integration via MCP Server

`dxcli` implements the **Model Context Protocol (MCP)**, allowing AI tools (such as
Claude Desktop, Claude Code, or Cursor) to inspect disk health and diagnose bottlenecks.

The server speaks JSON-RPC 2.0 over stdio. Run it directly to check it responds:

```bash
dxcli mcp
```

#### Exposed tools

Five tools, all **read-only** — none of them delete, move, or modify anything:

| Tool | Returns |
| :--- | :--- |
| `disk_status` | Capacity, used bytes, free bytes, usage percent for a mountpoint. |
| `diagnose` | Top storage consumers, logs, stale files, prescriptions. |
| `diff` | Storage growth against a pre-build baseline snapshot. |
| `predict` | Time-to-full forecast and daily growth rate. |
| `clean_preview` | Dry-run cleanup plan; reports reclaimable bytes, deletes nothing. |

`heal`, `clean`, and `undo` are deliberately **not** exposed over MCP. Remediation stays
on the CLI, where a human runs it.

#### Restricting which directories an agent can read

`--allow` takes **directory paths**, and may be repeated. It does not take tool names.
With no `--allow`, the server permits the current working directory and the user's home.

```bash
# Limit the agent to two project trees
dxcli mcp --allow /srv/app --allow /var/log/app
```

Any tool call targeting a path outside the allowed trees returns an `Access denied` error.

#### Connecting a client

Use an **absolute path** to the interpreter. MCP clients start the server in a bare
environment where a virtualenv's `dxcli` script is usually not on `PATH`; the
`-m dxcli` form always resolves.

**Claude Code** — from the project directory:

```bash
claude mcp add dxcli -- /absolute/path/to/.venv/bin/python -m dxcli mcp
```

**Claude Desktop** — edit `claude_desktop_config.json`
(macOS: `~/Library/Application Support/Claude/`, Windows: `%APPDATA%\Claude\`),
then restart the app:

```json
{
  "mcpServers": {
    "dxcli": {
      "command": "/absolute/path/to/.venv/bin/python",
      "args": ["-m", "dxcli", "mcp", "--allow", "/absolute/path/to/your/project"]
    }
  }
}
```

On Windows the command is `C:\\path\\to\\.venv\\Scripts\\python.exe`.

**Cursor** — same `mcpServers` block in `.cursor/mcp.json`.

Once connected, ask the agent things like *"what filled this disk, and which process
did it?"* — it will call `diagnose` and read back the culprit and the owning PID.

---

### 5. Production Daemon & Prometheus Monitoring

Run continuous monitoring with native desktop alerts or webhooks:

```bash
# Foreground watch loop with webhook alert threshold
dxcli watch /var/log --interval 60 --alert-threshold 10G --webhook https://hooks.slack.com/services/...

# Start as background daemon
dxcli daemon start --command watch --target my-app --webhook https://hooks.slack.com/...

# Export Prometheus metrics endpoint on port 8000
dxcli serve --port 8000 --bind 0.0.0.0
```

To generate a hardened, sandboxed systemd service file:
```bash
dxcli generate-service --target my-app --user dxcli > /etc/systemd/system/dxcli.service
```

---

### 6. Multi-Host Fleet Aggregation

Aggregate disk telemetry across multiple remote nodes:

```bash
# Query active fleet nodes
dxcli fleet --hosts worker-1.internal:8000,worker-2.internal:8000

# Push local snapshot to centralized fleet ingest server
dxcli snapshot . --push https://fleet.internal/api/v1/snapshot --token $FLEET_TOKEN --anonymize
```

---

## CLI Command Reference

| Command | Key Flags | Description |
| :--- | :--- | :--- |
| `dxcli status` | *(none)* | Fast overview of all partition mount points, usage %, and free space. |
| `dxcli diagnose [PATH]` | `--ci`, `--docker`, `--classify`, `--report <file.html>`, `--json`, `--threads <N>`, `--nice <N>` | Comprehensive disk scan, process mapping, and rule validation. |
| `dxcli ci [PATH]` | `--no-docker`, `--json` | Fast-fail pre-build guard (alias for `diagnose --ci --docker`). Exits `1` on critical state. |
| `dxcli snapshot-baseline [PATH]`| `--baseline <file.json>`, `--no-docker` | Captures baseline snapshot before CI build steps. |
| `dxcli autopsy [PATH]` | `--baseline <file.json>`, `--format <text\|json\|markdown>`, `--summary`, `--pr-comment` | Diffs post-build usage against baseline and identifies growth culprits. |
| `dxcli clean [PATH]` | `--dry-run`, `--yes/-y`, `--no-docker`, `--json` | Interactive/automated cleaner for stale caches, tmp files, and dangling docker layers. |
| `dxcli heal [PATH]` | `--dry-run`, `--yes/-y` | Applies safe, scoped remediation rules. |
| `dxcli undo` | *(none)* | Reverts the most recent `heal` action using recorded state logs. |
| `dxcli diff [PATH]` | `--hours <N>` | Compares current directory sizes with a previous snapshot from *N* hours ago. |
| `dxcli predict [PATH]` | *(none)* | Forecasts time until partition exhaustion using linear regression on history. |
| `dxcli explain [PATH]` | *(none)* | Generates plain-English narrative of why disk pressure exists. |
| `dxcli watch [PATH]` | `--interval <sec>`, `--alert-threshold <size>`, `--webhook <URL>`, `--notify-desktop` | Continuous monitoring loop with tripwire alerting. |
| `dxcli serve` | `--port <P>`, `--bind <IP>`, `--interval <sec>`, `--auth-token <TOK>` | Starts HTTP/Prometheus metrics exporter. |
| `dxcli daemon <action>` | `start`, `stop`, `status` (`--command watch\|serve`, `--target <name>`) | Background process supervisor for watch/serve. |
| `dxcli fleet [HOSTS...]`| `--port <P>`, `--server <URL>`, `--token <TOK>` | Centralized fleet query and multi-host monitoring dashboard. |
| `dxcli snapshot [PATH]` | `--json`, `--push <URL>`, `--token <TOK>`, `--anonymize` | Ad-hoc snapshot generation and fleet upload. |
| `dxcli add-target` | *(interactive)* | Configures named monitoring target in `~/.dx/config.yaml`. |
| `dxcli generate-service`| `--target <name>`, `--user <username>` | Emits production-ready, sandboxed systemd service definition. |
| `dxcli prune` | `--days <N>` | Purges historical SQLite database records older than *N* days (default: 30). |
| `dxcli plugins` | *(none)* | Lists discovered plugins and trust verification status. |
| `dxcli trust [PATH]` | *(none)* | Computes SHA256 checksum and marks a local plugin as trusted. |
| `dxcli mcp` | `--allow <path>` | Starts read-only Model Context Protocol stdio server for AI agents. Repeat `--allow` to permit more directories. |
| `dxcli dash` | *(none)* | Opens full-screen interactive Textual Terminal User Interface (TUI). |
| `dxcli demo` | *(none)* | Seeds realistic synthetic snapshots for sandbox testing. |

---

## Exit Code Reference

| Exit Code | Constant | Meaning |
| :---: | :--- | :--- |
| `0` | `SUCCESS` | Healthy state. Disk usage < 90% and all policies satisfied. |
| `1` | `CRITICAL_PRESSURE` | Disk usage ≥ 90% or `[CRITICAL]` policy rule breached in CI mode. |
| `2` | `VALIDATION_ERROR` | Invalid CLI arguments, missing baseline file, or bad configuration. |
| `3` | `RUNTIME_ERROR` | Unhandled runtime exception or missing OS dependencies. |
| `4` | `PARTIAL_SCAN` | Scan completed with non-fatal permission or access errors on subdirectories. |

---

## Security, Sandboxing & Policy Model

1. **State Directory Hardening**: `~/.dx` directory permissions are locked to `0700`, and `history.db` is locked to `0600`.
2. **Atomic Writes**: All state, baseline, and configuration files are written using atomic swap operations to prevent corruptions during sudden aborts.
3. **Symlink Escape Protection**: `HealEngine` and `CleanEngine` resolve `realpath` on all targets to prevent path traversal or symlink redirection attacks.
4. **Sandboxed Plugins**: Plugins are disabled by default. Executing plugins requires explicit `--enable-plugins` and cryptographic hash verification via `dxcli trust`.
5. **Declarative Policies**: Create a `dx_policies.yaml` in your workspace root to define custom limits:

```yaml
rules:
  - name: Build Artifact Ceiling
    type: limit
    path: dist/
    max_size_gb: 2
    action: Clean build directory

  - name: Stale Temporary Logs
    type: stale
    path: /tmp
    max_age_days: 3
    action: Safe to delete
```
