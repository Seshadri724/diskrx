from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


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
    days_until_full_low: Optional[float] = None
    days_until_full_high: Optional[float] = None
    hint: Optional[str] = None
    confidence: str = "medium"  # 'high', 'medium', 'low'
    r_squared: Optional[float] = None
    data_points: int = 0


@dataclass
class Prescription:
    """Represents an actionable recommendation from the analysis engine."""

    id: str
    name: str
    description: str
    category: str
    severity: str  # 'low', 'medium', 'high', 'critical'
    size_savings_bytes: int
    action_type: Optional[str] = None  # 'delete', 'create_file', 'command'
    target_path: Optional[str] = None
    template: Optional[str] = None  # Content to write for 'create_file'
    risk: str = "low"  # 'low', 'medium', 'high'
    is_safe: bool = True


@dataclass
class PolicyViolation:
    rule_name: str
    path: str
    message: str
    severity: str  # 'info', 'warning', 'critical'
    suggested_action: str


@dataclass
class RiskSignal:
    """A single explainable storage risk finding for fleet telemetry."""

    id: str
    severity: str
    category: str
    message: str
    path: Optional[str] = None
    owner: Optional[str] = None
    score: int = 0


@dataclass
class CollectorError:
    """A non-fatal collector failure included in telemetry."""

    collector: str
    message: str
    path: Optional[str] = None
    error_type: str = "unknown"
    partial: bool = False


@dataclass
class HostSnapshot:
    """Fleet-ready telemetry emitted by a local dxcli agent run."""

    schema_version: str
    host_id: str
    hostname: str
    platform: str
    timestamp: float
    scan_path: str
    partitions: List[Partition]
    top_dirs: List[DirNode]
    logs: List[UnrotatedLog]
    stales: List[StaleFile]
    policy_violations: List[PolicyViolation]
    risk_signals: List[RiskSignal]
    risk_score: int
    risk_level: str
    collector_errors: List[CollectorError] = field(default_factory=list)


@dataclass
class DiagnosticSnapshot:
    """Unified result of a full diagnostic run.

    Every consumer (CLI, TUI, watch, serve, enterprise, CI) receives
    exactly this structure from the shared engine, ensuring consistent
    results across all output paths.
    """

    path: str
    partition: Optional[Partition]
    top_dirs: List[DirNode]
    logs: List[UnrotatedLog]
    stale_files: List[StaleFile]
    docker: Optional[Dict[str, Any]] = None
    trends: List[Dict[str, Any]] = field(default_factory=list)
    prediction: Optional[PredictionResult] = None
    anomalies: List[str] = field(default_factory=list)
    policy_violations: List[PolicyViolation] = field(default_factory=list)
    prescriptions: List[Prescription] = field(default_factory=list)
    app_accounting: List[Dict[str, Any]] = field(default_factory=list)
    active_writers: List[Dict[str, Any]] = field(default_factory=list)
    classification: Optional[Dict[str, int]] = None
    collector_errors: List[CollectorError] = field(default_factory=list)
    timestamp: float = 0.0
