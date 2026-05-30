# 🩺 dxcli — The Super Awesome Forever Guide

Welcome to the definitive living manual for **dxcli**, the world's first **Disk Intelligence** platform. This document is a sacred record of our journey from a simple diagnostic script to a category-defining infrastructure powerhouse.

---

## 🚀 The Vision

`dxcli` is not a tool; it's a **Standard**. Our goal is to own the "Standard Unit of Disk Awareness." We don't just show data; we give orders. In the "Storage Crisis" of the modern cloud, `dxcli` is the decision engine that saves SREs 45 minutes of 2 AM investigation.

---

## 🏗️ Core Architecture: The Six Pillars

1.  **Collectors**: The hands. High-speed parallel scanning of the filesystem and process space.
2.  **Analyzers**: The brain. Linear regression, anomaly detection, and community-driven plugin logic.
3.  **Policy Engine**: The law. Declarative "Disk Policy as Code" (YAML) for fleet-wide governance.
4.  **Plugin SDK**: The heart. A Shopify-style ecosystem allowing anyone to build stack-specific intelligence.
5.  **Heal Engine**: The surgeon. Opinionated remediation with "Sleep Insurance" remittance reports.
6.  **Outputs**: The voice. One-screen diagnostic clarity, shareable HTML reports, and Prometheus-compatible sentinels.

---

## 🛠️ The Toolkit (Command Reference)

### `dxcli diagnose [PATH]`
The category leader. Scans a path, enforces policies, runs plugins, and returns a "Prescription-First" report.
- `--json`: Outputs pure JSON for automation.
- `--enable-plugins`: **Opt-in** to run community analyzer plugins securely.
- `--report [file.html]`: Generates a beautiful, self-contained HTML report.
- `--docker`: Runs the Docker Analyzer for actionable cleanup commands.
- `--ci`: **The Enterprise Wedge.** Pipeline mode for CI/CD failures.
- `--classify`: **Semantic Grouping.** Group disk usage by content type.
- `--target [NAME]`: Use a named target from `config.yaml`.

### `dxcli watch [PATH] --interval [N] --alert-threshold [SIZE]`
The tripwire. Continuously monitors a directory for growth anomalies.
- `--webhook [URL]`: Notify Slack/PagerDuty on threshold breach.
- `--notify-desktop`: **Proactive Alerting.** Native desktop notifications.
- `--target [NAME]`: Load settings from a saved target.

### `dxcli daemon [start|stop|status] --command [CMD]`
The ghost. Runs `watch` or `serve` as a background process.

### `dxcli fleet [HOSTS...]`
The aggregator. Multi-server health dashboard.

### `dxcli add-target`
The onboarding wizard. Interactively register a monitor target.

### `dxcli heal [PATH]`
The stabilizer. Applies prescriptions and provides a Sleep Insurance report. *(Always use `--dry-run` to preview changes!)*

### `dxcli undo`
The reset button. Reverts remediation actions using the audit stack.

### `dxcli dash` & `dxcli serve`
The grid. `dash` opens the TUI workstation, while `serve` exports real-time metrics for global observability (Prometheus/Grafana).

### `dxcli demo`
The hero maker. Seeds 7 days of synthetic growth history and immediately runs a diagnostic to showcase predictive capabilities.

---

## 🛡️ The Four Trust Pillars

SREs don't trust marketing; they trust behavior. `dxcli` is built on these four unshakeable pillars:

1.  **🔍 Radical Transparency**: Zero telemetry. Data stays on your machine in `~/.dx/history.db` with **0600 permissions**.
2.  **🛡️ Production Hardening**: Built-in support for systemd sandboxing (`NoNewPrivileges`, `ProtectSystem=strict`). Use `generate-service` to deploy with zero-trust defaults.
3.  **🔧 Workflow Integration**: Composable outputs (JSON/HTML), standard exit codes, and Prometheus-compatible metrics out of the box.
4.  **📊 Evidence over Claims**: Every "Prescription" is backed by attribution data. Every action is reversible with `dxcli undo`.

---

## 📜 The Forever Log: Project Evolution

### Iteration 5: Production Hardening (The Fortress Phase)
*2026-05-12*
> "Secure by Default"

**Achievements:**
- ✅ **Plugin Opt-In**: Community plugins are now physically impossible to run without explicit `--enable-plugins` consent, mitigating supply-chain risks.
- ✅ **Zero-Trust Healing**: `HealEngine` strictly validates target paths against the scanned scope using realpath resolution, blocking all symlink escape vectors.
- ✅ **Atomic Persistence**: Extracted `dxcli/state.py` to implement centralized, atomic file writes. State is never left in a partial or corruptible condition.
- ✅ **Strict OS Hygiene**: Enforced `0700` and `0600` permissions via a unified state provider.
- ✅ **Lifecycle Safety**: Fortified long-running processes (Sentinel, Watch) with robust exception handling and deterministic resource cleanup.
- ✅ **Quality Gates**: Dev workflow standardized with `flake8`, `black`, and `bandit` for automated security linting.

### Iteration 4: The Viral Enterprise
*2026-05-12*
> "From Utility to Infrastructure"

**Achievements:**
- ✅ **Smarter Attribution**: Process mapping now correlates historical deltas with live PIDs and **throughput sampling** (Bytes/sec).
- ✅ **The Ultimate Bro Feature**: Docker Analyzer identifies dangling layers and build cache with estimated savings.
- ✅ **Named Targets & Config**: Migrated to YAML configuration with `add-target` and `--target` support for reduced CLI friction.
- ✅ **Production Hardening**: Enforced 0700/0600 file permissions and added `generate-service` for hardened systemd deployment.
- ✅ **Cross-Platform Alerts**: Native desktop notifications added for Windows, macOS, and Linux.
- ✅ **Fleet Mode**: Added `fleet` command for multi-server metric aggregation.

### Iteration 3: The Moat Features & Strategic Reality
*2026-04-24*
> "Building the Defensible Category"

**Achievements:**
- ✅ **The Diff Engine**: Implemented `dxcli diff` to query historical DB snapshots and show growth deltas.
- ✅ **Threshold Watcher**: Added `--alert-threshold` tripwires to catch anomalies in real-time.
- ✅ **Shareable Intelligence**: Built self-contained HTML report generation (`diagnose --report`).
- ✅ **Strategic Shift**: Reoriented from "speed" to "intelligence/trust" based on brutal market feedback. Focus shifted to BSL licensing and niche domination.

### Iteration 2: The Billionaire Sprints
*2026-04-14*
> "Creating the Disk Intelligence Category"

**Achievements:**
- ✅ **Standardization**: Rebranded and refactored for monopoly-level clarity.
- ✅ **Dyson Scanner**: Physically impossible speed achieved via parallel BFS.
- ✅ **Policy as Code**: YAML-driven disk governance implemented.
- ✅ **Plugin SDK**: Shopify-style ecosystem launched with sample analyzers.
- ✅ **Sleep Insurance**: Remediation reports designed for SRE peace of mind.

---

## 🧠 Developer Philosophy
- **Speed is Physics**: If it's slow, it's broken.
- **One Screen, One Action**: Ruthless clarity over data volume.
- **Category over Tool**: We are building the standard word for disk.
- **Transparency is a Moat**: Iterating in public, open handbook.

---

*(This guide is updated with every release. Keep it close.)*
