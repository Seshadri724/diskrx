import time
from typing import Optional
import numpy as np
from .growth import GrowthTracker
from ..store.models import PredictionResult, Partition
from ..store.database import Database


def compute_ewma_growth(history: list, half_life_days: float) -> float:
    if len(history) < 2:
        return 0.0
    ewma = 0.0
    initialized = False
    half_life_seconds = half_life_days * 86400.0
    lam = 0.6931471805599453 / half_life_seconds  # ln(2) / half-life
    
    for i in range(1, len(history)):
        dt = history[i]['timestamp'] - history[i-1]['timestamp']
        if dt <= 0:
            continue
        dy = history[i]['used_bytes'] - history[i-1]['used_bytes']
        growth = (dy / dt) * 86400.0
        
        if not initialized:
            ewma = growth
            initialized = True
        else:
            alpha = 1.0 - np.exp(-dt * lam)
            ewma = alpha * growth + (1.0 - alpha) * ewma
            
    return ewma


class DiskPredictor:
    """
    Linear regression on historical usage data to determine time-to-full.
    """
    def __init__(self, db: Database):
        self.tracker = GrowthTracker(db)

    def predict_full_date(self, partition: Partition) -> Optional[PredictionResult]:
        history = self.tracker.db.get_history(partition.mountpoint, days_back=30, limit=100)
        daily_growth, s_growth = self.tracker.get_partition_growth_details(partition.mountpoint)
        
        if daily_growth <= 1024 * 1024:  # Less than 1MB/day is considered roughly stable/static
            return PredictionResult(
                path=partition.mountpoint,
                date_full_timestamp=None,
                days_until_full=None,
                current_capacity_bytes=partition.total_bytes,
                current_usage_bytes=partition.used_bytes,
                daily_growth_bytes=daily_growth,
                is_accelerating=False,
                days_until_full_low=None,
                days_until_full_high=None,
                hint=None
            )

        remaining_bytes = partition.total_bytes - partition.used_bytes
        days_until_full = remaining_bytes / daily_growth
        
        # 1. Compute EWMA-based acceleration
        ewma_recent = compute_ewma_growth(history, 1.0)
        ewma_baseline = compute_ewma_growth(history, 7.0)
        
        is_accelerating = False
        if ewma_recent > 0:
            if ewma_baseline <= 0 or ewma_recent > 1.2 * ewma_baseline:
                is_accelerating = True
        
        # 2. Compute confidence bands
        growth_low = daily_growth - 1.96 * s_growth
        growth_high = daily_growth + 1.96 * s_growth
        
        days_until_full_low = None
        days_until_full_high = None
        
        if growth_high > 0:
            days_until_full_low = remaining_bytes / growth_high
        if growth_low > 0:
            days_until_full_high = remaining_bytes / growth_low

        # 3. Handle log rotation case
        hint = None
        recent_24h = [h for h in history if h['timestamp'] >= time.time() - 86400]
        if len(recent_24h) >= 2:
            x_24h = np.array([h['timestamp'] for h in recent_24h])
            y_24h = np.array([h['used_bytes'] for h in recent_24h])
            try:
                p_24h = np.polyfit(x_24h, y_24h, 1)
                if p_24h[0] < 0:
                    is_accelerating = False
                    hint = "rotated recently"
            except Exception:
                pass
        
        return PredictionResult(
            path=partition.mountpoint,
            date_full_timestamp=time.time() + (days_until_full * 86400),
            days_until_full=days_until_full,
            current_capacity_bytes=partition.total_bytes,
            current_usage_bytes=partition.used_bytes,
            daily_growth_bytes=daily_growth,
            is_accelerating=is_accelerating,
            days_until_full_low=days_until_full_low,
            days_until_full_high=days_until_full_high,
            hint=hint
        )
