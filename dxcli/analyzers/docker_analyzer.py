from typing import Dict, Any, List
from ..store.models import Prescription

class DockerAnalyzer:
    """
    Analyzes Docker disk usage and synthesizes actionable prescriptions.
    """
    def __init__(self):
        self.reclaim_threshold_bytes = 500 * 1024 * 1024  # 500 MB

    def analyze(self, df_data: Dict[str, Any]) -> List[Prescription]:
        prescriptions = []
        if not df_data:
            return prescriptions

        # 1. Images
        images_data = df_data.get("Images", {})
        img_reclaimable = images_data.get("Reclaimable", 0)
        if img_reclaimable > self.reclaim_threshold_bytes:
            prescriptions.append(Prescription(
                id="docker_images",
                name="Prune dangling Docker images",
                description="Prune reclaimable Docker images.",
                category="docker",
                severity="medium",
                template="docker image prune -f",
                risk="safe",
                size_savings_bytes=img_reclaimable,
                action_type="manual",
                target_path=None,
                is_safe=False,
            ))

        # 2. Build Cache
        build_cache_data = df_data.get("Build Cache", {})
        bc_reclaimable = build_cache_data.get("Reclaimable", 0)
        if bc_reclaimable > self.reclaim_threshold_bytes:
            prescriptions.append(Prescription(
                id="docker_build_cache",
                name="Prune Docker build cache",
                description="Prune reclaimable Docker build cache.",
                category="docker",
                severity="medium",
                template="docker builder prune -f",
                risk="safe",
                size_savings_bytes=bc_reclaimable,
                action_type="manual",
                target_path=None,
                is_safe=False,
            ))

        # 3. Local Volumes
        volumes_data = df_data.get("Local Volumes", {})
        vol_reclaimable = volumes_data.get("Reclaimable", 0)
        # Note: Volume pruning can be slightly more risky if containers are stopped but data is needed.
        # We'll mark it as 'needs-review'
        if vol_reclaimable > self.reclaim_threshold_bytes:
            prescriptions.append(Prescription(
                id="docker_volumes",
                name="Prune unused Docker volumes",
                description="Prune reclaimable unused Docker volumes.",
                category="docker",
                severity="high",
                template="docker volume prune -f",
                risk="needs-review",
                size_savings_bytes=vol_reclaimable,
                action_type="manual",
                target_path=None,
                is_safe=False,
            ))

        return prescriptions
