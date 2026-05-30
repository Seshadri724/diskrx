from typing import List, Dict
from ..store.models import DirNode
from ..collectors.process_mapper import ProcessMapper, ProcessRef

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
                    # Capture initial sizes
                    sizes1 = {}
                    for c in culprits:
                        if c.files:
                            for f in c.files:
                                try:
                                    if os.path.exists(f):
                                        sizes1[f] = os.path.getsize(f)
                                except Exception:
                                    pass
                                    
                    time.sleep(0.5)
                    
                    # Capture final sizes
                    sizes2 = {}
                    for c in culprits:
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
                        grew = False
                        if c.files:
                            for f in c.files:
                                if f in sizes1 and f in sizes2:
                                    if sizes2[f] > sizes1[f]:
                                        grew = True
                                        break
                        
                        confidence = "High" if grew else "Medium"
                        if best_culprit is None or (confidence == "High" and best_confidence == "Medium"):
                            best_culprit = c
                            best_confidence = confidence
                            
                    res["culprit"] = best_culprit
                    res["confidence"] = best_confidence
            
            results.append(res)
            
        return results

