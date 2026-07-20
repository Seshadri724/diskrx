import os
import time
from typing import List
from ..store.models import StaleFile
from ..config import get_config

class StaleFileCollector:
    def __init__(self, config=None):
        self._config = config
        
    @property
    def config(self):
        if self._config is None:
            self._config = get_config()
        return self._config
        
    def scan(self, paths: List[str]) -> List[StaleFile]:
        stales = []
        now = time.time()
        stale_seconds = self.config.stale_days * 86400
        
        IGNORED_SYSTEM_DIRS = {
            "$recycle.bin", "system volume information", "$winreagent", "config.msi",
            "proc", "sys", "dev", "run", "windows"
        }

        for root_path in paths:
            clean_root = os.path.abspath(root_path).rstrip("/\\")
            is_drive_root = (len(clean_root) <= 3 or clean_root == "")
            try:
                for dirpath, dirnames, filenames in os.walk(root_path):
                    # Prune system and hidden directories instantly
                    dirnames[:] = [d for d in dirnames if d.lower() not in IGNORED_SYSTEM_DIRS and not d.startswith("$")]
                    if is_drive_root:
                        rel_path = dirpath[len(clean_root):].lstrip("/\\")
                        if rel_path and rel_path.count(os.sep) >= 2:
                            dirnames.clear()

                    for filename in filenames:
                        filepath = os.path.join(dirpath, filename)
                        try:
                            stat = os.lstat(filepath)
                            if stat.st_mode & 0o170000 == 0o120000:  # symlink
                                continue
                            # usually a-time is reliable, but sometimes disabled (noatime), so fallback to mtime
                            last_accessed = max(stat.st_atime, stat.st_mtime)
                            age_seconds = now - last_accessed
                            
                            if age_seconds > stale_seconds and stat.st_size > 10 * 1024 * 1024:  # At least 10MB to be worth flagging
                                stales.append(StaleFile(
                                    path=filepath,
                                    size_bytes=stat.st_size,
                                    last_accessed_timestamp=last_accessed,
                                    days_stale=age_seconds / 86400.0
                                ))
                        except (OSError, PermissionError):
                            continue
            except (OSError, PermissionError):
                continue
                
        # Sort by size
        stales.sort(key=lambda x: x.size_bytes, reverse=True)
        return stales
