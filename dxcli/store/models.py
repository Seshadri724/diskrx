from dataclasses import dataclass
from typing import List, Optional

@dataclass
class Partition:
    device: str
    mountpoint: str
    fstype: str
    total_bytes: int
    used_bytes: int
    free_bytes: int

    @property
    def usage_percent(self) -> float:
        if self.total_bytes == 0:
            return 0.0
        return (self.used_bytes / self.total_bytes) * 100.0

@dataclass
class DirNode:
    path: str
    size_bytes: int
    file_count: int

@dataclass
class UnrotatedLog:
    path: str
    size_bytes: int
    last_modified_timestamp: float
    has_logrotate_config: bool

@dataclass
class StaleFile:
    path: str
    size_bytes: int
    last_accessed_timestamp: float
    days_stale: float

@dataclass
class GrowthRate:
    path: str
    bytes_per_day: float

@dataclass
class PredictionResult:
    path: str
    date_full_timestamp: Optional[float]
    days_until_full: Optional[float]
    current_capacity_bytes: int
    current_usage_bytes: int
    daily_growth_bytes: float
    is_accelerating: bool

@dataclass
class Prescription:
    id: str
    name: str
    template: str
    risk: str
    size_savings_bytes: int
