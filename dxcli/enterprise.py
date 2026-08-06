import os
import platform
import socket
import time
import uuid
from typing import List

from .policy_engine import PolicyEngine
from .store.models import (
    CollectorError,
    DirNode,
    HostSnapshot,
    Partition,
    PolicyViolation,
    RiskSignal,
)

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
    gb = node.size_bytes / (1024**3)
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
    signals.extend(
        signal
        for signal in (score_partition(partition) for partition in partitions)
        if signal.score > 0
    )
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

    def _collect_or_default(
        self, name: str, func, default, errors: List[CollectorError]
    ):
        try:
            return func()
        except Exception as exc:
            errors.append(CollectorError(collector=name, message=str(exc)))
            return default

    def collect(self, path: str = ".", anonymize: bool = False) -> HostSnapshot:
        from .engine import run_diagnosis
        import hashlib
        import re

        scan_path = os.path.abspath(path)
        collector_errors: List[CollectorError] = []
        partitions = self._collect_or_default(
            "partitions",
            self.provider.get_partitions,
            [],
            collector_errors,
        )

        diag_snap = run_diagnosis(
            scan_path,
            policy_engine=self.policy_engine,
            provider=self.provider,
        )
        collector_errors.extend(diag_snap.collector_errors)

        top_dirs = diag_snap.top_dirs
        logs = diag_snap.logs
        stales = diag_snap.stale_files
        violations = diag_snap.policy_violations

        signals = build_risk_signals(partitions, top_dirs, violations, scan_path)
        score = max((signal.score for signal in signals), default=0)

        snapshot = HostSnapshot(
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

        if anonymize or os.environ.get("DX_ANONYMIZE_TELEMETRY") == "1":

            def scrub_path(p: str) -> str:
                if not p:
                    return p
                # Handle Windows C:\Users\username and Unix /home/username or /Users/username (with slash abstraction)
                p = re.sub(r"(?i)([a-zA-Z]:\\Users\\)([^\\]+)", r"\1[redacted]", p)
                p = re.sub(r"(?i)(/Users/)([^/]+)", r"\1[redacted]", p)
                p = re.sub(r"(?i)(/home/|\\home\\)([^/\\]+)", r"\1[redacted]", p)
                return p

            # Anonymize hostname via hashing
            raw_host = snapshot.hostname
            snapshot.hostname = (
                "host-" + hashlib.sha256(raw_host.encode("utf-8")).hexdigest()[:12]
            )
            snapshot.scan_path = scrub_path(snapshot.scan_path)

            for part in snapshot.partitions:
                part.mountpoint = scrub_path(part.mountpoint)

            for d in snapshot.top_dirs:
                d.path = scrub_path(d.path)

            for lg in snapshot.logs:
                lg.path = scrub_path(lg.path)

            for s in snapshot.stales:
                s.path = scrub_path(s.path)

            for v in snapshot.policy_violations:
                v.path = scrub_path(v.path)
                v.message = scrub_path(v.message)

            for r in snapshot.risk_signals:
                if r.path:
                    r.path = scrub_path(r.path)
                r.message = scrub_path(r.message)

            for e in snapshot.collector_errors:
                e.message = scrub_path(e.message)

        return snapshot
