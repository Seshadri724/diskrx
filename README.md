# dxcli — The disk doctor for your CI pipeline and dev box

`dxcli` keeps GitHub Actions runners, dev containers, and Docker builds from running out of disk. It diagnoses *what* filled the drive, *which process* did it, and gives you a one-line fix.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![PyPI](https://img.shields.io/pypi/v/dxcli.svg)](https://pypi.org/project/dxcli/)

---

## Why dxcli?

You've seen these before:

- `No space left on device` halfway through a CI build.
- `Error response from daemon: write /var/lib/docker/...: no space left on device`.
- A dev container that mysteriously crawls after a few weeks of `npm install` cycles.
- A GitHub Actions runner that passes locally and fails in CI because the runner image hit 90% used.

`du`, `ncdu`, and `dust` show you the bytes. `dxcli` tells you **what filled the disk, which process did it, and how to fix it** — and exits non-zero in CI when something is wrong, so your pipeline fails fast instead of failing weird.

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
- uses: Seshadri724/dxcli@v1
  with:
    path: .
    fail-on-critical: true
    docker: true
```

See [action.yml](action.yml) for all inputs.

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

`dxcli` also runs unattended as a systemd service for fleet-wide monitoring (`dxcli daemon`, `dxcli serve`, webhook alerts, hardened sandboxing). See [GUIDE.md](GUIDE.md) for the production playbook — the same engine, just configured for long-running hosts.

---

## Installation

```bash
pip install dxcli
```

Requires Python 3.8+. Works on Linux, macOS, and Windows. Docker analysis requires a reachable Docker socket.

---

## Contributing

```bash
git clone https://github.com/Seshadri724/dxcli
cd dxcli
python -m venv venv
# Windows: venv\Scripts\activate
# Linux/macOS: source venv/bin/activate
pip install -e ".[test]"

black dxcli
flake8 dxcli
bandit -r dxcli
pytest
```

Issues and PRs welcome at <https://github.com/Seshadri724/dxcli/issues>.

---

## License

MIT — see [LICENSE](LICENSE).

<p align="center">
  Built so your CI build doesn't die at 87%.
</p>
