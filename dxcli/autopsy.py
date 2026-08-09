"""CI Autopsy & Baseline tracking module for dxcli.

Enables two-step build growth analysis:
1. `dxcli snapshot-baseline --baseline /tmp/dx-baseline.json` (pre-build)
2. `dxcli autopsy --baseline /tmp/dx-baseline.json` (post-build / failure)

Diffs pre-build vs post-build disk usage, identifies growth culprits,
and generates GitHub $GITHUB_STEP_SUMMARY / PR comment markdown.
"""

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from .engine import run_diagnosis
from .outputs.cli_report import format_bytes
from .runtime import atomic_write_text
from .store.models import CollectorError, Prescription

logger = logging.getLogger(__name__)

CURRENT_SCHEMA_VERSION = 1


@dataclass
class BaselineSnapshot:
    schema: int
    created_at: float
    path: str
    partition: Optional[Dict[str, Any]]
    dirs: List[Dict[str, Any]]
    docker: Optional[Dict[str, Any]]
    collector_errors: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class DirGrowth:
    path: str
    size_before: int
    size_after: int
    delta_bytes: int


@dataclass
class AutopsyReport:
    schema: int
    created_at: float
    path: str
    baseline_file: str
    total_growth_bytes: int
    grown_dirs: List[DirGrowth]
    shrunk_dirs: List[DirGrowth]
    docker_growth: Optional[Dict[str, Any]]
    probable_cause: str
    prescriptions: List[Prescription]
    collector_errors: List[CollectorError]


def save_baseline(
    path: str, baseline_file: str, include_docker: bool = True
) -> BaselineSnapshot:
    """Run diagnosis and write baseline snapshot to a JSON file atomically."""
    snap = run_diagnosis(path, include_docker=include_docker, include_processes=False)

    baseline_data = BaselineSnapshot(
        schema=CURRENT_SCHEMA_VERSION,
        created_at=time.time(),
        path=os.path.abspath(path),
        partition=asdict(snap.partition) if snap.partition else None,
        dirs=[asdict(d) for d in snap.top_dirs],
        docker=snap.docker,
        collector_errors=[asdict(e) for e in snap.collector_errors],
    )

    json_str = json.dumps(asdict(baseline_data), indent=2)
    atomic_write_text(baseline_file, json_str)
    return baseline_data


def run_autopsy(baseline_file: str, path: str = ".") -> AutopsyReport:
    """Compare current directory state against a pre-build baseline file."""
    if not os.path.exists(baseline_file):
        raise ValueError(f"Baseline file not found: {baseline_file}")

    with open(baseline_file, "r", encoding="utf-8") as f:
        raw = json.load(f)

    schema = raw.get("schema", 1)
    if schema > CURRENT_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported baseline schema version: {schema} (expected <= {CURRENT_SCHEMA_VERSION})"
        )

    # Convert raw baseline dirs dict to a map path -> size_bytes
    before_dirs = {d["path"]: d["size_bytes"] for d in raw.get("dirs", [])}
    before_docker = raw.get("docker")

    include_docker = before_docker is not None
    current_snap = run_diagnosis(
        path, include_docker=include_docker, include_processes=False
    )

    grown_dirs: List[DirGrowth] = []
    shrunk_dirs: List[DirGrowth] = []
    total_growth = 0

    for d in current_snap.top_dirs:
        prev_size = before_dirs.get(d.path, 0)
        delta = d.size_bytes - prev_size
        if delta > 0:
            grown_dirs.append(
                DirGrowth(
                    path=d.path,
                    size_before=prev_size,
                    size_after=d.size_bytes,
                    delta_bytes=delta,
                )
            )
            total_growth += delta
        elif delta < 0:
            shrunk_dirs.append(
                DirGrowth(
                    path=d.path,
                    size_before=prev_size,
                    size_after=d.size_bytes,
                    delta_bytes=delta,
                )
            )

    grown_dirs.sort(key=lambda x: x.delta_bytes, reverse=True)
    shrunk_dirs.sort(key=lambda x: x.delta_bytes)

    # Docker growth diff
    docker_growth = None
    if before_docker and current_snap.docker:
        docker_growth = {}
        for cat, curr_val in current_snap.docker.items():
            prev_val = before_docker.get(cat, {})
            prev_size = prev_val.get("Size", 0) if isinstance(prev_val, dict) else 0
            curr_size = curr_val.get("Size", 0) if isinstance(curr_val, dict) else 0
            docker_growth[cat] = {
                "before": prev_size,
                "after": curr_size,
                "delta": curr_size - prev_size,
            }

    # Probable cause determination
    if grown_dirs:
        top_grower = grown_dirs[0]
        basename = os.path.basename(top_grower.path.rstrip(os.sep))
        probable_cause = (
            f"Directory `{basename}` grew by {format_bytes(top_grower.delta_bytes)} "
            f"during build."
        )
    elif total_growth > 0:
        probable_cause = f"Storage usage grew by {format_bytes(total_growth)}."
    else:
        probable_cause = "No significant storage growth detected."

    return AutopsyReport(
        schema=CURRENT_SCHEMA_VERSION,
        created_at=time.time(),
        path=os.path.abspath(path),
        baseline_file=baseline_file,
        total_growth_bytes=total_growth,
        grown_dirs=grown_dirs,
        shrunk_dirs=shrunk_dirs,
        docker_growth=docker_growth,
        probable_cause=probable_cause,
        prescriptions=current_snap.prescriptions,
        collector_errors=current_snap.collector_errors,
    )


def render_markdown(report: AutopsyReport) -> str:
    """Render AutopsyReport as GitHub-flavored Markdown for PR comments or Step Summary."""
    lines = []
    lines.append("<!-- dxcli-autopsy -->")
    lines.append("## 🔍 dxcli CI Storage Autopsy Report")
    lines.append("")
    lines.append(f"**Probable Cause:** {report.probable_cause}")
    lines.append(f"**Total Build Growth:** `{format_bytes(report.total_growth_bytes)}`")
    lines.append("")

    if report.grown_dirs:
        lines.append("### 📈 Top Storage Consumers (Growth During Build)")
        lines.append("")
        lines.append("| Directory | Before | After | Delta |")
        lines.append("| --- | ---: | ---: | ---: |")
        for g in report.grown_dirs[:10]:
            display = g.path if len(g.path) <= 45 else "..." + g.path[-42:]
            lines.append(
                f"| `{display}` | {format_bytes(g.size_before)} | "
                f"{format_bytes(g.size_after)} | **+{format_bytes(g.delta_bytes)}** |"
            )
        lines.append("")

    if report.docker_growth:
        lines.append("### 🐳 Docker Resource Changes")
        lines.append("")
        lines.append("| Resource Type | Before | After | Delta |")
        lines.append("| --- | ---: | ---: | ---: |")
        for cat, stats in report.docker_growth.items():
            delta = stats["delta"]
            sign = "+" if delta > 0 else ""
            lines.append(
                f"| `{cat}` | {format_bytes(stats['before'])} | "
                f"{format_bytes(stats['after'])} | {sign}{format_bytes(delta)} |"
            )
        lines.append("")

    if report.prescriptions:
        lines.append("### 💡 Prescribed Cleanup Actions")
        lines.append("")
        for p in report.prescriptions:
            lines.append(f"- **{p.name}**: {p.description}")
            if p.template:
                lines.append(f"  ```bash\n  {p.template}\n  ```")
        lines.append("")

    if report.collector_errors:
        lines.append("### ⚠️ Scan Warnings")
        for err in report.collector_errors:
            lines.append(f"- `{err.collector}`: {err.message}")
        lines.append("")

    return "\n".join(lines)


def write_github_summary(markdown: str) -> bool:
    """Write markdown summary to $GITHUB_STEP_SUMMARY environment file if available."""
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_file:
        return False

    try:
        with open(summary_file, "a", encoding="utf-8") as f:
            f.write("\n" + markdown + "\n")
        return True
    except OSError as e:
        logger.warning("Could not write to GITHUB_STEP_SUMMARY: %s", e)
        return False


def post_github_pr_comment(markdown: str) -> bool:
    """Post or update a single GitHub PR comment without creating duplicates.

    Falls back safely if GITHUB_TOKEN or PR number is not available without failing the build.
    """
    import urllib.error
    import urllib.request

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        logger.warning("GITHUB_TOKEN not set. Skipping PR comment creation.")
        return False

    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        logger.warning("GITHUB_REPOSITORY not set. Skipping PR comment creation.")
        return False

    pr_number = None
    # 1. Check GITHUB_REF (e.g., refs/pull/123/merge)
    ref = os.environ.get("GITHUB_REF", "")
    if "refs/pull/" in ref:
        parts = ref.split("/")
        if len(parts) >= 3 and parts[2].isdigit():
            pr_number = int(parts[2])

    # 2. Check GITHUB_EVENT_PATH payload
    if not pr_number:
        event_path = os.environ.get("GITHUB_EVENT_PATH")
        if event_path and os.path.exists(event_path):
            try:
                with open(event_path, "r", encoding="utf-8") as f:
                    event = json.load(f)
                pr_number = event.get("pull_request", {}).get("number") or event.get(
                    "number"
                )
            except Exception as e:
                logger.debug("Failed to parse GITHUB_EVENT_PATH: %s", e)

    if not pr_number:
        logger.warning("Could not determine PR number. Skipping PR comment creation.")
        return False

    api_url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "dxcli-autopsy",
        "Content-Type": "application/json",
    }

    try:
        # Check existing comments to prevent duplicates
        req = urllib.request.Request(api_url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310
            comments = json.loads(resp.read().decode("utf-8"))

        existing_comment_id = None
        for c in comments:
            if "<!-- dxcli-autopsy -->" in c.get("body", ""):
                existing_comment_id = c.get("id")
                break

        payload = json.dumps({"body": markdown}).encode("utf-8")

        if existing_comment_id:
            patch_url = f"https://api.github.com/repos/{repo}/issues/comments/{existing_comment_id}"
            patch_req = urllib.request.Request(
                patch_url, data=payload, headers=headers, method="PATCH"
            )
            with urllib.request.urlopen(patch_req, timeout=10) as resp:  # nosec B310
                return resp.status in (200, 201)
        else:
            post_req = urllib.request.Request(
                api_url, data=payload, headers=headers, method="POST"
            )
            with urllib.request.urlopen(post_req, timeout=10) as resp:  # nosec B310
                return resp.status in (200, 201)

    except Exception as e:
        logger.warning("Failed to post/update GitHub PR comment: %s", e)
        return False
