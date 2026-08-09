# dxcli examples

Copy-pasteable recipes for the most common dxcli setups.

| File | What it shows |
| --- | --- |
| [github-actions.yml](github-actions.yml) | Drop-in GitHub Actions workflow with the `dxcli ci` guard. |
| [gitlab-ci.yml](gitlab-ci.yml) | Same pattern for GitLab CI. |
| [Dockerfile](Dockerfile) | Run `dxcli diagnose` inside a build to catch image bloat. |
| [devcontainer.json](devcontainer.json) | Have your dev container warn you when it crosses 80% used. |
| [pre-commit-hook.sh](pre-commit-hook.sh) | Fail a commit if the local working tree is dangerously full. |

All examples assume `pip install dxcli` is available. For a one-step GitHub Action, see the repo-root [action.yml](../../action.yml).
