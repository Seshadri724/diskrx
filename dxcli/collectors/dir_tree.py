import os
import concurrent.futures
from typing import List, Tuple
from ..store.models import CollectorError, DirNode

IGNORED_SYSTEM_DIRS = {
    "$recycle.bin",
    "system volume information",
    "$winreagent",
    "config.msi",
    "proc",
    "sys",
    "dev",
    "run",
    "hiberfil.sys",
    "pagefile.sys",
    "swapfile.sys",
}


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
        self.last_errors: List[CollectorError] = []

    def scan(self, root_path: str) -> List[DirNode]:
        """
        Scans top-level directories of root_path to identify storage consumers.
        Deep-scans each top-level child directory in a separate thread.
        If max_depth is set, descends at most that many levels below root_path.
        """
        self.last_errors = []
        results = []
        clean_root = os.path.abspath(root_path)
        # An unbounded scan is the accurate default. A previous implicit
        # depth=3 cap made drive-root reports silently undercount storage.
        effective_depth = self.max_depth

        try:
            root_entries = list(os.scandir(root_path))
        except (OSError, PermissionError) as exc:
            self.last_errors.append(
                CollectorError(
                    collector="directory_tree",
                    message=f"Cannot read root path: {exc}",
                    path=clean_root,
                    error_type=(
                        "permission_denied"
                        if isinstance(exc, PermissionError)
                        else "os_error"
                    ),
                    partial=False,
                )
            )
            return []

        try:
            # Windows reports a synthetic/zero st_dev for regular files, so
            # device-boundary checks are only reliable on POSIX systems.
            root_device = (
                os.stat(root_path, follow_symlinks=False).st_dev
                if os.name != "nt"
                else None
            )
        except OSError:
            root_device = None

        root_file_size = 0
        root_file_count = 0
        for entry in root_entries:
            try:
                if not entry.is_dir(follow_symlinks=False) and not entry.is_symlink():
                    stat = entry.stat(follow_symlinks=False)
                    if root_device is None or stat.st_dev == root_device:
                        root_file_size += stat.st_size
                        root_file_count += 1
            except (OSError, PermissionError):
                continue

        # We only report top-level children of root_path, filtering system bloat
        target_dirs = [
            e
            for e in root_entries
            if e.is_dir()
            and not e.is_symlink()
            and e.name.lower() not in IGNORED_SYSTEM_DIRS
            and not e.name.startswith("$")
        ]

        # Parallelize the heavy lifting of calculating sizes for each top-level dir
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self.max_threads
        ) as executor:
            # Each top-level child starts at depth=1
            remaining_depth = (
                (effective_depth - 1) if effective_depth is not None else None
            )
            future_to_path = {
                executor.submit(
                    self._calculate_dir_stats, d.path, remaining_depth, root_device
                ): d.path
                for d in target_dirs
            }
            for future in concurrent.futures.as_completed(future_to_path):
                try:
                    size, count, errs = future.result()
                    if errs:
                        self.last_errors.extend(errs)
                    if size > 0:
                        results.append(
                            DirNode(
                                path=future_to_path[future],
                                size_bytes=size,
                                file_count=count,
                            )
                        )
                except Exception as exc:
                    self.last_errors.append(
                        CollectorError(
                            collector="directory_tree",
                            message=str(exc),
                            path=future_to_path.get(future),
                            error_type="worker_error",
                            partial=True,
                        )
                    )

        if root_file_size > 0:
            results.append(
                DirNode(
                    path=clean_root,
                    size_bytes=root_file_size,
                    file_count=root_file_count,
                )
            )

        # Sort by size descending
        results.sort(key=lambda x: x.size_bytes, reverse=True)
        return results

    def _calculate_dir_stats(
        self,
        root_dir: str,
        remaining_depth: int = None,
        root_device: int = None,
    ) -> Tuple[int, int, List[CollectorError]]:
        """
        Iterative directory stat collector using os.scandir and a stack.
        If remaining_depth is not None, limits recursion to that many additional levels.
        """
        total_size = 0
        total_count = 0
        dir_errors: List[CollectorError] = []
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
                                if (
                                    entry.name.lower() in IGNORED_SYSTEM_DIRS
                                    or entry.name.startswith("$")
                                ):
                                    continue
                                if root_device is not None:
                                    try:
                                        if (
                                            entry.stat(follow_symlinks=False).st_dev
                                            != root_device
                                        ):
                                            continue
                                    except (OSError, PermissionError) as exc:
                                        if len(dir_errors) < 50:
                                            dir_errors.append(
                                                CollectorError(
                                                    collector="directory_tree",
                                                    message=str(exc),
                                                    path=entry.path,
                                                    error_type=(
                                                        "permission_denied"
                                                        if isinstance(
                                                            exc, PermissionError
                                                        )
                                                        else "os_error"
                                                    ),
                                                    partial=True,
                                                )
                                            )
                                        continue
                                # Only descend if depth allows
                                if depth_left is None:
                                    stack.append((entry.path, None))
                                elif depth_left > 0:
                                    stack.append((entry.path, depth_left - 1))
                                # else: depth exhausted, skip this subdirectory
                            else:
                                total_size += entry.stat(follow_symlinks=False).st_size
                                total_count += 1
                        except (OSError, PermissionError) as exc:
                            if len(dir_errors) < 50:
                                dir_errors.append(
                                    CollectorError(
                                        collector="directory_tree",
                                        message=str(exc),
                                        path=current_dir,
                                        error_type=(
                                            "permission_denied"
                                            if isinstance(exc, PermissionError)
                                            else "os_error"
                                        ),
                                        partial=True,
                                    )
                                )
                            continue
            except (OSError, PermissionError) as exc:
                if len(dir_errors) < 50:
                    dir_errors.append(
                        CollectorError(
                            collector="directory_tree",
                            message=str(exc),
                            path=current_dir,
                            error_type=(
                                "permission_denied"
                                if isinstance(exc, PermissionError)
                                else "os_error"
                            ),
                            partial=True,
                        )
                    )
                continue

        return total_size, total_count, dir_errors
