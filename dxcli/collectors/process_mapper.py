import psutil
import os
from typing import List, Dict, Optional, Any
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

    def get_application_accounting(self, directory_path: str) -> List[Dict[str, Any]]:
        """
        Aggregates total size of open files by process name within the given directory.
        Answers "Which application is using how much?"
        """
        if self._process_cache is None:
            self._build_cache()

        app_sizes = {}
        directory_path = os.path.abspath(directory_path)
        if os.name == 'nt':
            directory_path = directory_path.lower()
            
        for pid, info in self._process_cache.items():
            proc_name = info['name']
            proc_size = 0
            
            for fpath in info['paths']:
                compare_path = fpath.lower() if os.name == 'nt' else fpath
                if compare_path.startswith(directory_path):
                    try:
                        # Only count files that still exist and we can stat
                        proc_size += os.path.getsize(fpath)
                    except Exception:
                        pass
                        
            if proc_size > 0:
                if proc_name in app_sizes:
                    app_sizes[proc_name]['size'] += proc_size
                    app_sizes[proc_name]['pids'].append(pid)
                else:
                    app_sizes[proc_name] = {'size': proc_size, 'pids': [pid]}
                    
        # Convert to list and sort by size descending
        result = []
        for name, data in app_sizes.items():
            result.append({
                'name': name,
                'total_bytes': data['size'],
                'pids': data['pids']
            })
            
        result.sort(key=lambda x: x['total_bytes'], reverse=True)
        return result
