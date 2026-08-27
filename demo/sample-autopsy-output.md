# 🔍 dxcli CI Storage Autopsy Report

**Execution Status**: ⚠️ Storage Growth Warning  
**Target Path**: `/home/runner/work/backend/backend`  
**Total Build Growth**: **+16.42 GB** (Runner storage increased from 33.3% to 53.7%)  
**Autopsy Confidence**: **98.4% (High)**

---

## 🎯 Primary Culprit Identified

> **Probable Cause:** Multi-stage Docker image layer caching and dangling BuildKit layers consumed **14.80 GB** during `docker build`.

| Attribute | Value |
|---|---|
| **Culprit Path** | `/var/lib/docker/overlay2` |
| **Growth Delta** | `+14.80 GB` (from 2.15 GB to 16.95 GB) |
| **Active Writer** | `buildkitd` (pid `2043`) |
| **Layer Category** | `docker_build_cache` |

---

## 📊 Top Storage Consumers (Growth Diff)

| Directory Path | Baseline Size | Post-Build Size | Delta Growth | % of Total Growth |
|---|---|---|---|---|
| `/var/lib/docker/overlay2` | `2.15 GB` | `16.95 GB` | **+14.80 GB** | 90.1% |
| `~/.cache/pip` | `209.7 MB` | `1.59 GB` | **+1.38 GB** | 8.4% |
| `./dist/build_output` | `0 B` | `240.0 MB` | **+240.0 MB` | 1.4% |
| `./logs/integration_test.log` | `0 B` | `18.5 MB` | **+18.5 MB** | 0.1% |

---

## 🐳 Docker Subsystem Diff

| Subsystem Component | Baseline | Post-Build | Growth Delta | Reclaimable |
|---|---|---|---|---|
| **BuildKit Cache** | 536.8 MB | 12.80 GB | **+12.26 GB** | `12.26 GB (100%)` |
| **Images** | 1.07 GB | 3.61 GB | **+2.54 GB** | `1.85 GB (51%)` |
| **Containers** | 104.8 MB | 104.8 MB | `0 B` | `0 B` |
| **Volumes** | 0 B | 0 B | `0 B` | `0 B` |

---

## 💡 Prescribed Remediations for CI Workflow

Add the following step before caching or at the end of the test job:

```yaml
- name: Clean BuildKit Caches
  if: always()
  run: |
    # Safe: Reclaims ~12.26 GB without breaking subsequent jobs
    docker builder prune -f --filter "until=24h"
    # Safe: Reclaims ~1.85 GB of dangling intermediate images
    docker image prune -f
```

---
*Report generated automatically by `dxcli autopsy` (diskrx v0.3.2)*
