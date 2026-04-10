from typing import List, Dict
from ..store.models import DirNode
from ..collectors.process_mapper import ProcessMapper, ProcessRef

class CorrelationEngine:
    """
    Bridges the gap between the growth analyzer and the process list.
    """
    def __init__(self):
        self.mapper = ProcessMapper()

    def correlate(self, growing_dirs: List[Dict]) -> List[Dict]:
        """
        Takes a list of growth results from RootCauseAnalyzer and attempts 
        to attribute a PID to each growing directory.
        """
        results = []
        for g in growing_dirs:
            # We only look for culprits if the trend is not "Stable"
            res = g.copy()
            res["culprit"] = None
            
            if g["trend"] != "Stable":
                culprits = self.mapper.find_culprits(g["path"])
                if culprits:
                    # Pick the first one or prioritize by name match?
                    # For now just the first one found
                    res["culprit"] = culprits[0]
            
            results.append(res)
            
        return results
