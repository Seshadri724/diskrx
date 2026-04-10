import time
from typing import Optional
from .growth import GrowthTracker
from ..store.models import PredictionResult, Partition
from ..store.database import Database

class DiskPredictor:
    """
    Linear regression on historical usage data to determine time-to-full.
    """
    def __init__(self, db: Database):
        self.tracker = GrowthTracker(db)

    def predict_full_date(self, partition: Partition) -> Optional[PredictionResult]:
        daily_growth = self.tracker.get_partition_growth_rate(partition.mountpoint)
        
        if daily_growth <= 1024 * 1024:  # Less than 1MB/day is considered roughly stable/static
            return PredictionResult(
                path=partition.mountpoint,
                date_full_timestamp=None,
                days_until_full=None,
                current_capacity_bytes=partition.total_bytes,
                current_usage_bytes=partition.used_bytes,
                daily_growth_bytes=daily_growth,
                is_accelerating=False
            )

        remaining_bytes = partition.total_bytes - partition.used_bytes
        days_until_full = remaining_bytes / daily_growth
        
        # Super simple acceleration check (compare last 3 days vs last 7 days)
        short_growth = self.tracker.get_partition_growth_rate(partition.mountpoint, days=3)
        long_growth = self.tracker.get_partition_growth_rate(partition.mountpoint, days=7)
        is_accelerating = short_growth > (long_growth * 1.2) # 20% spike is accelerating
        
        return PredictionResult(
            path=partition.mountpoint,
            date_full_timestamp=time.time() + (days_until_full * 86400),
            days_until_full=days_until_full,
            current_capacity_bytes=partition.total_bytes,
            current_usage_bytes=partition.used_bytes,
            daily_growth_bytes=daily_growth,
            is_accelerating=is_accelerating
        )
