from typing import Any, Dict, List, Optional
from ..store.models import Prescription


class DockerAnalyzer:
    """
    Analyzes Docker disk usage and synthesizes actionable prescriptions.
    Supports named volume protection and deep resource inspection.
    """

    def __init__(self):
        self.reclaim_threshold_bytes = 500 * 1024 * 1024  # 500 MB

    def analyze(
        self,
        df_data: Dict[str, Any],
        volumes_info: Optional[List[Dict[str, Any]]] = None,
        containers_info: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Prescription]:
        prescriptions = []
        if not df_data:
            return prescriptions

        # 1. Images
        images_data = df_data.get("Images", {})
        img_reclaimable = images_data.get("Reclaimable", 0)
        if img_reclaimable > self.reclaim_threshold_bytes:
            prescriptions.append(
                Prescription(
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
                    is_safe=True,
                )
            )

        # 2. Build Cache
        build_cache_data = df_data.get("Build Cache", {})
        bc_reclaimable = build_cache_data.get("Reclaimable", 0)
        if bc_reclaimable > self.reclaim_threshold_bytes:
            prescriptions.append(
                Prescription(
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
                    is_safe=True,
                )
            )

        # 3. Local Volumes (with Named Volume Protection)
        volumes_data = df_data.get("Local Volumes", {})
        vol_reclaimable = volumes_data.get("Reclaimable", 0)
        if vol_reclaimable > self.reclaim_threshold_bytes:
            named_count = 0
            if volumes_info:
                named_count = sum(1 for v in volumes_info if v.get("is_protected"))

            if named_count > 0:
                # Protection alert for named persistent volumes
                prescriptions.append(
                    Prescription(
                        id="docker_named_volumes_protected",
                        name=f"Review {named_count} named persistent Docker volume(s)",
                        description=(
                            f"{named_count} named persistent volume(s) detected. "
                            "Named volumes are protected from automatic deletion to prevent data loss."
                        ),
                        category="docker",
                        severity="high",
                        template="docker volume ls --filter dangling=true",
                        risk="needs-review",
                        size_savings_bytes=vol_reclaimable,
                        action_type="manual",
                        target_path=None,
                        is_safe=False,
                    )
                )

            # Safe prune template targeting anonymous volumes only if available
            vol_cmd = (
                "docker volume prune -f --filter label!=keep"
                if named_count > 0
                else "docker volume prune -f"
            )
            prescriptions.append(
                Prescription(
                    id="docker_volumes",
                    name="Prune unused Docker volumes",
                    description="Prune reclaimable unused Docker volumes.",
                    category="docker",
                    severity="high",
                    template=vol_cmd,
                    risk="needs-review",
                    size_savings_bytes=vol_reclaimable,
                    action_type="manual",
                    target_path=None,
                    is_safe=False,
                )
            )

        # 4. Stopped Containers
        containers_data = df_data.get("Containers", {})
        cnt_reclaimable = containers_data.get("Reclaimable", 0)
        if cnt_reclaimable > self.reclaim_threshold_bytes:
            prescriptions.append(
                Prescription(
                    id="docker_containers",
                    name="Prune stopped Docker containers",
                    description="Prune stopped Docker containers releasing log/layer disk space.",
                    category="docker",
                    severity="medium",
                    template="docker container prune -f",
                    risk="safe",
                    size_savings_bytes=cnt_reclaimable,
                    action_type="manual",
                    target_path=None,
                    is_safe=True,
                )
            )

        return prescriptions
