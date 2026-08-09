import os
from typing import List
from ..store.models import UnrotatedLog
from ..config import get_config


class LogFinderCollector:
    def __init__(self, config=None):
        self._config = config

    @property
    def config(self):
        if self._config is None:
            self._config = get_config()
        return self._config

    def scan(self, paths: List[str]) -> List[UnrotatedLog]:
        logs = []
        threshold_bytes = self.config.large_log_threshold_mb * 1024 * 1024

        IGNORED_SYSTEM_DIRS = {
            "$recycle.bin",
            "system volume information",
            "$winreagent",
            "config.msi",
            "proc",
            "sys",
            "dev",
            "run",
            "windows",
        }

        for root_path in paths:
            clean_root = os.path.abspath(root_path).rstrip("/\\")
            is_drive_root = len(clean_root) <= 3 or clean_root == ""
            try:
                for dirpath, dirnames, filenames in os.walk(root_path):
                    # Prune system and hidden directories instantly
                    dirnames[:] = [
                        d
                        for d in dirnames
                        if d.lower() not in IGNORED_SYSTEM_DIRS
                        and not d.startswith("$")
                    ]
                    if is_drive_root:
                        rel_path = dirpath[len(clean_root) :].lstrip("/\\")
                        if rel_path and rel_path.count(os.sep) >= 2:
                            dirnames.clear()

                    for filename in filenames:
                        # Simple naive check matching extension
                        if any(
                            filename.endswith(ext.replace("*", ""))
                            for ext in self.config.log_patterns
                        ):
                            filepath = os.path.join(dirpath, filename)
                            try:
                                stat = os.lstat(filepath)
                                if stat.st_mode & 0o170000 == 0o120000:  # symlink
                                    continue
                                if stat.st_size > threshold_bytes:
                                    logs.append(
                                        UnrotatedLog(
                                            path=filepath,
                                            size_bytes=stat.st_size,
                                            last_modified_timestamp=stat.st_mtime,
                                            has_logrotate_config=self.check_logrotate(
                                                filepath
                                            ),
                                        )
                                    )
                            except (OSError, PermissionError):
                                continue
            except (OSError, PermissionError):
                continue
        return logs

    def check_logrotate(self, filepath: str) -> bool:
        """Check if a log file appears to have rotation configured."""
        # Check for compressed rotated copies
        has_gz = os.path.exists(filepath + ".1.gz") or os.path.exists(filepath + ".gz")
        # Check for numbered rotation (app.log.1, app.log.2)
        has_numbered = os.path.exists(filepath + ".1") or os.path.exists(
            filepath + ".2"
        )
        if has_gz or has_numbered:
            return True

        import glob

        parent = os.path.dirname(filepath)
        basename = os.path.basename(filepath)
        patterns = [
            os.path.join(parent, f"{basename}-*"),
            os.path.join(parent, f"{basename}.*.gz"),
            os.path.join(parent, f"{basename}.*.zip"),
        ]
        for pat in patterns:
            try:
                if glob.glob(pat):
                    return True
            except Exception:
                pass
        return False
