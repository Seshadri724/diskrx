from typing import List
import psutil
from ..store.models import Partition
from .base import PlatformProvider

class WindowsProvider(PlatformProvider):
    def get_partitions(self) -> List[Partition]:
        """Implementation for Windows using psutil."""
        partitions = []
        for part in psutil.disk_partitions(all=False):
            if part.mountpoint:
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                    partitions.append(Partition(
                        device=part.device,
                        mountpoint=part.mountpoint,
                        fstype=part.fstype,
                        total_bytes=usage.total,
                        used_bytes=usage.used,
                        free_bytes=usage.free
                    ))
                except (PermissionError, OSError):
                    # Unformatted or restricted drives
                    continue
        return partitions
