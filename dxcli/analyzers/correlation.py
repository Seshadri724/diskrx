from typing import List, Dict, Optional
from ..collectors.process_mapper import ProcessMapper


def _get_pid_write_bytes(pid: int) -> Optional[int]:
    import os

    try:
        proc_io_path = f"/proc/{pid}/io"
        if os.path.exists(proc_io_path):
            with open(proc_io_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("write_bytes:"):
                        return int(line.split()[1])
    except Exception:
        pass

    try:
        import psutil

        proc = psutil.Process(pid)
        counters = proc.io_counters()
        if counters:
            return counters.write_bytes
    except Exception:
        pass

    return None


class CorrelationEngine:
    """
    Bridges the gap between the growth analyzer and the process list.
    """

    def __init__(self, db=None):
        self.mapper = ProcessMapper()
        self.db = db

    def correlate(self, growing_dirs: List[Dict]) -> List[Dict]:
        """
        Takes a list of growth results from RootCauseAnalyzer and attempts
        to attribute a PID to each growing directory by correlating with
        historical growth and current open files.
        """
        import time
        import os

        results = []
        for g in growing_dirs:
            res = g.copy()
            res["culprit"] = None

            # If it's growing, look for a culprit
            if g.get("trend") != "Stable" or g.get("velocity_per_day", 0) > 0:
                culprits = self.mapper.find_culprits(g["path"], write_only=True)

                if culprits:
                    # Capture initial sizes and write bytes
                    sizes1 = {}
                    proc_write1 = {}
                    for c in culprits:
                        wb = _get_pid_write_bytes(c.pid)
                        if wb is not None:
                            proc_write1[c.pid] = wb
                        if c.files:
                            for f in c.files:
                                try:
                                    if os.path.exists(f):
                                        sizes1[f] = os.path.getsize(f)
                                except Exception:
                                    pass

                    time.sleep(0.5)

                    # Capture final sizes and write bytes
                    sizes2 = {}
                    proc_write2 = {}
                    for c in culprits:
                        wb = _get_pid_write_bytes(c.pid)
                        if wb is not None:
                            proc_write2[c.pid] = wb
                        if c.files:
                            for f in c.files:
                                try:
                                    if os.path.exists(f):
                                        sizes2[f] = os.path.getsize(f)
                                except Exception:
                                    pass

                    best_culprit = None
                    best_confidence = "Medium"

                    for c in culprits:
                        grew_file = False
                        if c.files:
                            for f in c.files:
                                if f in sizes1 and f in sizes2:
                                    if sizes2[f] > sizes1[f]:
                                        grew_file = True
                                        break

                        grew_proc = False
                        if c.pid in proc_write1 and c.pid in proc_write2:
                            if proc_write2[c.pid] > proc_write1[c.pid]:
                                grew_proc = True

                        confidence = "High" if (grew_file or grew_proc) else "Medium"
                        if best_culprit is None or (
                            confidence == "High" and best_confidence == "Medium"
                        ):
                            best_culprit = c
                            best_confidence = confidence

                    res["culprit"] = best_culprit
                    res["confidence"] = best_confidence

            results.append(res)

        return results
