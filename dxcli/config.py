import os
import json
from dataclasses import dataclass, asdict
from typing import List, Optional

@dataclass
class Config:
    log_patterns: List[str] = None
    stale_days: int = 30
    large_log_threshold_mb: int = 50
    telemetry_opt_in: Optional[bool] = None  # None = not asked, True = enabled, False = disabled

    def __post_init__(self):
        if self.log_patterns is None:
            self.log_patterns = ["*.log", "*.out", "*.err", "syslog", "messages"]

    @classmethod
    def load(cls) -> "Config":
        home = os.path.expanduser("~")
        config_path = os.path.join(home, ".dx", "config.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, "r") as f:
                    data = json.load(f)
                    return cls(**data)
            except:
                pass
        return cls()

    def save(self):
        home = os.path.expanduser("~")
        dx_dir = os.path.join(home, ".dx")
        os.makedirs(dx_dir, exist_ok=True)
        config_path = os.path.join(dx_dir, "config.json")
        with open(config_path, "w") as f:
            json.dump(asdict(self), f, indent=2)

# Global defaults
DEFAULT_CONFIG = Config.load()
