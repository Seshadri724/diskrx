"""Safe automated storage cleanup engine for dxcli.

Discovers and safely purges disposable caches, build artifacts, and Docker bloat
while strictly protecting system paths and named persistent volumes.
Enforces dry-run plans by default and writes an append-only audit trail to ~/.dx/audit.log.
"""

import json
import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from .collectors.docker import DockerCollector
from .state import get_state_dir

logger = logging.getLogger(__name__)

# Paths that MUST NEVER be deleted under any circumstance
PROTECTED_PATHS: Set[str] = {
    "/",
    "/bin",
    "/boot",
    "/dev",
    "/etc",
    "/home",
    "/lib",
    "/lib64",
    "/media",
    "/mnt",
    "/opt",
    "/proc",
    "/root",
    "/run",
    "/sbin",
    "/srv",
    "/sys",
    "/tmp",  # nosec B108
    "/usr",
    "/var",
    "c:\\",
    "c:\\windows",
    "c:\\program files",
    "c:\\program files (x86)",
    "c:\\users",
}


@dataclass
class CleanTarget:
    name: str
    category: str
    path: Optional[str]
    size_bytes: int
    command: Optional[str] = None
    is_docker: bool = False
    is_protected: bool = False


@dataclass
class CleanPlan:
    created_at: float
    scan_path: str
    targets: List[CleanTarget]
    estimated_savings_bytes: int
    protected_excluded: List[str]
    dry_run: bool = True


@dataclass
class CleanResult:
    timestamp: float
    freed_bytes: int
    cleaned_items: List[str]
    failed_items: List[Dict[str, str]]
    audit_log_path: str


def is_path_protected(path: str) -> bool:
    """Check if a path is a system-critical protected directory."""
    if not path:
        return True
    raw_lower = path.lower().rstrip("/\\")
    protected_set = {p.lower().rstrip("/\\") for p in PROTECTED_PATHS}
    if raw_lower in protected_set:
        return True
    norm = os.path.abspath(path).lower().rstrip(os.sep)
    if norm in protected_set:
        return True
    user_home = os.path.expanduser("~").lower().rstrip(os.sep)
    if norm == user_home:
        return True
    return False


class CleanEngine:
    """Orchestrates discovery, dry-run planning, and safe execution of disk cleanups."""

    def __init__(self, state_dir: Optional[str] = None):
        self.state_dir = state_dir or get_state_dir()
        self.audit_log_path = os.path.join(self.state_dir, "audit.log")

    def discover_targets(
        self, scan_path: str = ".", include_docker: bool = True
    ) -> Tuple[List[CleanTarget], List[str]]:
        """Find disposable caches and build artifacts in scan_path and user home."""
        targets: List[CleanTarget] = []
        protected_excluded: List[str] = []
        scan_abs = os.path.abspath(scan_path)

        # 1. Project-local disposable targets
        for root, dirs, files in os.walk(scan_abs, topdown=True):
            # Exclude symlinks
            dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(root, d))]

            for d in list(dirs):
                full_path = os.path.join(root, d)
                d_lower = d.lower()

                if d_lower in (
                    "node_modules",
                    ".pytest_cache",
                    ".tox",
                    ".next",
                    ".nuxt",
                    "target",
                    "build",
                    "dist",
                ):
                    if is_path_protected(full_path):
                        protected_excluded.append(full_path)
                        continue

                    try:
                        size = sum(
                            os.path.getsize(os.path.join(r, f))
                            for r, _, fs in os.walk(full_path)
                            for f in fs
                            if not os.path.islink(os.path.join(r, f))
                        )
                    except OSError:
                        size = 0

                    if size > 0:
                        targets.append(
                            CleanTarget(
                                name=f"Project artifact `{d}` in {os.path.basename(root)}",
                                category="project_artifact",
                                path=full_path,
                                size_bytes=size,
                            )
                        )
                    # Don't recurse inside matched artifact dirs
                    dirs.remove(d)

        # 2. Global user caches
        home = os.path.expanduser("~")
        candidate_caches = [
            ("npm cache", "npm", os.path.join(home, ".npm")),
            ("yarn cache", "yarn", os.path.join(home, ".cache", "yarn")),
            ("pip cache", "pip", os.path.join(home, ".cache", "pip")),
            (
                "pip Windows cache",
                "pip",
                os.path.join(home, "AppData", "Local", "pip", "Cache"),
            ),
            (
                "Cargo registry cache",
                "cargo",
                os.path.join(home, ".cargo", "registry", "cache"),
            ),
            ("Go build cache", "go", os.path.join(home, ".cache", "go-build")),
        ]

        for name, cat, cache_path in candidate_caches:
            if os.path.exists(cache_path):
                if is_path_protected(cache_path):
                    protected_excluded.append(cache_path)
                    continue
                try:
                    size = sum(
                        os.path.getsize(os.path.join(r, f))
                        for r, _, fs in os.walk(cache_path)
                        for f in fs
                        if not os.path.islink(os.path.join(r, f))
                    )
                except OSError:
                    size = 0
                if size > 0:
                    targets.append(
                        CleanTarget(
                            name=name,
                            category=cat,
                            path=cache_path,
                            size_bytes=size,
                        )
                    )

        # 3. Docker reclaimables
        if include_docker:
            collector = DockerCollector()
            df = collector.get_system_df()
            if df:
                # Images
                img_rec = df.get("Images", {}).get("Reclaimable", 0)
                if img_rec > 0:
                    targets.append(
                        CleanTarget(
                            name="Dangling Docker images",
                            category="docker",
                            path=None,
                            size_bytes=img_rec,
                            command="docker image prune -f",
                            is_docker=True,
                        )
                    )
                # Build Cache
                bc_rec = df.get("Build Cache", {}).get("Reclaimable", 0)
                if bc_rec > 0:
                    targets.append(
                        CleanTarget(
                            name="Docker build cache",
                            category="docker",
                            path=None,
                            size_bytes=bc_rec,
                            command="docker builder prune -f",
                            is_docker=True,
                        )
                    )
                # Volumes (check protection)
                vol_rec = df.get("Local Volumes", {}).get("Reclaimable", 0)
                if vol_rec > 0:
                    vols = collector.get_volume_details()
                    named_count = sum(1 for v in vols if v.get("is_protected"))
                    if named_count > 0:
                        protected_excluded.append(
                            f"{named_count} named persistent Docker volume(s)"
                        )
                    cmd = (
                        "docker volume prune -f --filter label!=keep"
                        if named_count > 0
                        else "docker volume prune -f"
                    )
                    targets.append(
                        CleanTarget(
                            name="Unused Docker volumes",
                            category="docker",
                            path=None,
                            size_bytes=vol_rec,
                            command=cmd,
                            is_docker=True,
                        )
                    )

        return targets, protected_excluded

    def create_plan(
        self, scan_path: str = ".", include_docker: bool = True
    ) -> CleanPlan:
        """Build a dry-run CleanPlan outlining proposed targets and savings."""
        targets, protected = self.discover_targets(
            scan_path, include_docker=include_docker
        )
        est_savings = sum(t.size_bytes for t in targets)
        return CleanPlan(
            created_at=time.time(),
            scan_path=os.path.abspath(scan_path),
            targets=targets,
            estimated_savings_bytes=est_savings,
            protected_excluded=protected,
            dry_run=True,
        )

    def execute_plan(self, plan: CleanPlan) -> CleanResult:
        """Execute a CleanPlan and write audit entry."""
        freed = 0
        cleaned: List[str] = []
        failed: List[Dict[str, str]] = []

        for target in plan.targets:
            if target.is_docker and target.command:
                try:
                    cmd_parts = target.command.split()
                    res = subprocess.run(
                        cmd_parts, capture_output=True, text=True, timeout=60
                    )
                    if res.returncode == 0:
                        freed += target.size_bytes
                        cleaned.append(target.name)
                    else:
                        failed.append(
                            {"target": target.name, "error": res.stderr.strip()}
                        )
                except Exception as e:
                    failed.append({"target": target.name, "error": str(e)})

            elif target.path:
                if is_path_protected(target.path):
                    failed.append(
                        {"target": target.name, "error": "Protected path blocked"}
                    )
                    continue

                try:
                    if os.path.isdir(target.path) and not os.path.islink(target.path):
                        shutil.rmtree(target.path)
                    elif os.path.exists(target.path):
                        os.remove(target.path)
                    freed += target.size_bytes
                    cleaned.append(target.name)
                except Exception as e:
                    failed.append({"target": target.name, "error": str(e)})

        # Write audit log
        self._write_audit_entry(freed, cleaned, failed)

        return CleanResult(
            timestamp=time.time(),
            freed_bytes=freed,
            cleaned_items=cleaned,
            failed_items=failed,
            audit_log_path=self.audit_log_path,
        )

    def _write_audit_entry(
        self, freed: int, cleaned: List[str], failed: List[Dict[str, str]]
    ) -> None:
        """Append an audit log entry to ~/.dx/audit.log."""
        try:
            os.makedirs(self.state_dir, exist_ok=True)
            entry = {
                "timestamp": time.time(),
                "freed_bytes": freed,
                "cleaned_items": cleaned,
                "failed_items": failed,
            }
            with open(self.audit_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError as e:
            logger.warning("Could not write audit log: %s", e)
