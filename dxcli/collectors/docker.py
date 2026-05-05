import subprocess
import json
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class DockerCollector:
    """
    Collects Docker disk usage metrics using `docker system df --format '{{json .}}'`.
    """
    def __init__(self):
        pass

    def is_docker_available(self) -> bool:
        try:
            result = subprocess.run(["docker", "info"], capture_output=True, text=True, timeout=5)
            return result.returncode == 0
        except (subprocess.SubprocessError, FileNotFoundError):
            return False

    def get_system_df(self) -> Optional[Dict[str, Any]]:
        """
        Runs `docker system df` and returns structured data.
        """
        if not self.is_docker_available():
            return None

        try:
            result = subprocess.run(
                ["docker", "system", "df", "--format", "{{json .}}"],
                capture_output=True,
                text=True,
                timeout=15
            )
            if result.returncode != 0:
                return None

            # docker system df outputs multiple JSON lines (one per resource type)
            lines = result.stdout.strip().split('\n')
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
                        "Reclaimable": self._parse_size(obj.get("Reclaimable", "0B").split(" ")[0]), # often "1.2GB (50%)"
                        "Active": obj.get("Active", 0)
                    }
                except json.JSONDecodeError:
                    pass
            return parsed
        except Exception as e:
            logger.debug(f"Docker collection failed: {e}")
            return None

    def _parse_size(self, size_str: str) -> int:
        """Parse sizes like '1.2GB', '500MB', '0B' into bytes."""
        if not size_str: return 0
        s = size_str.upper().strip()
        multipliers = {'KB': 1024, 'MB': 1024**2, 'GB': 1024**3, 'TB': 1024**4, 'B': 1}
        for suffix, multiplier in multipliers.items():
            if s.endswith(suffix):
                try:
                    num = float(s.replace(suffix, '').strip())
                    return int(num * multiplier)
                except ValueError:
                    return 0
        return 0
