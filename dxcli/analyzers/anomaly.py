from typing import List, Dict, Optional
from ..store.database import Database
import time

class StatisticalAnomalyDetector:
    """
    Analyzes historical snapshots to fingerprint behavioral anomalies.
    """
    def __init__(self, db: Database):
        self.db = db

    def check_for_anomalies(self, path: str) -> Optional[str]:
        """
        Main entry point for fingerprinting. 
        Returns a descriptive string if an anomaly is found, else None.
        """
        history = self.db.get_dir_history(path, limit=5) # Last 5 points
        if len(history) < 3:
            return None
            
        # 1. Check for Log Bomb (Rapid, sudden, sustained acceleration)
        if self._is_log_bomb(history):
            return "LOG BOMB: Rapid, sustained write spike detected."
            
        # 2. Check for Persistent Leak (Small but never-ending growth)
        if self._is_leak(history):
            return "LEAK: Steady growth over several hours with no cleanup."
            
        return None

    def _is_log_bomb(self, history: List[Dict]) -> bool:
        # Simplistic check: If last growth is > 5x the average of previous points
        deltas = []
        for i in range(len(history)-1):
            deltas.append(max(0, history[i+1]['size_bytes'] - history[i]['size_bytes']))
            
        if len(deltas) < 2: return False
        
        last_delta = deltas[-1]
        avg_prev_delta = sum(deltas[:-1]) / len(deltas[:-1])
        
        # If it's a massive jump (e.g., 10x) and substantial (>10MB)
        if last_delta > (avg_prev_delta * 10) and last_delta > 1024 * 1024 * 10:
            return True
        return False

    def _is_leak(self, history: List[Dict]) -> bool:
        # Check if EVERY delta in the last 5 points is positive (no drops)
        deltas = []
        for i in range(len(history)-1):
            deltas.append(history[i+1]['size_bytes'] - history[i]['size_bytes'])
            
        if all(d > 0 for d in deltas) and len(deltas) >= 2:
            # If total growth over this time is > 1MB (avoid noise)
            total_change = sum(deltas)
            if total_change > 1024 * 1024:
                return True
        return False
