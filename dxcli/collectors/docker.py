import json
import logging
import re
import subprocess
from typing import Any, Dict, List, Optional

from ..store.models import CollectorError

logger = logging.getLogger(__name__)


class DockerCollector:
    """
    Collects Docker disk usage metrics using `docker system df --format '{{json .}}'`.
    """

    def __init__(self):
        self.last_errors: list = []

    def is_docker_available(self) -> bool:
        try:
            result = subprocess.run(
                ["docker", "info"], capture_output=True, text=True, timeout=5
            )
            return result.returncode == 0
        except (subprocess.SubprocessError, FileNotFoundError):
            return False

    def get_system_df(self) -> Optional[Dict[str, Any]]:
        """
        Runs `docker system df` and returns structured data.
        """
        self.last_errors = []
        if not self.is_docker_available():
            self.last_errors.append(
                CollectorError(
                    collector="docker",
                    message="Docker CLI or daemon is unavailable.",
                    error_type="docker_unavailable",
                )
            )
            return None

        try:
            result = subprocess.run(
                ["docker", "system", "df", "--format", "{{json .}}"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode != 0:
                self.last_errors.append(
                    CollectorError(
                        collector="docker",
                        message=f"docker system df failed: {result.stderr.strip()}",
                        error_type="docker_df_failed",
                    )
                )
                return None

            # docker system df outputs multiple JSON lines (one per resource type)
            lines = result.stdout.strip().split("\n")
            parsed = {}
            for line in lines:
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                    res_type = obj.get("Type", "")
                    parsed[res_type] = {
                        "TotalCount": obj.get("TotalCount", 0),
                        "Size": self._parse_size(obj.get("Size", "0B")),
                        "Reclaimable": self._parse_size(
                            obj.get("Reclaimable", "0B").split(" ")[0]
                        ),  # often "1.2GB (50%)"
                        "Active": obj.get("Active", 0),
                    }
                except json.JSONDecodeError:
                    pass
            return parsed
        except Exception as e:
            logger.debug(f"Docker collection failed: {e}")
            self.last_errors.append(
                CollectorError(
                    collector="docker",
                    message=f"Docker collection exception: {e}",
                    error_type="docker_exception",
                )
            )
            return None

    def get_volume_details(self) -> List[Dict[str, Any]]:
        """List Docker volumes and categorize as anonymous vs named persistent volumes."""
        if not self.is_docker_available():
            return []

        try:
            res = subprocess.run(
                ["docker", "volume", "ls", "--format", "{{json .}}"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if res.returncode != 0:
                return []

            volumes = []
            for line in res.stdout.strip().splitlines():
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                    name = obj.get("Name", "")
                    driver = obj.get("Driver", "local")
                    is_anon = bool(re.fullmatch(r"[0-9a-fA-F]{64}", name))
                    volumes.append(
                        {
                            "name": name,
                            "driver": driver,
                            "is_anonymous": is_anon,
                            "is_protected": not is_anon,
                        }
                    )
                except json.JSONDecodeError:
                    pass
            return volumes
        except Exception as e:
            logger.debug(f"get_volume_details failed: {e}")
            return []

    def get_container_log_sizes(self) -> List[Dict[str, Any]]:
        """Inspect container status and metadata for disk analysis."""
        if not self.is_docker_available():
            return []

        try:
            res = subprocess.run(
                ["docker", "ps", "-a", "--format", "{{json .}}"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if res.returncode != 0:
                return []

            containers = []
            for line in res.stdout.strip().splitlines():
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                    containers.append(
                        {
                            "id": obj.get("ID", ""),
                            "name": obj.get("Names", ""),
                            "status": obj.get("Status", ""),
                            "image": obj.get("Image", ""),
                            "is_running": "Up" in obj.get("Status", ""),
                        }
                    )
                except json.JSONDecodeError:
                    pass
            return containers
        except Exception as e:
            logger.debug(f"get_container_log_sizes failed: {e}")
            return []

    def _parse_size(self, size_str: str) -> int:
        """Parse Docker sizes, including IEC/SI spellings and whitespace."""
        if not size_str:
            return 0
        match = re.fullmatch(
            r"\s*([0-9]+(?:\.[0-9]+)?)\s*(B|KB|MB|GB|TB|KIB|MIB|GIB|TIB)\s*",
            str(size_str).upper(),
        )
        if not match:
            return 0
        number, suffix = match.groups()
        multipliers = {
            "B": 1,
            "KB": 1024,
            "MB": 1024**2,
            "GB": 1024**3,
            "TB": 1024**4,
            "KIB": 1024,
            "MIB": 1024**2,
            "GIB": 1024**3,
            "TIB": 1024**4,
        }
        return int(float(number) * multipliers[suffix])
