import os
from typing import List
from ..store.models import UnrotatedLog
from ..config import DEFAULT_CONFIG
import time

class LogFinderCollector:
    def __init__(self, config=DEFAULT_CONFIG):
        self.config = config
        
    def scan(self, paths: List[str]) -> List[UnrotatedLog]:
        logs = []
        threshold_bytes = self.config.large_log_threshold_mb * 1024 * 1024
        
        for root_path in paths:
            # We use os.walk to find logs, handling permission errors
            try:
                for dirpath, dirnames, filenames in os.walk(root_path):
                    for filename in filenames:
                        # Simple naive check matching extension
                        if any(filename.endswith(ext.replace('*', '')) for ext in self.config.log_patterns):
                            filepath = os.path.join(dirpath, filename)
                            try:
                                stat = os.stat(filepath)
                                if stat.st_size > threshold_bytes:
                                    logs.append(UnrotatedLog(
                                        path=filepath,
                                        size_bytes=stat.st_size,
                                        last_modified_timestamp=stat.st_mtime,
                                        has_logrotate_config=self.check_logrotate(filepath)
                                    ))
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
        has_numbered = os.path.exists(filepath + ".1") or os.path.exists(filepath + ".2")
        return has_gz or has_numbered

