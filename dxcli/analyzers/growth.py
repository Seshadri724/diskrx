from ..store.database import Database
from ..store.models import GrowthRate
from typing import Optional, Tuple
import numpy as np
import warnings

# numpy moved RankWarning to numpy.exceptions in 1.25 and removed the
# top-level numpy.RankWarning alias in 2.0. Resolve it in a version-agnostic
# way so dxcli works across the declared numpy>=1.24 support range.
try:
    from numpy.exceptions import RankWarning  # numpy >= 1.25
except ImportError:  # pragma: no cover - exercised only on numpy < 1.25
    from numpy import RankWarning  # numpy < 1.25

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
            warnings.simplefilter('error', RankWarning)
            try:
                m, _ = np.polyfit(timestamps, sizes, 1)
            except RankWarning:
                return None  # Data too noisy/flat for reliable regression
        
        # Convert bytes per second to bytes per day
        bytes_per_day = m * 86400.0
        
        return GrowthRate(path=path, bytes_per_day=bytes_per_day)

    def get_partition_growth_details(self, mountpoint: str, days: int = 7) -> Tuple[float, float]:
        """Returns (bytes_per_day_growth, s_growth) for a whole partition using residuals."""
        history = self.db.get_history(mountpoint, days_back=days)
        if len(history) < 2:
            return 0.0, 0.0

        timestamps = np.array([h['timestamp'] for h in history])
        sizes = np.array([h['used_bytes'] for h in history])
        
        with warnings.catch_warnings():
            warnings.simplefilter('error', RankWarning)
            try:
                p, residuals, rank, singular_values, rcond = np.polyfit(timestamps, sizes, 1, full=True)
                m = p[0]
                ssr = residuals[0] if len(residuals) > 0 else 0.0
                n = len(timestamps)
                if n > 2:
                    s_e = np.sqrt(ssr / (n - 2))
                    x_mean = np.mean(timestamps)
                    sum_x_dev_sq = np.sum((timestamps - x_mean) ** 2)
                    if sum_x_dev_sq > 0:
                        s_growth_sec = s_e / np.sqrt(sum_x_dev_sq)
                        s_growth = s_growth_sec * 86400.0
                    else:
                        s_growth = 0.0
                else:
                    s_growth = 0.0
            except Exception:
                return 0.0, 0.0
        return m * 86400.0, s_growth

    def get_partition_growth_rate(self, mountpoint: str, days: int = 7) -> float:
        """Returns bytes per day growth for a whole partition."""
        return self.get_partition_growth_details(mountpoint, days)[0]
