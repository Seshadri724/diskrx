# 🚀 dxcli CI/CD Integration Guide

Catch disk issues in your pipelines before they cause catastrophic build failures.

## Why use dxcli in CI?
Modern build agents (Jenkins, GitHub Actions, GitLab CI) often run on ephemeral or shared disks. A "Disk Full" error mid-build can:
1. Corrupt build artifacts.
2. Cause cryptic "Input/Output error" messages.
3. Waste 30-60 minutes of developer time.

## The solution: `dxcli diagnose --ci`
The `--ci` flag is specifically designed for automated environments.

### Key Features:
- **Non-Zero Exit Code**: Exits with `1` if disk usage is >90% or if critical policies are violated.
- **Silent Mode**: Suppresses interactive prompts and ASCII art for clean logs.
- **Root Cause Attribution**: If a previous build left "garbage" behind, `dxcli` will find it.

---

## 🛠️ Jenkins Integration

Add this snippet as a pre-build step in your Jenkinsfile:

```groovy
pipeline {
    agent any
    stages {
        stage('Pre-Build Disk Check') {
            steps {
                sh 'pip install dxcli'
                // Fail the build if disk is critical or policies are breached
                sh 'dxcli diagnose . --ci'
            }
        }
        stage('Build') {
            steps {
                sh './build.sh'
            }
        }
    }
}
```

---

## 🐙 GitHub Actions

Use `dxcli` to verify runner health:

```yaml
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Install dxcli
        run: pip install dxcli
      - name: Disk Guard
        run: dxcli diagnose / --ci --docker
```

---

## 🚨 Alerting with Webhooks

Combine `watch` with webhooks in your staging environments:

```bash
# Start a background observer
dxcli daemon start --command watch --args "/var/lib/docker --alert-threshold 5G --webhook https://hooks.slack.com/services/..."
```

---

## 🛡️ Best Practices
1. **Target Large Paths**: Always run `dxcli` on paths where builds happen (e.g., `workspace/` or `/tmp`).
2. **Docker Cleanup**: Use the `--docker` flag in CI to detect dangling images left over from previous failed builds.
3. **Policy Enforcement**: Define a `dx_policies.yaml` in your repo to enforce rules like "No files larger than 1GB allowed in the source tree".
