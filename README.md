# dxcli — The disk doctor for your CI pipeline and dev box

`dxcli` keeps GitHub Actions runners, dev containers, and Docker builds from running out of disk. It diagnoses *what* filled the drive, *which process* did it, and gives you a one-line fix.

[![PyPI](https://img.shields.io/pypi/v/dxcli.svg)](https://pypi.org/project/dxcli/)
[![Python versions](https://img.shields.io/pypi/pyversions/dxcli.svg)](https://pypi.org/project/dxcli/)
[![Tests](https://github.com/Seshadri724/diskrx/actions/workflows/test.yml/badge.svg)](https://github.com/Seshadri724/diskrx/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Downloads](https://img.shields.io/pypi/dm/dxcli.svg)](https://pypi.org/project/dxcli/)

> `No space left on device` at 87% through a CI build isn't a disk problem — it's a *diagnosis* problem. `dxcli` is the diagnosis.

<!-- DEMO GIF (add before launch):
     The money shot is a red failing CI log → `dxcli ci` → "Primary culprit + one-line fix" in ~15s.
     Record with asciinema (asciinema.org) or termtosvg, export a GIF to docs/assets/demo.gif,
     then uncomment the block below. Until then, the sample output beneath stands in as the visual.

<p align="center">
  <img src="docs/assets/demo.gif" alt="dxcli diagnosing a full CI runner in a single command" width="760">
</p>
-->

---

## What it looks like

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

`du`, `ncdu`, and `dust` show you the bytes. `dxcli` tells you **what filled the disk, which process did it, and how to fix it** — and exits non-zero in CI so your pipeline fails fast instead of failing weird.

---

## Why dxcli?

You've seen these before:

- `No space left on device` halfway through a CI build.
- `Error response from daemon: write /var/lib/docker/...: no space left on device`.
- A dev container that mysteriously crawls after a few weeks of `npm install` cycles.
- A GitHub Actions runner that passes locally and fails in CI because the runner image hit 90% used.

`dxcli` answers the question those errors don't: **now what?**

---

## Quick start

```bash
pip install dxcli
```

### In GitHub Actions (the one-liner)

```yaml
- name: Disk guard
  run: |
    pip install dxcli
    dxcli ci
```

`dxcli ci` is the CI-mode shortcut: silent on success, exits `1` on critical disk pressure or policy violations, and includes Docker analysis automatically.

### Before a `docker build`

```bash
dxcli diagnose . --docker
```

Surfaces dangling images, stale build cache, and the prescriptions to reclaim them (`docker builder prune`, `docker image prune -a`, etc.) — with the actual bytes each would free.

### In your dev container

```bash
dxcli diagnose ~ --classify
```

Groups usage by category (node_modules, Python venvs, build artifacts, cache directories, logs) so you can see at a glance whether it's `~/.cache/pip` or that one `node_modules` from 2024 that's killing you.

---

## Core features

### Exit-code-aware CI mode
`dxcli ci` and `dxcli diagnose --ci` exit `1` on critical thresholds. Drop it in as a pre-build step; your pipeline fails the moment the runner is unhealthy, not 20 minutes later mid-build.

### Docker-aware diagnosis
`--docker` correlates Docker's own disk usage (images, containers, volumes, build cache) with system disk pressure. No more `docker system df` followed by "now what?"

### Process attribution
Most disk tools tell you *which directory* is full. `dxcli` tells you *which process is writing to it right now*, so you can find the runaway test runner or the misconfigured logger.

### Predictive forecasting
Linear regression against historical snapshots — useful for catching slow leaks in long-lived dev environments or shared CI runners before they bite.

### Safe automated cleanup
`dxcli heal <path>` applies scoped, reversible fixes — and `dxcli undo` reverts the last one. No untrusted plugins run by default.

---

## Use it as a GitHub Action

```yaml
- uses: Seshadri724/diskrx@v1
  with:
    path: .
    fail-on-critical: true
    docker: true
```

See [action.yml](https://github.com/Seshadri724/diskrx/blob/master/action.yml) for all inputs.

---

## Common recipes

### Fail a PR if the build leaves behind > 1 GB of junk
```yaml
- run: dxcli diagnose ./build --ci
```

### Catch the `npm install` that bloated the runner
```bash
dxcli diff . --hours 1
```
Shows directories that grew in the last hour, ranked.

### Find what to delete in your home dir
```bash
dxcli diagnose ~ --classify
```

### Make a one-page HTML report you can attach to a bug
```bash
dxcli diagnose / --report disk-report.html
```

---

## Production / SRE use

`dxcli` also runs unattended as a systemd service for fleet-wide monitoring (`dxcli daemon`, `dxcli serve`, webhook alerts, hardened sandboxing) — the same engine, just configured for long-running hosts.

---

## Installation

```bash
pip install dxcli
```

Requires Python 3.8+. CI covers CPython 3.8–3.12 on Linux, plus 3.12 on macOS and Windows. No telemetry, no network calls unless you configure webhooks. Docker analysis requires a reachable Docker socket.

---

## Contributing

```bash
git clone https://github.com/Seshadri724/diskrx
cd diskrx
python -m venv venv
# Windows: venv\Scripts\activate
# Linux/macOS: source venv/bin/activate
pip install -e ".[test]"

black --check dxcli tests
flake8 dxcli tests
bandit -r dxcli -q -ll
pytest
```

Issues and PRs welcome at <https://github.com/Seshadri724/diskrx/issues>.

---

## License

MIT — see [LICENSE](https://github.com/Seshadri724/diskrx/blob/master/LICENSE).

<p align="center">
  Built so your CI build doesn't die at 87%.
</p>
