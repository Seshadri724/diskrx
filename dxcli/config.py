import logging
import os
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)


@dataclass
class TargetConfig:
    path: str
    alert_threshold: Optional[str] = None
    interval: Optional[int] = None


@dataclass
class Config:
    log_patterns: List[str] = field(
        default_factory=lambda: ["*.log", "*.out", "*.err", "syslog", "messages"]
    )
    stale_days: int = 30
    large_log_threshold_mb: int = 50
    telemetry_opt_in: bool = False
    targets: Dict[str, TargetConfig] = field(default_factory=dict)
    default_target: Optional[str] = None

    @classmethod
    def load(cls) -> "Config":
        """Load config from disk, returning defaults on any failure.

        Failures are logged as warnings so operators know their config was not
        applied — we do not silently degrade without notice.
        """
        try:
            from .state import get_state_dir

            config_path = os.path.join(get_state_dir(), "config.yaml")
        except Exception as e:
            logger.warning("Could not resolve state directory: %s. Using defaults.", e)
            return cls()

        if not os.path.exists(config_path):
            return cls()

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)

            if not data:
                return cls()

            # Convert raw target dicts to TargetConfig objects
            raw_targets = data.get("targets", {}) or {}
            parsed_targets: Dict[str, TargetConfig] = {}
            for name, t_data in raw_targets.items():
                if isinstance(t_data, dict):
                    try:
                        parsed_targets[name] = TargetConfig(**t_data)
                    except TypeError as e:
                        logger.warning("Skipping malformed target '%s': %s", name, e)
                else:
                    logger.warning(
                        "Skipping target '%s': expected a mapping, got %s",
                        name,
                        type(t_data),
                    )
            data["targets"] = parsed_targets

            # Remove keys not in the dataclass to avoid TypeError
            known_fields = {f.name for f in cls.__dataclass_fields__.values()}
            filtered = {k: v for k, v in data.items() if k in known_fields}

            return cls(**filtered)

        except yaml.YAMLError as e:
            logger.warning(
                "config.yaml is malformed (%s). Using defaults. Fix the file to apply your config.",
                e,
            )
            print(
                f"[dxcli] WARNING: config.yaml is malformed: {e}. Using defaults.",
                file=sys.stderr,
            )
            return cls()
        except Exception as e:
            logger.warning("Unexpected config load error: %s. Using defaults.", e)
            return cls()

    def save(self) -> None:
        from .state import get_state_dir, atomic_write

        config_path = os.path.join(get_state_dir(), "config.yaml")

        data = {
            "log_patterns": self.log_patterns,
            "stale_days": self.stale_days,
            "large_log_threshold_mb": self.large_log_threshold_mb,
            "telemetry_opt_in": self.telemetry_opt_in,
            "default_target": self.default_target,
            "targets": {
                name: {k: v for k, v in t.__dict__.items() if v is not None}
                for name, t in self.targets.items()
            },
        }
        yaml_content = yaml.safe_dump(data, default_flow_style=False)
        atomic_write(config_path, yaml_content, mode=0o600)


_DEFAULT_CONFIG = None


def get_config() -> "Config":
    global _DEFAULT_CONFIG
    if _DEFAULT_CONFIG is None:
        _DEFAULT_CONFIG = Config.load()
    return _DEFAULT_CONFIG
