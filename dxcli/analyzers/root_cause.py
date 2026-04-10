from typing import List, Dict
from ..store.models import DirNode
from .growth import GrowthTracker
from ..store.database import Database

class RootCauseAnalyzer:
    """
    Ranks directories by absolute growth velocity (change) rather than sheer size.
    """
    def __init__(self, db: Database):
        self.tracker = GrowthTracker(db)

    def attribute_cause(self, top_dirs: List[DirNode], days: int = 7) -> List[Dict]:
        """
        Takes the top N directories, queries their historical growth, 
        and sorts them by who is growing the fastest.
        """
        results = []
        for d in top_dirs:
            rate = self.tracker.get_growth_rate(d.path, days=days)
            velocity = rate.bytes_per_day if rate else 0.0
            
            # Simple trend string
            trend_str = "Stable"
            if velocity > 1024 * 1024 * 50: # >50MB/day
                trend_str = "Spiking ↑"
            elif velocity > 1024 * 1024 * 5: # >5MB/day
                trend_str = "Growing ↗"
            elif velocity < -1024 * 1024:
                trend_str = "Shrinking ↘"
                
            results.append({
                "path": d.path,
                "current_size": d.size_bytes,
                "velocity_per_day": velocity,
                "trend": trend_str
            })
            
        # Sort by fastest growing first
        results.sort(key=lambda x: x["velocity_per_day"], reverse=True)
        return results
