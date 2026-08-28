# dxcli CI Disk Autopsy Demo

This demo illustrates how `dxcli` pinpoints the exact cause of `"No space left on device"` errors on Docker-heavy CI/CD runners in seconds.

---

## 🎬 4-Step Interactive Walkthrough

### 1. Pre-Build: Capture Baseline Snapshot
Before your CI workflow begins compiling or pulling containers, capture a pre-build snapshot:

```bash
dxcli snapshot-baseline . --output .dxcli-baseline.json --docker
```
*Creates `.dxcli-baseline.json` recording directory byte trees and Docker layer allocations in < 1.5 seconds.*

---

### 2. Simulated Build & Disk Spike
Simulate a runaway Docker BuildKit build or large cache generation:

```bash
# Example: build a reproducible Docker workload
docker build -t myapp:integration -f Dockerfile.test .
```

---

### 3. Post-Build: Run Storage Autopsy
Run the autopsy in your `always()` cleanup step or upon build failure:

```bash
dxcli autopsy . --baseline .dxcli-baseline.json --docker --fail-on-growth 15GB
```

---

### 4. Output: Instant Diagnosis & Prescribed Fix
`dxcli` compares the pre-build baseline with the current runner state, outputting a clear diagnostic autopsy:

```markdown
🔍 dxcli CI Storage Autopsy Report

> The values below are illustrative sample output, not production accuracy measurements.

Probable Cause: Docker BuildKit cache layer accumulation (+14.80 GB)
Total Build Growth: +16.42 GB (Runner reached 94% capacity)
Autopsy Confidence: 98.4%

📈 Top Storage Consumers (Growth During Build):
- /var/lib/docker/overlay2: +14.80 GB (from 2.15 GB -> 16.95 GB)
- ~/.cache/pip:            +1.38 GB  (from 209 MB -> 1.59 GB)
- ./dist/build_output:     +240 MB   (from 0 B -> 240 MB)

💡 Prescribed CI Fix:
docker builder prune -f --filter "until=24h" # Reclaims 12.26 GB
```

---

## 📁 Demo Files in this Directory

- [`sample-baseline.json`](sample-baseline.json) — Pre-build baseline JSON artifact.
- [`sample-autopsy-output.md`](sample-autopsy-output.md) — Rendered markdown PR summary output.
- [`../examples/github-actions-disk-autopsy.yml`](../examples/github-actions-disk-autopsy.yml) — Production-ready GitHub Actions workflow file.
