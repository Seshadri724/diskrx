import os
import sys
from typing import List
from ..store.models import Prescription, UnrotatedLog, StaleFile

class PrescriptionEngine:
    """
    Pattern-matched remediation recommendations.
    """
    def __init__(self):
        pass

    def synthesize(self, logs: List[UnrotatedLog], stales: List[StaleFile], scan_path: str = None) -> List[Prescription]:
        prescriptions = []
        base_path = os.path.abspath(scan_path) if scan_path else os.getcwd()

        # Log Prescriptions
        for i, log in enumerate(logs):
            if not log.has_logrotate_config:
                basename = os.path.basename(log.path)
                template = f"""{log.path} {{
    daily
    rotate 7
    compress
    missingok
    notifempty
    copytruncate
}}"""
                name = f"Add logrotate config for {basename}"
                target_path = os.path.join(base_path, ".dx-prescriptions", "logrotate.d", f"dxcli-{basename}")
                action_type = "create_file"

                prescriptions.append(Prescription(
                    id=f"log_{i}",
                    name=name,
                    description=f"Generate logrotate config to rotate {log.path} automatically.",
                    category="logs",
                    severity="medium",
                    template=template,
                    risk="safe",
                    size_savings_bytes=log.size_bytes,
                    action_type=action_type,
                    target_path=target_path,
                    is_safe=True,
                ))


        # Stale Prescriptions
        for i, stale in enumerate(stales):
            prescriptions.append(Prescription(
                id=f"stale_{i}",
                name=f"Remove stale file: {os.path.basename(stale.path)}",
                description=f"Remove stale file after review: {stale.path}",
                category="stale-files",
                severity="medium",
                template=f"Delete stale file after review: {stale.path}",
                risk="needs-review",
                size_savings_bytes=stale.size_bytes,
                action_type="delete",
                target_path=stale.path,
                is_safe=False,
            ))

        # 3. Rule-based Prescriptions (Node.js, Python, etc.)
        from .rules import RuleEngine
        rule_engine = RuleEngine()
        
        rule_prescriptions = rule_engine.evaluate(base_path)
        prescriptions.extend(rule_prescriptions)

        return prescriptions
