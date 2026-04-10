from ..store.database import Database
from ..store.models import GrowthRate
from typing import Optional
import numpy as np
import warnings

class GrowthTracker:
    """
    Calculates daily growth rate per directory based on historical SQLite snapshots.
    """
    def __init__(self, db: Database):
        self.db = db

    def get_growth_rate(self, path: str, days: int = 7) -> Optional[GrowthRate]:
        history = self.db.get_dir_history(path, days_back=days)
        if len(history) < 2:
            return None # Not enough history

        # Extract timestamps and sizes
        timestamps = np.array([h['timestamp'] for h in history])
        sizes = np.array([h['size_bytes'] for h in history])
        
        # Linear regression: size = m * timestamp + c
        # We want m (bytes per second)
        # Polyfit returns [m, c] for deg=1
        with warnings.catch_warnings():
            warnings.simplefilter('error', np.exceptions.RankWarning)
            try:
                m, _ = np.polyfit(timestamps, sizes, 1)
            except np.exceptions.RankWarning:
                return None  # Data too noisy/flat for reliable regression
        
        # Convert bytes per second to bytes per day
        bytes_per_day = m * 86400.0
        
        return GrowthRate(path=path, bytes_per_day=bytes_per_day)

    def get_partition_growth_rate(self, mountpoint: str, days: int = 7) -> float:
        """Returns bytes per day growth for a whole partition."""
        history = self.db.get_history(mountpoint, days_back=days)
        if len(history) < 2:
            return 0.0

        timestamps = np.array([h['timestamp'] for h in history])
        sizes = np.array([h['used_bytes'] for h in history])
        
        with warnings.catch_warnings():
            warnings.simplefilter('error', np.exceptions.RankWarning)
            try:
                m, _ = np.polyfit(timestamps, sizes, 1)
            except np.exceptions.RankWarning:
                return 0.0
        return m * 86400.0
