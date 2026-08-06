import time
from typing import Optional

import numpy as np

from ..store.database import Database
from ..store.models import Partition, PredictionResult
from .growth import GrowthTracker


def compute_ewma_growth(history: list, half_life_days: float) -> float:
    if len(history) < 2:
        return 0.0
    ewma = 0.0
    initialized = False
    half_life_seconds = half_life_days * 86400.0
    lam = 0.6931471805599453 / half_life_seconds  # ln(2) / half-life

    for i in range(1, len(history)):
        dt = history[i]["timestamp"] - history[i - 1]["timestamp"]
        if dt <= 0:
            continue
        dy = history[i]["used_bytes"] - history[i - 1]["used_bytes"]
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
    Linear regression on historical usage data to determine time-to-full
    and assess prediction confidence and variance metrics.
    """

    def __init__(self, db: Database):
        self.tracker = GrowthTracker(db)

    def predict_full_date(self, partition: Partition) -> Optional[PredictionResult]:
        if not partition or partition.total_bytes <= 0:
            return None

        hint = None
        history = self.tracker.db.get_history(
            partition.mountpoint, days_back=30, limit=100
        )
        data_points = len(history)

        daily_growth, s_growth = self.tracker.get_partition_growth_details(
            partition.mountpoint
        )

        remaining_bytes = partition.total_bytes - partition.used_bytes

        # Calculate R^2 coefficient of determination
        r_squared = None
        if data_points >= 3:
            try:
                x = np.array([h["timestamp"] for h in history], dtype=float)
                x = x - x[0]
                y = np.array([h["used_bytes"] for h in history], dtype=float)
                if len(np.unique(x)) > 1:
                    p = np.polyfit(x, y, 1)
                    y_pred = p[0] * x + p[1]
                    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
                    ss_res = float(np.sum((y - y_pred) ** 2))
                    if ss_tot > 0:
                        r_squared = max(0.0, float(1.0 - (ss_res / ss_tot)))
                    else:
                        r_squared = 1.0
            except Exception:
                r_squared = None

        if remaining_bytes <= 0:
            now = time.time()
            return PredictionResult(
                path=partition.mountpoint,
                date_full_timestamp=now,
                days_until_full=0.0,
                current_capacity_bytes=partition.total_bytes,
                current_usage_bytes=partition.used_bytes,
                daily_growth_bytes=max(0.0, daily_growth),
                is_accelerating=False,
                days_until_full_low=0.0,
                days_until_full_high=0.0,
                hint="already full",
                confidence="high",
                r_squared=1.0,
                data_points=data_points,
            )

        if data_points < 3:
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
                hint="insufficient history",
                confidence="low",
                r_squared=r_squared,
                data_points=data_points,
            )

        # Check log rotation case
        recent_24h = [h for h in history if h["timestamp"] >= time.time() - 86400]
        if len(recent_24h) >= 2:
            x_24h = np.array([h["timestamp"] for h in recent_24h], dtype=float)
            x_24h = x_24h - x_24h[0]
            y_24h = np.array([h["used_bytes"] for h in recent_24h], dtype=float)
            if len(np.unique(x_24h)) > 1:
                try:
                    p_24h = np.polyfit(x_24h, y_24h, 1)
                    if p_24h[0] < 0:
                        hint = "rotated recently"
                except Exception:
                    pass

        if (
            daily_growth <= 1024 * 1024
        ):  # Less than 1MB/day is considered roughly static
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
                hint=hint or "stable",
                confidence="high" if (r_squared and r_squared >= 0.8) else "medium",
                r_squared=r_squared,
                data_points=data_points,
            )

        if daily_growth > 0 and s_growth > 0.5 * daily_growth:
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
                hint=hint or "high variance",
                confidence="low",
                r_squared=r_squared,
                data_points=data_points,
            )

        days_until_full = remaining_bytes / daily_growth

        # 1. Compute EWMA-based acceleration
        ewma_recent = compute_ewma_growth(history, 1.0)
        ewma_baseline = compute_ewma_growth(history, 7.0)

        is_accelerating = False
        if hint == "rotated recently":
            is_accelerating = False
        elif ewma_recent > 0:
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

        # 4. Assess overall prediction confidence
        if r_squared is not None and r_squared >= 0.85 and data_points >= 5:
            confidence = "high"
        elif r_squared is not None and r_squared >= 0.50:
            confidence = "medium"
        else:
            confidence = "low"

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
            hint=hint,
            confidence=confidence,
            r_squared=r_squared,
            data_points=data_points,
        )
