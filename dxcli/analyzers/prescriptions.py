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

    def synthesize(self, logs: List[UnrotatedLog], stales: List[StaleFile]) -> List[Prescription]:
        prescriptions = []
        is_windows = sys.platform == "win32"
        
        # Log Prescriptions
        for i, log in enumerate(logs):
            if not log.has_logrotate_config:
                service_name = os.path.basename(log.path).replace('.log', '')
                if not service_name:
                    service_name = "custom_service"
                
                if is_windows:
                    template = f"# Windows does not have logrotate.\n# To reclaim space, you can manually delete or compress: {log.path}"
                    name = f"Clean up log: {service_name}"
                    target_path = log.path
                    action_type = "delete" # Allow emergency deletion on Windows
                else:
                    template = f"""# /etc/logrotate.d/{service_name}
{log.path} {{
    daily
    rotate 7
    compress
    missingok
    copytruncate
}}"""
                    name = f"Add logrotate for {service_name}"
                    target_path = f"/etc/logrotate.d/{service_name}"
                    action_type = "create_file"

                prescriptions.append(Prescription(
                    id=f"log_{i}",
                    name=name,
                    template=template,
                    risk="safe",
                    size_savings_bytes=log.size_bytes,
                    action_type=action_type,
                    target_path=target_path
                ))

        # Stale Prescriptions
        for i, stale in enumerate(stales):
            if is_windows:
                cmd = f"Remove-Item -Force '{stale.path}'"
            else:
                cmd = f"rm -f '{stale.path}'"

            prescriptions.append(Prescription(
                id=f"stale_{i}",
                name=f"Remove stale file: {os.path.basename(stale.path)}",
                template=cmd,
                risk="needs-review",
                size_savings_bytes=stale.size_bytes,
                action_type="delete",
                target_path=stale.path
            ))

        return prescriptions
