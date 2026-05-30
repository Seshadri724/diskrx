import os
import concurrent.futures
from typing import List, Tuple
from ..store.models import DirNode

class DirectoryTreeCollector:
    """
    High-concurrency directory scanner.
    Parallelizes stat calculations by submitting one worker per top-level child directory.
    For deeper parallelism, increase the number of top-level children or restructure the scan.
    """
    def __init__(self, max_threads: int = None, max_depth: int = None):
        if max_threads is None:
            max_threads = min(16, (os.cpu_count() or 4) * 2)
        self.max_threads = max_threads
        self.max_depth = max_depth


    def scan(self, root_path: str) -> List[DirNode]:
        """
        Scans top-level directories of root_path to identify storage consumers.
        Deep-scans each top-level child directory in a separate thread.
        If max_depth is set, descends at most that many levels below root_path.
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
            # Each top-level child starts at depth=1
            remaining_depth = (self.max_depth - 1) if self.max_depth is not None else None
            future_to_path = {
                executor.submit(self._calculate_dir_stats, d.path, remaining_depth): d.path
                for d in target_dirs
            }
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

    def _calculate_dir_stats(self, root_dir: str, remaining_depth: int = None) -> Tuple[int, int]:
        """
        Iterative directory stat collector using os.scandir and a stack.
        If remaining_depth is not None, limits recursion to that many additional levels.
        """
        total_size = 0
        total_count = 0
        # Stack entries: (directory_path, remaining_depth)
        stack = [(root_dir, remaining_depth)]
        
        while stack:
            current_dir, depth_left = stack.pop()
            try:
                with os.scandir(current_dir) as entries:
                    for entry in entries:
                        try:
                            if entry.is_symlink():
                                continue
                            
                            if entry.is_dir():
                                # Only descend if depth allows
                                if depth_left is None:
                                    stack.append((entry.path, None))
                                elif depth_left > 0:
                                    stack.append((entry.path, depth_left - 1))
                                # else: depth exhausted, skip this subdirectory
                            else:
                                total_size += entry.stat(follow_symlinks=False).st_size
                                total_count += 1
                        except (OSError, PermissionError):
                            continue
            except (OSError, PermissionError):
                continue
                
        return total_size, total_count

