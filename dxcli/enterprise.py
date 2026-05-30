import os
import platform
import socket
import time
import uuid
from typing import List

from .policy_engine import PolicyEngine
from .store.models import CollectorError, DirNode, HostSnapshot, Partition, PolicyViolation, RiskSignal


SCHEMA_VERSION = "dxcli.host_snapshot.v1"
AGENT_ID_FILE = "agent_id"


def risk_level(score: int) -> str:
    if score >= 90:
        return "critical"
    if score >= 65:
        return "high"
    if score >= 35:
        return "warning"
    return "healthy"


def score_partition(partition: Partition) -> RiskSignal:
    usage = partition.usage_percent
    if usage >= 95:
        severity = "critical"
        score = 100
    elif usage >= 90:
        severity = "critical"
        score = 90
    elif usage >= 80:
        severity = "high"
        score = 70
    elif usage >= 70:
        severity = "warning"
        score = 40
    else:
        severity = "info"
        score = 0

    return RiskSignal(
        id=f"partition:{partition.mountpoint}",
        severity=severity,
        category="capacity",
        message=f"{partition.mountpoint} is {usage:.1f}% full",
        path=partition.mountpoint,
        score=score,
    )


def score_policy_violation(violation: PolicyViolation) -> RiskSignal:
    severity_scores = {
        "critical": 95,
        "warning": 55,
        "info": 20,
    }
    score = severity_scores.get(violation.severity, 40)
    return RiskSignal(
        id=f"policy:{violation.rule_name}:{violation.path}",
        severity=violation.severity,
        category="policy",
        message=violation.message,
        path=violation.path,
        score=score,
    )


def score_large_directory(node: DirNode, scan_path: str) -> RiskSignal:
    gb = node.size_bytes / (1024 ** 3)
    if gb >= 100:
        severity = "high"
        score = 70
    elif gb >= 25:
        severity = "warning"
        score = 40
    else:
        severity = "info"
        score = 0

    return RiskSignal(
        id=f"directory:{node.path}",
        severity=severity,
        category="growth-source",
        message=f"{node.path} is a top storage consumer under {scan_path}",
        path=node.path,
        score=score,
    )


def build_risk_signals(
    partitions: List[Partition],
    top_dirs: List[DirNode],
    policy_violations: List[PolicyViolation],
    scan_path: str,
) -> List[RiskSignal]:
    signals: List[RiskSignal] = []
    signals.extend(signal for signal in (score_partition(partition) for partition in partitions) if signal.score > 0)
    signals.extend(score_policy_violation(violation) for violation in policy_violations)
    signals.extend(
        signal
        for signal in (score_large_directory(node, scan_path) for node in top_dirs[:5])
        if signal.score > 0
    )
    signals.sort(key=lambda signal: signal.score, reverse=True)
    return signals


class AgentSnapshotCollector:
    """Collects a fleet-ready local host snapshot for a future control plane."""

    def __init__(self, provider=None, policy_engine: PolicyEngine = None):
        if provider is None:
            from .platform import provider as platform_provider

            provider = platform_provider
        self.provider = provider
        self.policy_engine = policy_engine or PolicyEngine()

    def _host_id(self) -> str:
        from .state import atomic_write, get_state_dir

        agent_id_path = os.path.join(get_state_dir(), AGENT_ID_FILE)
        try:
            with open(agent_id_path, "r", encoding="utf-8") as handle:
                agent_id = handle.read().strip()
            uuid.UUID(agent_id)
            return agent_id
        except (OSError, ValueError):
            agent_id = str(uuid.uuid4())
            atomic_write(agent_id_path, agent_id, mode=0o600)
            return agent_id

    def _collect_or_default(self, name: str, func, default, errors: List[CollectorError]):
        try:
            return func()
        except Exception as exc:
            errors.append(CollectorError(collector=name, message=str(exc)))
            return default

    def collect(self, path: str = ".") -> HostSnapshot:
        from .collectors.dir_tree import DirectoryTreeCollector
        from .collectors.log_finder import LogFinderCollector
        from .collectors.stale_files import StaleFileCollector

        scan_path = os.path.abspath(path)
        collector_errors: List[CollectorError] = []
        partitions = self._collect_or_default(
            "partitions",
            self.provider.get_partitions,
            [],
            collector_errors,
        )
        top_dirs = self._collect_or_default(
            "directory_tree",
            lambda: DirectoryTreeCollector().scan(scan_path),
            [],
            collector_errors,
        )
        logs = self._collect_or_default(
            "log_finder",
            lambda: LogFinderCollector().scan([scan_path]),
            [],
            collector_errors,
        )
        stales = self._collect_or_default(
            "stale_files",
            lambda: StaleFileCollector().scan([scan_path]),
            [],
            collector_errors,
        )
        violations = self._collect_or_default(
            "policy",
            lambda: self.policy_engine.evaluate(top_dirs, logs, stales),
            [],
            collector_errors,
        )
        signals = build_risk_signals(partitions, top_dirs, violations, scan_path)
        score = max((signal.score for signal in signals), default=0)

        return HostSnapshot(
            schema_version=SCHEMA_VERSION,
            host_id=self._host_id(),
            hostname=socket.gethostname(),
            platform=platform.platform(),
            timestamp=time.time(),
            scan_path=scan_path,
            partitions=partitions,
            top_dirs=top_dirs,
            logs=logs,
            stales=stales,
            policy_violations=violations,
            risk_signals=signals,
            risk_score=score,
            risk_level=risk_level(score),
            collector_errors=collector_errors,
        )
