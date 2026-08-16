# 🚀 dxcli CI/CD Integration Guide

> **Stop "No Space Left on Device" crashes before they break your builds.**  
> Pre-build disk guards, two-phase autopsy reports, Docker layer attribution, and automated PR summaries.

---

## 📑 Table of Contents

- [The CI Disk Problem](#the-ci-disk-problem)
- [The Two-Phase CI Strategy](#the-two-phase-ci-strategy)
- [Official GitHub Action (Recommended)](#official-github-action-recommended)
- [Platform Integration Examples](#platform-integration-examples)
  - [GitHub Actions (Direct CLI)](#github-actions-direct-cli)
  - [GitLab CI](#gitlab-ci)
  - [Jenkins (Declarative Pipeline)](#jenkins-declarative-pipeline)
  - [CircleCI](#circleci)
  - [Bitbucket Pipelines](#bitbucket-pipelines)
  - [Azure DevOps Pipelines](#azure-devops-pipelines)
- [Docker Storage Optimization in CI](#docker-storage-optimization-in-ci)
- [Policy as Code (`dx_policies.yaml`)](#policy-as-code-dx_policiesyaml)
- [Exit Code Matrix](#exit-code-matrix)
- [Post-Build Automated Cleanup](#post-build-automated-cleanup)

---

## The CI Disk Problem

Modern CI runners (GitHub Actions, GitLab Runners, Jenkins nodes, Kubernetes agents) frequently encounter disk exhaustion due to:
1. **Shared or Persistent Runner Bloat**: Orphaned docker build caches, leftover test databases, and untracked caches from previous jobs.
2. **Layer Explosion**: Monolithic Docker builds or multi-stage builds that fail to prune intermediate builder layers.
3. **Silent I/O Corruption**: Running out of space at minute 45 of a 50-minute matrix build, producing cryptic compiler crashes and wasted runner minutes.

`dxcli` solves this with a **fast-fail pre-build guard** (< 2 seconds) and an **actionable post-build autopsy**.

---

## The Two-Phase CI Strategy

```
┌────────────────────────┐
│  1. Pre-Build Guard   │ ──► `dxcli ci` (Exits 1 if >= 90% full or policy breach)
│  (Instant Fast-Fail)   │
└───────────┬────────────┘
            │
            ▼
┌────────────────────────┐
│  2. Snapshot Baseline  │ ──► `dxcli snapshot-baseline --baseline /tmp/base.json`
└───────────┬────────────┘
            │
            ▼
┌────────────────────────┐
│  3. Execute Build/Test │ ──► `npm run build` / `docker build` / `pytest`
└───────────┬────────────┘
            │
            ▼
┌────────────────────────┐
│  4. Post-Build Autopsy │ ──► `dxcli autopsy --baseline /tmp/base.json --summary`
│  (Culprit Attribution) │     (Identifies exact bloat & posts GitHub Summary/PR Comment)
└────────────────────────┘
```

---

## Official GitHub Action (Recommended)

The easiest way to integrate `dxcli` in GitHub Actions is with the composite action:

### Complete Workflow with Baseline & Autopsy
```yaml
name: Build Pipeline with Disk Autopsy

on:
  push:
    branches: [main]
  pull_request:

jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write # Required if pr-comment: true

    steps:
      - uses: actions/checkout@v4

      # Phase 1: Pre-Build Guard & Baseline
      - name: Disk Guard & Baseline
        uses: Seshadri724/diskrx@v1
        with:
          mode: "snapshot-baseline"
          baseline-file: "dxcli-baseline.json"
          docker: "true"

      # Main Build Step
      - name: Build Application
        run: |
          docker build -t my-app:latest .
          npm test

      # Phase 2: Post-Build Autopsy (Runs even on failure)
      - name: Disk Growth Autopsy
        if: always()
        uses: Seshadri724/diskrx@v1
        with:
          mode: "autopsy"
          baseline-file: "dxcli-baseline.json"
          summary: "true"      # Appends to $GITHUB_STEP_SUMMARY
          pr-comment: "true"   # Posts markdown summary to the PR
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

---

## Platform Integration Examples

### GitHub Actions (Direct CLI)

If you prefer installing directly via `pip`:

```yaml
name: CI Disk Guard
on: [push, pull_request]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dxcli
        run: pip install diskrx

      # 1. Pre-build check (silent unless critical pressure)
      - name: Pre-build Disk Guard
        run: dxcli ci

      # 2. Baseline snapshot
      - name: Record Baseline
        run: dxcli snapshot-baseline --baseline /tmp/dx-base.json .

      # 3. Main Build
      - name: Run Build
        run: ./build.sh

      # 4. Post-build Report
      - name: Disk Autopsy Report
        if: always()
        run: dxcli autopsy --baseline /tmp/dx-base.json --summary .
```

---

### GitLab CI

Add pre-build checking and automatic failure artifacts in `.gitlab-ci.yml`:

```yaml
stages:
  - guard
  - build

disk-guard:
  stage: guard
  image: python:3.12-slim
  script:
    - pip install diskrx
    - dxcli ci

build-job:
  stage: build
  image: docker:latest
  before_script:
    - apk add --no-cache python3 py3-pip
    - pip install diskrx --break-system-packages
    - dxcli snapshot-baseline --baseline /tmp/dx-base.json .
  script:
    - ./build.sh
  after_script:
    - dxcli autopsy --baseline /tmp/dx-base.json . || true
    - dxcli diagnose . --docker --report disk-report.html || true
  artifacts:
    when: always
    paths:
      - disk-report.html
    expire_in: 7 days
```

---

### Jenkins (Declarative Pipeline)

Embed `dxcli` directly into your `Jenkinsfile`:

```groovy
pipeline {
    agent any
    stages {
        stage('Pre-Build Guard') {
            steps {
                sh 'pip install diskrx'
                // Fails immediately if disk is >= 90% or policies breached
                sh 'dxcli ci'
                sh 'dxcli snapshot-baseline --baseline /tmp/jenkins-base.json .'
            }
        }
        stage('Build & Test') {
            steps {
                sh './build.sh'
            }
        }
    }
    post {
        always {
            sh 'dxcli autopsy --baseline /tmp/jenkins-base.json . || true'
        }
        failure {
            sh 'dxcli diagnose . --docker --report jenkins-disk-report.html || true'
            archiveArtifacts artifacts: 'jenkins-disk-report.html', allowEmptyArchive: true
        }
    }
}
```

---

### CircleCI

Add to `.circleci/config.yml`:

```yaml
version: 2.1

jobs:
  build:
    docker:
      - image: cimg/python:3.12
    steps:
      - checkout
      - run:
          name: Pre-Build Disk Guard
          command: |
            pip install diskrx
            dxcli ci
            dxcli snapshot-baseline --baseline /tmp/circle-base.json .
      - run:
          name: Build
          command: ./build.sh
      - run:
          name: Post-Build Autopsy
          command: dxcli autopsy --baseline /tmp/circle-base.json .
          when: always
```

---

### Bitbucket Pipelines

Add to `bitbucket-pipelines.yml`:

```yaml
image: python:3.12

pipelines:
  default:
    - step:
        name: Build with Disk Guard
        script:
          - pip install diskrx
          - dxcli ci
          - dxcli snapshot-baseline --baseline /tmp/bb-base.json .
          - ./build.sh
        after-script:
          - dxcli autopsy --baseline /tmp/bb-base.json .
```

---

### Azure DevOps Pipelines

Add to `azure-pipelines.yml`:

```yaml
trigger:
  - main

pool:
  vmImage: "ubuntu-latest"

steps:
  - task: UsePythonVersion@0
    inputs:
      versionSpec: "3.12"

  - script: |
      pip install diskrx
      dxcli ci
      dxcli snapshot-baseline --baseline $(Agent.TempDirectory)/base.json .
    displayName: "Pre-Build Disk Guard"

  - script: ./build.sh
    displayName: "Execute Build"

  - script: dxcli autopsy --baseline $(Agent.TempDirectory)/base.json .
    condition: always()
    displayName: "Disk Autopsy"
```

---

## Docker Storage Optimization in CI

When using Docker in CI (Docker-in-Docker or host Docker socket), append `--docker` to diagnose container overhead:

```bash
# Detailed breakdown of images, containers, anonymous volumes, and BuildKit cache
dxcli diagnose / --ci --docker
```

Common CI Docker issues caught by `dxcli`:
- **BuildKit cache exhaustion**: Accumulated multi-stage layer cache.
- **Dangling images**: Leftover untagged `<none>` layers from failed builds.
- **Orphan volumes**: Unpruned anonymous volumes created by test containers.

---

## Policy as Code (`dx_policies.yaml`)

Define deterministic disk policies in the root of your repository to automatically fail builds when limits are violated:

```yaml
# dx_policies.yaml
rules:
  # Prevent massive dependencies from being checked in
  - name: Source Tree Size Limit
    type: limit
    path: src/
    max_size_gb: 1
    action: Source tree exceeds 1GB ceiling

  # Reject forgotten temporary files in workspace
  - name: No Stale Test Dumps
    type: stale
    path: tmp/
    max_age_days: 2
    action: Clean up old test fixtures
```

When `dxcli ci` or `dxcli diagnose --ci` runs, any `CRITICAL` policy violation immediately exits with code `1`.

---

## Exit Code Matrix

| Exit Code | Meaning in CI | Recommended CI Action |
| :---: | :--- | :--- |
| `0` | **Healthy** (Disk < 90%, policies pass) | Proceed to build steps. |
| `1` | **Critical Pressure / Policy Breach** | Fail pipeline fast; review runner disk or run `dxcli clean`. |
| `2` | **Invalid Arguments / Missing Baseline** | Check baseline file path or workflow configuration. |
| `3` | **Runtime Exception** | Check environment Python version (requires >= 3.8). |
| `4` | **Partial Scan** | Non-fatal permission warnings on restricted paths. |

---

## Post-Build Automated Cleanup

If you run self-hosted runners where disk accumulates over time, clean up automatically in your post-job hook:

```bash
# Automated non-interactive cleanup of stale cache and docker bloat
dxcli clean --yes .
```
