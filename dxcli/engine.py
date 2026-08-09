"""Shared diagnostic engine — the single source of truth for dxcli analysis.

Every consumer (CLI ``diagnose``, ``ci``, ``explain``, ``watch``, ``serve``,
TUI, enterprise ``snapshot``) calls :func:`run_diagnosis` and receives a
:class:`~dxcli.store.models.DiagnosticSnapshot`.  This eliminates the
duplicated collection/analysis paths that previously diverged across modules.
"""

import logging
import os
import time
from typing import Any, Dict, List

from .store.models import (
    CollectorError,
    DiagnosticSnapshot,
    Prescription,
)

logger = logging.getLogger(__name__)


def _collect_or_default(name, func, default, errors):
    """Run *func* and return its result, appending a CollectorError on failure."""
    try:
        return func()
    except Exception as exc:
        errors.append(CollectorError(collector=name, message=str(exc)))
        return default


def run_diagnosis(
    path: str,
    include_docker: bool = False,
    include_classification: bool = False,
    include_processes: bool = True,
    enable_plugins: bool = False,
    scan_threads: int = None,
    nice: int = None,
    ionice: bool = False,
    db=None,
    policy_engine=None,
    provider=None,
) -> DiagnosticSnapshot:
    """Run a full diagnostic pass and return a unified snapshot."""
    from .analyzers import (
        CorrelationEngine,
        DiskPredictor,
        PrescriptionEngine,
        RootCauseAnalyzer,
        StatisticalAnomalyDetector,
    )
    from .collectors.dir_tree import DirectoryTreeCollector
    from .collectors.log_finder import LogFinderCollector
    from .collectors.stale_files import StaleFileCollector
    from .policy_engine import PolicyEngine

    if provider is None:
        from .platform import provider as platform_provider

        provider = platform_provider

    if policy_engine is None:
        policy_engine = PolicyEngine()

    path = os.path.abspath(path)
    collector_errors: List[CollectorError] = []

    # -- optional niceness ---------------------------------------------------
    if nice is not None or ionice:
        _apply_niceness(nice, ionice)

    # -- partition -----------------------------------------------------------
    def _get_partition():
        if hasattr(provider, "get_partition_for_path"):
            return provider.get_partition_for_path(path)
        if hasattr(provider, "get_partitions"):
            parts = provider.get_partitions()
            if parts:
                return parts[0]
        return None

    partition = _collect_or_default(
        "partition",
        _get_partition,
        None,
        collector_errors,
    )

    # -- collectors ----------------------------------------------------------
    dir_collector = DirectoryTreeCollector(max_threads=scan_threads)
    top_dirs = _collect_or_default(
        "directory_tree",
        lambda: dir_collector.scan(path),
        [],
        collector_errors,
    )
    if hasattr(dir_collector, "last_errors") and dir_collector.last_errors:
        collector_errors.extend(dir_collector.last_errors)

    logs = _collect_or_default(
        "log_finder",
        lambda: LogFinderCollector().scan([path]),
        [],
        collector_errors,
    )
    stales = _collect_or_default(
        "stale_files",
        lambda: StaleFileCollector().scan([path]),
        [],
        collector_errors,
    )

    # -- Docker --------------------------------------------------------------
    docker_data = None
    docker_prescriptions: List[Prescription] = []
    if include_docker:
        from .analyzers.docker_analyzer import DockerAnalyzer
        from .collectors.docker import DockerCollector

        docker_collector = DockerCollector()
        docker_data = _collect_or_default(
            "docker",
            docker_collector.get_system_df,
            None,
            collector_errors,
        )
        if hasattr(docker_collector, "last_errors") and docker_collector.last_errors:
            collector_errors.extend(docker_collector.last_errors)

        if docker_data:
            volumes_info = docker_collector.get_volume_details()
            containers_info = docker_collector.get_container_log_sizes()
            docker_prescriptions = _collect_or_default(
                "docker_analyzer",
                lambda: DockerAnalyzer().analyze(
                    docker_data,
                    volumes_info=volumes_info,
                    containers_info=containers_info,
                ),
                [],
                collector_errors,
            )

    # -- database snapshot + analysers ---------------------------------------
    own_db = db is None
    if own_db:
        from .store.database import Database

        try:
            db = Database()
        except Exception as exc:
            collector_errors.append(
                CollectorError(collector="database", message=str(exc))
            )
            db = None

    trends: List[Dict[str, Any]] = []
    prediction = None
    anomalies: List[str] = []
    prescriptions: List[Prescription] = []
    violations = []

    if db is not None:
        try:
            # record snapshot
            if partition:
                try:
                    db.record_snapshot(partition, top_dirs)
                except Exception as exc:
                    logger.warning("Could not record snapshot: %s", exc)

            # root cause / correlation / history
            trends = _collect_or_default(
                "root_cause",
                lambda: RootCauseAnalyzer(db).attribute_cause(top_dirs),
                [],
                collector_errors,
            )
            correlated = _collect_or_default(
                "correlation",
                lambda: CorrelationEngine(db=db).correlate(trends),
                trends,
                collector_errors,
            )
            # attach sparkline history
            for trend in correlated:
                history = db.get_dir_history(trend["path"], limit=10)
                trend["history"] = [entry["size_bytes"] for entry in history]
            trends = correlated

            # anomaly detection
            detector = StatisticalAnomalyDetector(db)
            for node in top_dirs[:5]:
                result = detector.check_for_anomalies(node.path)
                if result:
                    anomalies.append(result)

            # prediction
            if partition:
                prediction = _collect_or_default(
                    "predictor",
                    lambda: DiskPredictor(db).predict_full_date(partition),
                    None,
                    collector_errors,
                )

            # prescriptions
            prescriptions = _collect_or_default(
                "prescriptions",
                lambda: PrescriptionEngine().synthesize(logs, stales, path),
                [],
                collector_errors,
            )
        finally:
            if own_db:
                db.close()
    else:
        # minimal analysis without db
        prescriptions = _collect_or_default(
            "prescriptions",
            lambda: PrescriptionEngine().synthesize(logs, stales, path),
            [],
            collector_errors,
        )

    # merge docker prescriptions
    prescriptions.extend(docker_prescriptions)

    # -- plugins -------------------------------------------------------------
    if enable_plugins:
        from .analyzers.plugin_loader import PluginLoader

        for plugin in PluginLoader().load_plugins():
            try:
                prescriptions.extend(plugin.analyze(top_dirs, logs, stales))
            except Exception as exc:
                collector_errors.append(
                    CollectorError(
                        collector=f"plugin:{type(plugin).__name__}", message=str(exc)
                    )
                )

    # -- policy engine -------------------------------------------------------
    violations = _collect_or_default(
        "policy",
        lambda: policy_engine.evaluate(top_dirs, logs, stales),
        [],
        collector_errors,
    )
    for violation in violations:
        anomalies.append(
            f"[{violation.severity.upper()}] {violation.rule_name}: "
            f"{violation.message} at {violation.path}"
        )

    # -- process attribution -------------------------------------------------
    app_accounting: List[Dict[str, Any]] = []
    active_writers: List[Dict[str, Any]] = []
    if include_processes:
        from .collectors.process_mapper import ProcessMapper

        mapper = ProcessMapper()
        app_accounting = _collect_or_default(
            "process_mapper",
            lambda: mapper.get_application_accounting(path),
            [],
            collector_errors,
        )
        active_writers = _collect_or_default(
            "active_writers",
            lambda: mapper.get_active_writers(path, interval=0.5),
            [],
            collector_errors,
        )

    # -- classification ------------------------------------------------------
    classification = None
    if include_classification:
        from .analyzers.classification import ClassificationEngine

        classification = _collect_or_default(
            "classification",
            lambda: ClassificationEngine().get_summary(top_dirs),
            None,
            collector_errors,
        )

    return DiagnosticSnapshot(
        path=path,
        partition=partition,
        top_dirs=top_dirs,
        logs=logs,
        stale_files=stales,
        docker=docker_data,
        trends=trends,
        prediction=prediction,
        anomalies=anomalies,
        policy_violations=violations,
        prescriptions=prescriptions,
        app_accounting=app_accounting,
        active_writers=active_writers,
        classification=classification,
        collector_errors=collector_errors,
        timestamp=time.time(),
    )


def _apply_niceness(nice=None, ionice_flag=False):
    """Best-effort CPU/IO priority adjustment (Linux only)."""
    import subprocess
    import sys

    if sys.platform != "win32":
        if nice is not None:
            try:
                os.nice(nice)
            except OSError as e:
                logger.warning("Could not set nice priority: %s", e)
        if ionice_flag:
            try:
                subprocess.run(
                    ["ionice", "-c3", "-p", str(os.getpid())],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            except Exception as e:
                logger.warning("Could not set ionice: %s", e)
