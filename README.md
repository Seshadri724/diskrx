# 🩺 dxcli — The Disk Doctor

> **Stop firefighting. Start predicting.**  
> Replace your 45-minute disk investigation with a 30-second diagnosis.

[![PyPI version](https://img.shields.io/pypi/v/diskrx.svg)](https://pypi.org/project/diskrx/)
[![Python](https://img.shields.io/pypi/pyversions/diskrx.svg)](https://pypi.org/project/diskrx/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)


---

## The Problem

It's 2 AM. PagerDuty fires. Your production server is at 98% disk.

You SSH in and start the ritual:

```bash
df -h          # okay, it's /var
du -sh /var/*  # narrowing down...
du -sh /var/log/* | sort -h  # getting warmer...
find /var/log -size +100M    # which file?
lsof | grep deleted          # which process?!
```

**45 minutes later**, you've found the culprit — a runaway log file from a service nobody knew was deployed. You delete it, go back to sleep, and it happens again next week.

**There is a better way.**

---

## The Solution

```bash
dxcli diagnose /var
```

```
🩺 Disk Doctor — Diagnosis Report
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🚨 LOG BOMB DETECTED
   /var/log/payments/transaction.log — 14.2 GB
   ↳ Written by: payments-service (PID 18423)
   ↳ Last rotation: Never
   ↳ Prescription: Add logrotate config immediately

⚠️  STALE DATA
   /var/cache/thumbnails — 8.7 GB
   ↳ Last accessed: 94 days ago
   ↳ Prescription: Safe to archive or delete

📈 GROWTH FORECAST
   At current rate, /var fills in 6 hours 12 minutes
   Growth is ACCELERATING (+340% vs last week)
```

**30 seconds. Exact culprit. Exact prescription.**

---

## Features

### 🔍 `dxcli diagnose` — Intelligent Diagnosis
Not just file sizes. It tells you **why** your disk is filling:
- **Log Bomb detection** — unrotated logs growing out of control
- **Stale file identification** — large files untouched for months
- **Process attribution** — exactly which PID is writing to a path

### 📈 `dxcli predict` — Time-to-Full Forecasting
Linear regression on historical snapshots stored locally. Tells you:
- When your disk will be full (hours, days, weeks)
- Whether growth is stable or **accelerating**
- Which directories are the fastest-growing threats

### 🖥️ `dxcli dash` — Real-time TUI Dashboard
A full terminal UI with live sparklines, anomaly alerts, and interactive process maps. No browser required.

```
┌─ Disk Overview ─────────────────────────────────┐
│ /var    [████████████████████░░░░] 84%  ↑ FAST  │
│ /home   [████████░░░░░░░░░░░░░░░░] 34%  → STABLE│
│ /tmp    [███░░░░░░░░░░░░░░░░░░░░░] 12%  ↓ SLOW  │
│                                                  │
│ 🚨 ANOMALY: Log Bomb in /var/log/payments        │
└──────────────────────────────────────────────────┘
```

### 🔭 `dxcli serve` — The Sentinel (Prometheus-compatible)
Run as a background daemon. Exports `/metrics` for Grafana integration. Plug dxcli's intelligence directly into your existing observability stack.

---

## Installation

```bash
pip install diskrx
```

That's it. No config files. No daemons required to get started.

---

## Quickstart

```bash
# Diagnose a path right now
dxcli diagnose /var

# Predict when your root partition fills up
dxcli predict /

# Open the live TUI dashboard
dxcli dash

# Start the Prometheus metrics server
dxcli serve --port 8000
```

---

## How It Works

dxcli stores lightweight disk snapshots in a local SQLite database (`~/.dx/history.db`). Over time, it builds a picture of your disk's growth patterns and uses linear regression to forecast the future.

```
┌─────────────────────────────────────────────────────────┐
│                    dxcli Architecture                   │
├──────────────┬──────────────┬────────────┬─────────────┤
│  collectors/ │  analyzers/  │   store/   │  outputs/   │
│              │              │            │             │
│  Raw OS data │  The "Brain" │  SQLite DB │  Rich / TUI │
│  psutil      │  Growth rate │  Snapshots │  Prometheus │
│  File scans  │  Anomaly     │  History   │  HTTP API   │
│  PID mapping │  detection   │            │             │
└──────────────┴──────────────┴────────────┴─────────────┘
```

---

## Who This Is For

- **SREs** who are tired of getting paged for disk full alerts they could have predicted
- **DevOps engineers** who want disk intelligence in their Grafana dashboards
- **Platform engineers** who need to attribute storage costs to specific services
- **Anyone** who has typed `du -sh * | sort -h` more than once this month

---

## Integrations

**Grafana / Prometheus**

Add to your `prometheus.yml`:
```yaml
scrape_configs:
  - job_name: 'diskrx'
    static_configs:
      - targets: ['localhost:8000']
```



---

Have a feature request? [Open an issue](https://github.com/Seshadri724/dxcli/issues).

---

## Contributing

Contributions are welcome. Please read the contributing guide before submitting a PR.

```bash
git clone https://github.com/Seshadri724/diskrx
cd dxcli
python -m venv venv && source venv/bin/activate
pip install -e ".[test]"
pytest tests/ -v
```

---

## License

MIT — see [LICENSE](LICENSE) for details.

---

<p align="center">
  Built for SREs, by someone who got paged one too many times at 2 AM.
</p>