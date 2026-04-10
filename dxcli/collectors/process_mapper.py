import psutil
import os
from typing import List, Dict, Optional
from dataclasses import dataclass

@dataclass
class ProcessRef:
    pid: int
    name: str
    cmdline: List[str]

class ProcessMapper:
    """
    Identifies which processes have open file handles in specific directories.
    Uses a scan-once cache to avoid repeated expensive process iteration.
    """
    def __init__(self):
        self._process_cache: Optional[Dict[int, List[str]]] = None

    def _build_cache(self):
        """Scan all processes once and cache their open file paths."""
        self._process_cache = {}
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                files = proc.open_files()
                if files:
                    self._process_cache[proc.info['pid']] = {
                        'name': proc.info['name'],
                        'cmdline': proc.info['cmdline'] or [],
                        'paths': [f.path for f in files]
                    }
            except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
                continue
            except Exception:
                continue

    def find_culprits(self, directory_path: str) -> List[ProcessRef]:
        """
        Returns a list of processes that currently have files open in the target directory.
        Builds cache on first call, reuses for subsequent calls.
        """
        if self._process_cache is None:
            self._build_cache()

        culprits = []
        directory_path = os.path.abspath(directory_path)
        # Case-insensitive on Windows
        if os.name == 'nt':
            directory_path = directory_path.lower()
        
        for pid, info in self._process_cache.items():
            for fpath in info['paths']:
                compare_path = fpath.lower() if os.name == 'nt' else fpath
                if compare_path.startswith(directory_path):
                    culprits.append(ProcessRef(
                        pid=pid,
                        name=info['name'],
                        cmdline=info['cmdline']
                    ))
                    break  # Found one file match, move to next process
                
        return culprits
