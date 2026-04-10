import os
import concurrent.futures
from typing import List, Dict, Tuple
from ..store.models import DirNode

class DirectoryTreeCollector:
    """
    Uses os.scandir for speed.
    """
    def scan(self, root_path: str, max_depth: int = 3) -> List[DirNode]:
        # To avoid blocking forever, we'll implement a fast multi-threaded or limited scan.
        # But for absolute accuracy, a full scan is needed. We'll do a simple parallel scan of top-level.
        
        results = []
        try:
            entries = list(os.scandir(root_path))
        except (OSError, PermissionError):
            return []
            
        directories = [e for e in entries if e.is_dir() and not e.is_symlink()]
        
        def process_dir(entry: os.DirEntry) -> DirNode:
            size, count = self._get_size_fast(entry.path)
            return DirNode(path=entry.path, size_bytes=size, file_count=count)
            
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(32, os.cpu_count() + 4)) as executor:
            future_to_entry = {executor.submit(process_dir, d): d for d in directories}
            for future in concurrent.futures.as_completed(future_to_entry):
                try:
                    res = future.result()
                    if res.size_bytes > 0:
                        results.append(res)
                except Exception:
                    pass
                    
        # Sort by size descending
        results.sort(key=lambda x: x.size_bytes, reverse=True)
        return results

    def _get_size_fast(self, path: str) -> Tuple[int, int]:
        total_size = 0
        total_count = 0
        try:
            for entry in os.scandir(path):
                if entry.is_symlink():
                    continue
                if entry.is_dir():
                    s, c = self._get_size_fast(entry.path)
                    total_size += s
                    total_count += c
                elif entry.is_file():
                    total_size += entry.stat(follow_symlinks=False).st_size
                    total_count += 1
        except (OSError, PermissionError):
            pass
        return total_size, total_count
