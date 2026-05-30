import os
from typing import List, Dict
from ..store.models import DirNode

class ClassificationEngine:
    """
    Groups disk usage by semantic category (Media, Logs, Code, etc.)
    Supports custom category definitions.
    """
    DEFAULT_CATEGORIES = {
        'Logs': ['.log', '.txt', '.out', '.err', '.syslog', '.evtx'],
        'Media': ['.mp4', '.mkv', '.avi', '.mov', '.mp3', '.wav', '.jpg', '.png', '.gif', '.pdf', '.jpeg'],
        'Code': ['.py', '.js', '.ts', '.c', '.cpp', '.h', '.go', '.rs', '.java', '.php', '.html', '.css', '.pyw'],
        'Build Artifacts': ['.obj', '.o', '.a', '.lib', '.dll', '.so', '.exe', '.bin', '.hex', '.node', '.whl', '.egg'],
        'Database': ['.db', '.sqlite', '.mdb', '.sql', '.dat', '.dbf', '.sav'],
        'Cache': ['.cache', '.tmp', '.temp', '.pyc', '.swp', '.idx', '.old'],
        'Archives': ['.zip', '.tar', '.gz', '.7z', '.rar', '.bz2', '.iso']
    }

    def __init__(self, custom_categories: Dict[str, List[str]] = None):
        self.categories = custom_categories or self.DEFAULT_CATEGORIES

    def classify_directory(self, path: str, _seen: set = None) -> Dict[str, int]:
        """
        Scans a directory and returns a map of {Category: TotalBytes}
        """
        if _seen is None:
            _seen = set()

        results = {cat: 0 for cat in self.categories}
        results['Others'] = 0

        # Avoid cycles by checking realpath and st_dev, st_ino
        try:
            abs_path = os.path.abspath(path)
            stat_info = os.lstat(abs_path)
            identity = (stat_info.st_dev, stat_info.st_ino)
            if identity in _seen:
                return results
            _seen.add(identity)
        except OSError:
            return results

        try:
            with os.scandir(path) as it:
                for entry in it:
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_file(follow_symlinks=False):
                            try:
                                size = entry.stat(follow_symlinks=False).st_size
                                ext = os.path.splitext(entry.name)[1].lower()
                                
                                found = False
                                for cat, extensions in self.categories.items():
                                    if ext in extensions:
                                        results[cat] += size
                                        found = True
                                        break
                                
                                if not found:
                                    results['Others'] += size
                            except (PermissionError, FileNotFoundError):
                                continue
                        elif entry.is_dir(follow_symlinks=False):
                            # Recursively classify subdirectories
                            sub_res = self.classify_directory(entry.path, _seen)
                            for cat, size in sub_res.items():
                                results[cat] += size
                    except Exception:
                        continue
        except Exception:
            pass

        return results

    def get_summary(self, top_dirs: List[DirNode]) -> Dict[str, int]:
        """
        Aggregates classification across the top directories.
        """
        summary = {cat: 0 for cat in self.categories}
        summary['Others'] = 0

        for d in top_dirs:
            res = self.classify_directory(d.path, _seen=set())
            for cat, size in res.items():
                summary[cat] += size
        
        return summary
