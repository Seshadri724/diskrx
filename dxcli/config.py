from dataclasses import dataclass
from typing import List

@dataclass
class Config:
    log_patterns: List[str] = None
    stale_days: int = 30
    large_log_threshold_mb: int = 50

    def __post_init__(self):
        if self.log_patterns is None:
            self.log_patterns = ["*.log", "*.out", "*.err", "syslog", "messages"]

# Global defaults
DEFAULT_CONFIG = Config()
