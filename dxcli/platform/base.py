import logging
from typing import List, Optional
from ..store.models import Partition

logger = logging.getLogger(__name__)


class PlatformProvider:
    """Abstract interface for OS-specific data fetching."""

    def get_partitions(self) -> List[Partition]:
        """Return all mounted physical partitions."""
        raise NotImplementedError

    def get_partition_for_path(self, path: str) -> "Optional[Partition]":
        """Resolve a path to its hosting partition."""
        import os

        try:
            parts = self.get_partitions()
            path_norm = (
                os.path.abspath(path).lower()
                if os.name == "nt"
                else os.path.abspath(path)
            )

            # Sort by length descending to match the most specific mountpoint
            parts.sort(key=lambda p: len(p.mountpoint), reverse=True)

            for p in parts:
                p_mount = p.mountpoint.lower() if os.name == "nt" else p.mountpoint
                if path_norm.startswith(p_mount):
                    return p
        except Exception as exc:
            logger.warning("Failed to resolve partition for %s: %s", path, exc)
        return None
