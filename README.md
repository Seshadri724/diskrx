# dxcli — The Disk Doctor 🩺

`dxcli` is a diagnostic tool for SREs and system administrators. It doesn't just show you what is taking up space—it helps you understand **why** your disk is filling up, **who** (which process) is responsible, and **how** to fix it.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## Why dxcli?

Standard tools like `du`, `ncdu`, or `dust` are excellent "viewers." They show you the current state of your disk. `dxcli` is a **decision engine**. It adds an intelligence layer that:

1.  **Attributes Growth**: Correlates growing directories with active processes (PIDs).
2.  **Predicts Time-to-Full**: Uses historical data and linear regression to forecast when a disk will be exhausted.
3.  **Detects Anomalies**: Identifies "log bombs" and persistent leaks using behavioral fingerprinting.
4.  **Prescribes Remediation**: Generates actionable fixes (like logrotate configs) with an automated "Heal Engine" and full undo support.

---

## Core Features

### 🩺 Intelligent Diagnosis
Attributes disk growth to specific processes. No more guessing which microservice is filling up the drive.
```bash
dxcli diagnose /var
```

### 📈 Predictive Forecasting
Learns your server's "metabolism" over time to predict exactly when you'll run out of space.
```bash
dxcli predict /
```

### 🩹 Automated Healing
Apply "prescriptions" to fix known issues. `dxcli` can generate logrotate configs or clean up stale files safely.
```bash
dxcli heal /var/log
```

### 🛡️ Sentinel Analysis
Background monitoring that alerts you to sudden spikes (log bombs) or slow, steady leaks.

---

## Installation

```bash
pip install diskrx
```

Requires Python 3.10+.

---

## Development & Philosophy

`dxcli` is built on three first principles:
1.  **Prescription Over Description**: Tell the user what to do, don't just show them bytes.
2.  **Attribution is Key**: Every byte has a parent process. Find it.
3.  **Safe Remediation**: Every automated action must be auditable and reversible (`dxcli undo`).

---

## Contributing

Contributions are welcome. 

```bash
git clone https://github.com/Seshadri724/dxcli
cd dxcli
python -m venv venv
# On Windows: venv\Scripts\activate
# On Linux: source venv/bin/activate
pip install -e ".[test]"
pytest
```

---

## License

MIT — see [LICENSE](LICENSE) for details.

<p align="center">
  Built for SREs who want their sleep back.
</p>