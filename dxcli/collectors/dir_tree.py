import os
import concurrent.futures
from typing import List, Tuple
from ..store.models import DirNode

class DirectoryTreeCollector:
    """
    Dyson-Level Scanner: High-concurrency BFS directory scanner.
    Optimized for pure Python performance by parallelizing I/O-bound stat calls.
    """
    def __init__(self, max_threads: int = 64):
        self.max_threads = max_threads

    def scan(self, root_path: str, max_depth: int = 3) -> List[DirNode]:
        """
        Scans top-level directories of root_path to identify storage consumers.
        Deep-scans subdirectories in parallel.
        """
        results = []
        try:
            root_entries = list(os.scandir(root_path))
        except (OSError, PermissionError):
            return []

        # We only report top-level children of root_path
        target_dirs = [e for e in root_entries if e.is_dir() and not e.is_symlink()]
        
        # Parallelize the heavy lifting of calculating sizes for each top-level dir
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_threads) as executor:
            future_to_path = {executor.submit(self._calculate_dir_stats, d.path): d.path for d in target_dirs}
            for future in concurrent.futures.as_completed(future_to_path):
                try:
                    size, count = future.result()
                    if size > 0:
                        results.append(DirNode(path=future_to_path[future], size_bytes=size, file_count=count))
                except Exception:
                    pass

        # Sort by size descending
        results.sort(key=lambda x: x.size_bytes, reverse=True)
        return results

    def _calculate_dir_stats(self, root_dir: str) -> Tuple[int, int]:
        """
        Iterative parallelized/high-speed directory stat collector.
        Uses os.scandir and stack to avoid recursion overhead.
        """
        total_size = 0
        total_count = 0
        stack = [root_dir]
        
        while stack:
            current_dir = stack.pop()
            try:
                with os.scandir(current_dir) as entries:
                    for entry in entries:
                        try:
                            if entry.is_symlink():
                                continue
                            
                            if entry.is_dir():
                                stack.append(entry.path)
                            else:
                                total_size += entry.stat(follow_symlinks=False).st_size
                                total_count += 1
                        except (OSError, PermissionError):
                            continue
            except (OSError, PermissionError):
                continue
                
        return total_size, total_count
