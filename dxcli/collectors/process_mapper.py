import psutil
import os
from typing import List, Dict, Optional, Any, Tuple
from dataclasses import dataclass


@dataclass
class ProcessRef:
    pid: int
    name: str
    cmdline: List[str]
    mode: str = "unknown"
    files: List[str] = None


SYSTEM_PROCESS_NAMES = {
    "system",
    "idle",
    "registry",
    "memory compression",
    "smss.exe",
    "csrss.exe",
    "wininit.exe",
    "services.exe",
    "lsass.exe",
    "svchost.exe",
    "fontdrvhost.exe",
    "wuauclt.exe",
    "searchindexer.exe",
    "spoolsv.exe",
    "ctfmon.exe",
    "sihost.exe",
    "systemsettings.exe",
    "securityhealthservice.exe",
    "audiodg.exe",
    "conhost.exe",
}

DEV_APP_KEYWORDS = [
    "python",
    "node",
    "java",
    "go",
    "rust",
    "git",
    "docker",
    "code",
    "chrome",
    "firefox",
    "idea",
    "webstorm",
    "pycharm",
    "clion",
    "wsl",
    "bash",
    "zsh",
    "powershell",
    "cmd",
    "postgres",
    "mysql",
    "redis",
    "nginx",
    "apache",
    "cargo",
    "npm",
    "yarn",
    "pnpm",
    "pip",
    "dotnet",
    "ruby",
    "php",
]


class ProcessMapper:
    """
    Identifies which processes have open file handles in specific directories.
    Uses a scan-once cache to avoid repeated expensive process iteration.
    """

    def __init__(self):
        self._process_cache: Optional[Dict[int, List[str]]] = None

    def _inspect_process(self, proc) -> Optional[Tuple[int, Dict[str, Any]]]:
        try:
            pid = proc.info["pid"]
            if pid <= 4:
                return None
            name = (proc.info["name"] or "").lower()
            if name in SYSTEM_PROCESS_NAMES or any(
                sys_p in name
                for sys_p in [
                    "system",
                    "svchost",
                    "service",
                    "helper",
                    "agent",
                    "wmiprv",
                    "search",
                ]
            ):
                return None

            # Fast filter: only inspect processes that are potential dev/user applications
            if not any(kw in name for kw in DEV_APP_KEYWORDS):
                return None

            files = proc.open_files()
            if files:
                paths = [f.path for f in files]
                modes = [getattr(f, "mode", "unknown") for f in files]
                try:
                    cmd = proc.cmdline()
                except Exception:
                    cmd = []
                return pid, {
                    "name": proc.info["name"],
                    "cmdline": cmd,
                    "paths": paths,
                    "modes": modes,
                }
        except Exception:
            return None
        return None

    def _build_cache(self):
        """Scan processes in parallel with strict process limit and timeout."""
        self._process_cache = {}
        import concurrent.futures

        try:
            procs = list(psutil.process_iter(["pid", "name"]))
        except Exception:
            return

        # Filter candidate user/developer processes
        candidates = []
        for p in procs:
            try:
                pid = p.info["pid"]
                if pid <= 4:
                    continue
                name = (p.info["name"] or "").lower()
                if name in SYSTEM_PROCESS_NAMES or any(
                    sys_p in name
                    for sys_p in [
                        "system",
                        "svchost",
                        "service",
                        "helper",
                        "agent",
                        "wmiprv",
                        "search",
                    ]
                ):
                    continue
                if any(kw in name for kw in DEV_APP_KEYWORDS):
                    candidates.append(p)
            except Exception:
                continue

        # Cap candidate inspection to top 8 active developer processes for sub-second runtime
        candidates = candidates[:8]

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)
        try:
            futures = [executor.submit(self._inspect_process, p) for p in candidates]
            for future in concurrent.futures.as_completed(futures, timeout=0.5):
                try:
                    res = future.result()
                    if res:
                        pid, info = res
                        self._process_cache[pid] = info
                except Exception:
                    continue
        except Exception:
            pass
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def find_culprits(
        self, directory_path: str, write_only: bool = True
    ) -> List[ProcessRef]:
        """
        Returns a list of processes that currently have files open in the target directory.
        Builds cache on first call, reuses for subsequent calls.
        """
        if self._process_cache is None:
            self._build_cache()

        culprits = []
        directory_path = os.path.abspath(directory_path)
        # Case-insensitive on Windows
        if os.name == "nt":
            directory_path = directory_path.lower()
        # Ensure path boundary check (avoid /var/log matching /var/logbomb)
        dir_with_sep = directory_path.rstrip(os.sep) + os.sep

        for pid, info in self._process_cache.items():
            matched_files = []
            matched_modes = []
            for fpath, fmode in zip(info["paths"], info["modes"]):
                compare_path = fpath.lower() if os.name == "nt" else fpath
                if compare_path == directory_path or compare_path.startswith(
                    dir_with_sep
                ):
                    is_writer = False
                    if fmode == "unknown":
                        is_writer = True
                    else:
                        if "w" in fmode or "a" in fmode or "+" in fmode:
                            is_writer = True

                    if not write_only or is_writer:
                        matched_files.append(fpath)
                        matched_modes.append(fmode)

            if matched_files:
                if all(m == "unknown" for m in matched_modes):
                    mode_tag = "unavailable"
                elif any("w" in m or "a" in m or "+" in m for m in matched_modes):
                    mode_tag = "write"
                else:
                    mode_tag = "read"

                culprits.append(
                    ProcessRef(
                        pid=pid,
                        name=info["name"],
                        cmdline=info["cmdline"],
                        mode=mode_tag,
                        files=matched_files,
                    )
                )

        return culprits

    def get_application_accounting(
        self, directory_path: str, write_only: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Aggregates total size of open files by process name within the given directory.
        Answers "Which application is using how much?"
        """
        if self._process_cache is None:
            self._build_cache()

        app_sizes = {}
        directory_path = os.path.abspath(directory_path)
        if os.name == "nt":
            directory_path = directory_path.lower()
        # Ensure path boundary check (avoid /var/log matching /var/logbomb)
        dir_with_sep = directory_path.rstrip(os.sep) + os.sep

        for pid, info in self._process_cache.items():
            proc_name = info["name"]
            proc_size = 0

            for fpath, fmode in zip(info["paths"], info["modes"]):
                compare_path = fpath.lower() if os.name == "nt" else fpath
                if compare_path == directory_path or compare_path.startswith(
                    dir_with_sep
                ):
                    is_writer = False
                    if fmode == "unknown":
                        is_writer = True
                    else:
                        if "w" in fmode or "a" in fmode or "+" in fmode:
                            is_writer = True

                    if not write_only or is_writer:
                        try:
                            # Only count files that still exist and we can stat
                            proc_size += os.path.getsize(fpath)
                        except Exception:
                            pass

            if proc_size > 0:
                if proc_name in app_sizes:
                    app_sizes[proc_name]["size"] += proc_size
                    app_sizes[proc_name]["pids"].append(pid)
                else:
                    app_sizes[proc_name] = {"size": proc_size, "pids": [pid]}

        # Convert to list and sort by size descending
        result = []
        for name, data in app_sizes.items():
            result.append(
                {"name": name, "total_bytes": data["size"], "pids": data["pids"]}
            )

        result.sort(key=lambda x: x["total_bytes"], reverse=True)
        return result

    def get_active_writers(
        self, directory_path: str, interval: float = 1.0
    ) -> List[Dict[str, Any]]:
        """
        Samples open files over an interval to identify which processes are
        actively writing (throughput detection).
        """
        import time

        if self._process_cache is None:
            self._build_cache()

        directory_path = os.path.abspath(directory_path)
        if os.name == "nt":
            directory_path = directory_path.lower()
        # Ensure path boundary check (avoid /var/log matching /var/logbomb)
        dir_with_sep = directory_path.rstrip(os.sep) + os.sep

        # Phase 1: Capture initial sizes
        initial_stats = {}
        for pid, info in self._process_cache.items():
            for fpath in info["paths"]:
                compare_path = fpath.lower() if os.name == "nt" else fpath
                if compare_path == directory_path or compare_path.startswith(
                    dir_with_sep
                ):
                    try:
                        initial_stats[(pid, fpath)] = os.path.getsize(fpath)
                    except Exception:
                        continue

        if not initial_stats:
            return []

        # Wait for interval
        time.sleep(interval)

        # Phase 2: Capture final sizes and calculate delta
        active_writers = {}
        for (pid, fpath), initial_size in initial_stats.items():
            try:
                final_size = os.path.getsize(fpath)
                delta = final_size - initial_size
                if delta > 0:
                    proc_name = self._process_cache[pid]["name"]
                    if pid not in active_writers:
                        active_writers[pid] = {
                            "name": proc_name,
                            "throughput_bps": delta / interval,
                            "files": [fpath],
                        }
                    else:
                        active_writers[pid]["throughput_bps"] += delta / interval
                        active_writers[pid]["files"].append(fpath)
            except Exception:
                continue

        # Convert to sorted list
        result = []
        for pid, data in active_writers.items():
            result.append(
                {
                    "pid": pid,
                    "name": data["name"],
                    "throughput_bps": data["throughput_bps"],
                    "files": data["files"],
                }
            )

        result.sort(key=lambda x: x["throughput_bps"], reverse=True)
        return result
