import os
import time
from typing import List
from ..store.models import StaleFile
from ..config import DEFAULT_CONFIG

class StaleFileCollector:
    def __init__(self, config=DEFAULT_CONFIG):
        self.config = config
        
    def scan(self, paths: List[str]) -> List[StaleFile]:
        stales = []
        now = time.time()
        stale_seconds = self.config.stale_days * 86400
        
        for root_path in paths:
            try:
                for dirpath, dirnames, filenames in os.walk(root_path):
                    for filename in filenames:
                        filepath = os.path.join(dirpath, filename)
                        try:
                            stat = os.stat(filepath)
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
