from typing import List
import psutil
import os
from ..store.models import Partition
from .base import PlatformProvider

class LinuxProvider(PlatformProvider):
    def get_partitions(self) -> List[Partition]:
        """Implementation for Linux using psutil/statvfs."""
        partitions = []
        for part in psutil.disk_partitions(all=False):
            # Ignore read-only, loop, and container isolation mounts usually
            if part.fstype in ('squashfs', 'tmpfs', 'devtmpfs'):
                continue
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
            except PermissionError:
                continue
        return partitions
